"""
smoke_test.py — 分層快速驗證

Layer 1  --check-config   : YAML 載入 + import 檢查（無需任何外部服務）
Layer 2  --check-db        : pgvector 連線 + schema 驗證（需要 Docker）
Layer 3  --check-ollama    : Embedding + LLM 連線測試（需要 Ollama）
Layer 4  --phase1-mini     : Phase 1 完整 mini-run（n_clean=1，1 query，1 iter）
Layer 5  --full            : 完整四階段 mini-run（Phase 1-4）

用法：
    python scripts/smoke_test.py --check-config
    python scripts/smoke_test.py --check-db
    python scripts/smoke_test.py --check-ollama
    python scripts/smoke_test.py --phase1-mini
    python scripts/smoke_test.py --full
    python scripts/smoke_test.py --all        # 依序跑全部
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 確保無論從哪個目錄執行，都能找到 src/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
os.chdir(_PROJECT_ROOT)

CONFIG_PATH  = "configs/experiment_01.yaml"
QUERIES_PATH = "data/queries.json"


def sep(title: str) -> None:
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


def ok(msg: str) -> None:
    print(f"  [OK]  {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    sys.exit(1)


# ── Layer 1: Config & imports ─────────────────────────────────────────────────

def check_config() -> None:
    sep("Layer 1 — Config & imports")
    try:
        from src.config import ExperimentConfig
        cfg = ExperimentConfig.from_yaml(CONFIG_PATH)
        ok(f"YAML loaded: attacker={cfg.attacker_model}, target={cfg.target_model}")
        ok(f"  n_clean_chunks={cfg.n_clean_chunks}, n_retrieved_per_query={cfg.n_retrieved_per_query}")
        ok(f"  defense pre_injection thresholds: "
           f"global={cfg.defense['pre_injection']['global_ppl_threshold']} "
           f"spike={cfg.defense['pre_injection']['spike_ppl_threshold']}")
    except Exception as e:
        fail(f"Config load failed: {e}")

    try:
        from src.pipeline.phase1 import Phase1Generator, PoisonChunk
        from src.pipeline.phase2 import Phase2Injector
        from src.pipeline.phase3 import Phase3Retriever
        from src.pipeline.phase4 import Phase4Generator
        from src.defense.filter import PPLDefenseFilter
        ok("All pipeline imports OK")
    except Exception as e:
        fail(f"Import error: {e}")

    # Verify PoisonChunk has new fields
    import dataclasses
    from src.pipeline.phase1 import PoisonChunk
    fields = {f.name for f in dataclasses.fields(PoisonChunk)}
    for required in ("original_chunk_id", "original_chunk_text"):
        if required in fields:
            ok(f"PoisonChunk has '{required}' field")
        else:
            fail(f"PoisonChunk missing '{required}' field")


# ── Layer 2: pgvector DB ──────────────────────────────────────────────────────

def check_db() -> None:
    sep("Layer 2 — pgvector connectivity + schema")
    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector
        from src.config import ExperimentConfig

        cfg = ExperimentConfig.from_yaml(CONFIG_PATH)
        db  = cfg.vector_db
        conn = psycopg2.connect(
            host=db.get("host", "localhost"),
            port=db.get("port", 5432),
            dbname=db.get("database", "rag_poison"),
            user=db.get("user", "postgres"),
            password=os.environ.get("PGPASSWORD", "postgres"),
        )
        register_vector(conn)
        ok("pgvector connection established")
    except Exception as e:
        fail(f"DB connection failed: {e}\n"
             "  → 請確認 Docker 已啟動：docker compose up -d")

    # Check schema columns
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'chunks'
            ORDER BY ordinal_position;
        """)
        cols = {row[0] for row in cur.fetchall()}

    for required_col in ("chunk_id", "document", "embedding", "is_original", "is_poison", "attack_type"):
        if required_col in cols:
            ok(f"Column '{required_col}' exists")
        else:
            fail(f"Column '{required_col}' missing in chunks table\n"
                 "  → 請重建 DB schema：\n"
                 "    docker compose down -v && docker compose up -d")

    # Count existing rows
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*), SUM(CASE WHEN is_original THEN 1 ELSE 0 END) FROM chunks;")
        total, originals = cur.fetchone()
    ok(f"chunks table: total={total}, is_original={originals or 0}")
    conn.close()


# ── Layer 3: Ollama connectivity ──────────────────────────────────────────────

def check_ollama() -> None:
    sep("Layer 3 — Ollama connectivity (embed + LLM)")
    from src.config import ExperimentConfig
    cfg = ExperimentConfig.from_yaml(CONFIG_PATH)

    # Embedding test
    try:
        import ollama
        t = time.perf_counter()
        resp = ollama.embed(model=cfg.embedding_model, input="test connectivity")
        elapsed = time.perf_counter() - t
        dim = len(resp.embeddings[0])
        ok(f"Embedding ({cfg.embedding_model}): dim={dim}, {elapsed:.1f}s")
    except Exception as e:
        fail(f"Embedding failed: {e}\n  → ollama pull {cfg.embedding_model}")

    # LLM test (attacker)
    try:
        t = time.perf_counter()
        resp = ollama.chat(
            model=cfg.attacker_model,
            messages=[{"role": "user", "content": "Reply with one word: OK"}],
        )
        elapsed = time.perf_counter() - t
        ok(f"Attacker LLM ({cfg.attacker_model}): replied in {elapsed:.1f}s → '{resp.message.content[:30]}'")
    except Exception as e:
        fail(f"Attacker LLM failed: {e}\n  → ollama pull {cfg.attacker_model}")


