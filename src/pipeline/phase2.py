"""
Phase 2 — Injection + Pre-Storage Defense (Defense Point A)

流程：
  1. 從 CUAD 載入 n_clean_chunks 筆乾淨 chunk（300-token，50-token overlap）
  2. 載入全部 Phase 1 poison chunks（通常 15 筆）
  3. 合併後跑 Defense Filter A（PPL）：惡意→跳過；乾淨→嵌入寫入 pgvector
  4. 寫出 output/audit_defense_a.jsonl

n_clean_chunks 由 config 控制：
  1   → 快速測試（~15-30s）
  500 → 完整實驗（~10-15min，含統計意義的 CDR）
"""

import json
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import tiktoken
from tqdm import tqdm

if TYPE_CHECKING:
    from src.config import ExperimentConfig

_ENC_NAME      = "cl100k_base"
_CHUNK_TOKENS  = 300
_CHUNK_OVERLAP = 50


class Phase2Injector:
    """
    Loads CUAD clean corpus + Phase 1 poison chunks, runs Defense A, writes to pgvector.

    n_clean_chunks (from config) controls trade-off between speed and CDR statistics:
      1   → fast test, ~15-30s total
      500 → full experiment, ~10-15min
    """

    def __init__(self, config: "ExperimentConfig"):
        self.config = config
        self._enc   = tiktoken.get_encoding(_ENC_NAME)

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, poison_chunks_path: str, output_audit_path: str) -> None:
        rng           = random.Random(self.config.seed)
        n_clean       = self.config.n_clean_chunks

        print(f"[Phase2] Loading {n_clean} clean chunk(s) from CUAD...")
        clean_chunks  = self._load_cuad_chunks(n_clean, rng)
        print(f"[Phase2] {len(clean_chunks)} clean chunks loaded.")

        print("[Phase2] Loading Phase 1 poison chunks...")
        poison_chunks = self._load_poison_chunks(poison_chunks_path)
        total_poison  = len(poison_chunks)
        n_poison = getattr(self.config, "n_poison_chunks", None)
        if n_poison is not None and n_poison < total_poison:
            poison_chunks = rng.sample(poison_chunks, n_poison)
            print(f"[Phase2] Sampled {n_poison} / {total_poison} poison chunks.")
        else:
            print(f"[Phase2] {total_poison} poison chunks loaded.")

        from src.defense.filter import PPLDefenseFilter
        defense_a = PPLDefenseFilter.from_config(self.config, "pre_injection")

        candidates    = clean_chunks + poison_chunks
        rng.shuffle(candidates)
        print(f"[Phase2] {len(clean_chunks)} clean + {len(poison_chunks)} poison = {len(candidates)} total")

        conn = self._connect()
        self._clear_table(conn)

        records: list[dict] = []
        inserted = blocked  = 0

        for chunk in tqdm(candidates, desc="  Defense-A + embed", unit="chunk"):
            is_malicious, score = defense_a.predict(chunk["document"])
            records.append({
                "chunk_id":               chunk["chunk_id"],
                "stage":                  "pre_injection",
                "defense_score":          score,
                "predicted_is_malicious": is_malicious,
                "ground_truth_is_poison": chunk["is_poison"],
                "source":                 chunk["source"],
                "attack_type":            chunk.get("attack_type"),
                "n_clean_chunks":         n_clean,
                "processed_at":           _now_iso(),
            })

            if is_malicious:
                blocked += 1
                continue

            embedding = self._embed(chunk["document"])
            self._insert_chunk(conn, chunk, embedding)
            inserted += 1

        conn.close()
        self._print_metrics(records, inserted, blocked)

        _write_jsonl(Path(output_audit_path), records)
        print(f"[Phase2] Audit log → {output_audit_path}  ({len(records)} records)")

        report_path = Path(output_audit_path).parent / "report.md"
        _write_report(report_path, records, inserted, blocked, self.config)
        print(f"[Phase2] Report    → {report_path}")

    # ── CUAD corpus loading + chunking ────────────────────────────────────────

    def _load_cuad_chunks(self, max_chunks: int, rng: random.Random) -> list[dict]:
        # Download only the SQuAD-format JSON; avoids PDF files in the same repo
        # (PDF filenames exceed Windows MAX_PATH and require pdfplumber to decode)
        from huggingface_hub import hf_hub_download

        print("[Phase2] Loading CUAD_v1.json (HF Hub cache)...")
        local_path = hf_hub_download(
            repo_id="theatticusproject/cuad",
            repo_type="dataset",
            filename="CUAD_v1/CUAD_v1.json",
        )

        with open(local_path, encoding="utf-8") as f:
            data = json.load(f)

        # SQuAD format: {"data": [{"title": ..., "paragraphs": [{"context": ...}]}]}
        chunks: list[dict] = []
        for entry in data["data"]:
            context = entry["paragraphs"][0]["context"]
            if len(context) > 200:
                chunks.extend(self._chunk_text(context, entry["title"]))
            if len(chunks) >= max_chunks:
                break

        chunks = chunks[:max_chunks]
        rng.shuffle(chunks)
        return chunks

    def _chunk_text(self, text: str, doc_id: str) -> list[dict]:
        tokens = self._enc.encode(text)
        chunks: list[dict] = []
        idx = 0
        start = 0
        while start < len(tokens):
            end        = min(start + _CHUNK_TOKENS, len(tokens))
            chunk_text = self._enc.decode(tokens[start:end])
            if chunk_text.strip():
                chunks.append({
                    "chunk_id":    f"clean_{uuid.uuid4().hex[:8]}",
                    "document":    chunk_text,
                    "doc_id":      doc_id,
                    "source":      "cuad",
                    "is_poison":   False,
                    "attack_type": None,
                    "chunk_index": idx,
                })
                idx += 1
            start += _CHUNK_TOKENS - _CHUNK_OVERLAP
        return chunks

    # ── Phase 1 poison loading ─────────────────────────────────────────────────

    def _load_poison_chunks(self, path: str) -> list[dict]:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return [
            {
                "chunk_id":    item["chunk_id"],
                "document":    item["generated_text"],
                "doc_id":      f"poison_{item['target_query_id']}",
                "source":      "phase1_poison",
                "is_poison":   True,
                "attack_type": item["attack_type"],
                "chunk_index": 0,
            }
            for item in raw
        ]

    # ── Embedding ─────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        import ollama
        resp = ollama.embed(model=self.config.embedding_model, input=text)
        return resp.embeddings[0]

    # ── pgvector DB helpers ───────────────────────────────────────────────────

    def _connect(self):
        import psycopg2
        from pgvector.psycopg2 import register_vector

        db   = self.config.vector_db
        conn = psycopg2.connect(
            host=db.get("host", "localhost"),
            port=db.get("port", 5432),
            dbname=db.get("database", "rag_poison"),
            user=db.get("user", "postgres"),
            password=os.environ.get("PGPASSWORD", "postgres"),
        )
        register_vector(conn)
        return conn

    def _clear_table(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks;")
        conn.commit()

    def _insert_chunk(self, conn, chunk: dict, embedding: list[float]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chunks
                    (chunk_id, document, embedding, doc_id, source,
                     is_poison, attack_type, chunk_index)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO NOTHING;
                """,
                (
                    chunk["chunk_id"],
                    chunk["document"],
                    np.array(embedding),
                    chunk["doc_id"],
                    chunk["source"],
                    chunk["is_poison"],
                    chunk.get("attack_type"),
                    chunk.get("chunk_index", 0),
                ),
            )
        conn.commit()

    # ── Metrics display ───────────────────────────────────────────────────────

    @staticmethod
    def _print_metrics(records: list[dict], inserted: int, blocked: int) -> None:
        poison = [r for r in records if r["ground_truth_is_poison"]]
        clean  = [r for r in records if not r["ground_truth_is_poison"]]
        dbr = sum(1 for r in poison if r["predicted_is_malicious"]) / max(len(poison), 1)
        cdr = sum(1 for r in clean  if r["predicted_is_malicious"]) / max(len(clean),  1)
        print(f"[Phase2]   inserted={inserted}  blocked={blocked}")
        print(f"[Phase2]   DBR-A={dbr:.2%}  CDR-A={cdr:.2%}")


# ── Module-level helpers ──────────────────────────────────────────────────────

def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_report(path: Path, records: list[dict], inserted: int, blocked: int, config) -> None:
    poison = [r for r in records if r["ground_truth_is_poison"]]
    clean  = [r for r in records if not r["ground_truth_is_poison"]]

    dbr = sum(1 for r in poison if r["predicted_is_malicious"]) / max(len(poison), 1)
    cdr = sum(1 for r in clean  if r["predicted_is_malicious"]) / max(len(clean),  1)

    # Per-attack-type breakdown
    attack_types = sorted({r["attack_type"] for r in poison if r["attack_type"]})
    attack_rows  = []
    for at in attack_types:
        group   = [r for r in poison if r["attack_type"] == at]
        caught  = sum(1 for r in group if r["predicted_is_malicious"])
        scores  = [r["defense_score"] for r in group]
        avg_s   = sum(scores) / len(scores) if scores else 0.0
        attack_rows.append((at, len(group), caught, f"{caught/len(group):.0%}", f"{avg_s:.3f}"))

    lines = [
        "# Phase 2 — Experiment Report",
        "",
        f"**Run time**: {_now_iso()}  ",
        f"**Config**: `configs/experiment_01.yaml`  ",
        f"**Defense method**: PPL Filtering (GPT-2 small, global + sliding-window spike)  ",
        f"**Thresholds (Defense A)**: global_ppl=80, spike_ppl=120  ",
        "",
        "---",
        "",
        "## Dataset",
        "",
        f"| Item | Value |",
        f"|------|-------|",
        f"| Clean chunks (CUAD) | {len(clean)} |",
        f"| Poison chunks (Phase 1) | {len(poison)} |",
        f"| Total candidates | {len(records)} |",
        f"| Embedding model | {config.embedding_model} |",
        f"| Chunk size | {_CHUNK_TOKENS} tokens / {_CHUNK_OVERLAP} overlap |",
        "",
        "---",
        "",
        "## Defense Point A — Results",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Chunks inserted into pgvector | {inserted} |",
        f"| Chunks blocked (not inserted) | {blocked} |",
        f"| **DBR-A** (poison caught / total poison) | **{dbr:.2%}** |",
        f"| **CDR-A** (clean wrongly blocked / total clean) | **{cdr:.2%}** |",
        "",
        "### Per-Attack-Type Breakdown",
        "",
        "| Attack Type | Total | Caught | DBR | Avg Score |",
        "|-------------|-------|--------|-----|-----------|",
    ]
    for at, total, caught, dbr_pct, avg_s in attack_rows:
        lines.append(f"| {at} | {total} | {caught} | {dbr_pct} | {avg_s} |")

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        f"- `n_clean_chunks={config.n_clean_chunks}` — increase for statistically robust CDR measurement",
        "- DBR-A is expected to be low for **Stealth** attacks (designed to maintain low PPL)",
        "- **Blocker** and **Hijack** should show higher DBR due to unnatural language patterns",
        "- Audit log with per-chunk details: `output/audit_defense_a.jsonl`",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