# ── Layer 4: Phase 1 mini-run ─────────────────────────────────────────────────

def phase1_mini() -> None:
    sep("Layer 4 — Phase 1 mini-run (n_clean=1, 1 query, 1 iter)")
    from src.config import ExperimentConfig
    from src.pipeline.phase1 import Phase1Generator

    cfg = ExperimentConfig.from_yaml(CONFIG_PATH)
    cfg.n_clean_chunks        = 1    # 只載 1 筆原始 chunk
    cfg.n_retrieved_per_query = 1    # 只撈 1 筆
    cfg.max_iter              = 1    # 只跑 1 輪
    cfg.n_poison_chunks       = 1

    queries = json.loads(Path(QUERIES_PATH).read_text(encoding="utf-8"))
    q = queries[0]  # 只跑第一個 query

    out = "output/tests/phase1_mini.json"

    try:
        t = time.perf_counter()
        gen = Phase1Generator(cfg)
        results = gen.run(
            queries=[q],
            output_path=out,
            attack_types=["hijack"],   # 只跑 hijack
        )
        elapsed = time.perf_counter() - t

        r = results[0]
        ok(f"Phase 1 completed in {elapsed:.1f}s")
        ok(f"  accepted={r.accepted}  iter={r.iteration_count}")
        ok(f"  original_chunk_id={r.original_chunk_id}")
        ok(f"  sim={r.final_sim_score}  stealth={r.final_stealth_score}  payload={r.final_payload_score}")
        ok(f"  output → {out}")
    except Exception as e:
        fail(f"Phase 1 mini-run failed: {e}")


# ── Layer 5: Full pipeline mini-run ──────────────────────────────────────────

def full_mini() -> None:
    sep("Layer 5 — Full pipeline mini-run (Phase 1-4)")
    from src.config import ExperimentConfig

    cfg = ExperimentConfig.from_yaml(CONFIG_PATH)
    cfg.n_clean_chunks        = 2
    cfg.n_retrieved_per_query = 1
    cfg.max_iter              = 1
    cfg.n_poison_chunks       = 1
    cfg.n_cdr_chunks          = 2
    cfg.top_k                 = [3]

    queries = json.loads(Path(QUERIES_PATH).read_text(encoding="utf-8"))
    q_mini  = queries[:1]   # 只跑第一個 query

    p1_out  = "output/tests/mini_poison.json"
    p2_out  = "output/tests/mini_audit_a.jsonl"
    p3_out  = "output/tests/mini_retrieval.json"
    p3_audit= "output/tests/mini_audit_b.jsonl"
    p4_out  = "output/tests/mini_phase4.json"

    try:
        # Phase 1
        from src.pipeline.phase1 import Phase1Generator
        t = time.perf_counter()
        Phase1Generator(cfg).run(q_mini, p1_out, attack_types=["hijack"])
        ok(f"Phase 1: {time.perf_counter()-t:.1f}s")

        # Phase 2
        from src.pipeline.phase2 import Phase2Injector
        t = time.perf_counter()
        Phase2Injector(cfg).run(p1_out, p2_out)
        ok(f"Phase 2: {time.perf_counter()-t:.1f}s")

        # Phase 3
        from src.pipeline.phase3 import Phase3Retriever
        t = time.perf_counter()
        Phase3Retriever(cfg).run(QUERIES_PATH, p3_out, p3_audit)
        ok(f"Phase 3: {time.perf_counter()-t:.1f}s")

        # Phase 4
        from src.pipeline.phase4 import Phase4Generator
        t = time.perf_counter()
        Phase4Generator(cfg).run(p3_out, QUERIES_PATH, p4_out)
        ok(f"Phase 4: {time.perf_counter()-t:.1f}s")

        ok(f"Full mini-run complete! Check output/tests/")
    except Exception as e:
        import traceback
        fail(f"Full mini-run failed:\n{traceback.format_exc()}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Smoke test for RAG poisoning pipeline")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-config",  action="store_true", help="Layer 1: imports + config")
    group.add_argument("--check-db",      action="store_true", help="Layer 2: pgvector + schema")
    group.add_argument("--check-ollama",  action="store_true", help="Layer 3: Ollama LLM + embed")
    group.add_argument("--phase1-mini",   action="store_true", help="Layer 4: Phase 1 mini-run")
    group.add_argument("--full",          action="store_true", help="Layer 5: Phase 1-4 mini-run")
    group.add_argument("--all",           action="store_true", help="Run all layers in order")
    args = parser.parse_args()

    if args.all:
        check_config()
        check_db()
        check_ollama()
        phase1_mini()
        full_mini()
    elif args.check_config:  check_config()
    elif args.check_db:      check_db()
    elif args.check_ollama:  check_ollama()
    elif args.phase1_mini:   phase1_mini()
    elif args.full:          full_mini()

    print(f"\n{'='*55}")
    print("  Done.")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
