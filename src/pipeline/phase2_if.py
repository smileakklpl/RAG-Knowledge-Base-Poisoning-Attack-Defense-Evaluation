"""
Phase 2 (IF) — Injection + Isolation Forest Defense (Defense Point A)

Replaces phase2.py (PPL) with embedding-space anomaly detection.

Flow:
  1. Load Phase 1 poison chunks from output/phase1/poison_chunks.json
  2. Read clean chunk embeddings from pgvector (is_original=TRUE) → fit IsolationForest
  3. For each poison chunk:
       embed → IF.predict() → is_malicious? → DELETE (skip) : INSERT with trust_score
  4. CDR test: run fresh CUAD chunks through IF, measure false-positive rate
  5. Write output/phase2_if/audit_defense_a_if.jsonl + report.md
"""

import json
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from tqdm import tqdm

if TYPE_CHECKING:
    from src.config import ExperimentConfig


class Phase2InjectorIF:
    """
    Loads Phase 1 poison chunks, fits IsolationForest on clean DB embeddings,
    scores each poison chunk, and writes survivors to pgvector with trust_score.
    Then runs CDR test using n_cdr_chunks fresh CUAD chunks.
    """

    def __init__(self, config: "ExperimentConfig"):
        self.config = config

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, poison_chunks_path: str, output_audit_path: str) -> None:
        from src.defense.isolation_forest_filter import IsolationForestFilter

        conn = self._connect()

        # Step 1 — Train IF on clean embeddings already in DB
        print("[Phase2-IF] Loading clean embeddings from pgvector (is_original=TRUE)...")
        clean_embeddings, clean_ids = self._load_clean_embeddings(conn)
        print(f"[Phase2-IF] {len(clean_embeddings)} clean embeddings loaded.")

        defense_a = IsolationForestFilter.from_config(self.config)
        defense_a.fit(clean_embeddings)

        # Step 2 — Process poison chunks
        poison_chunks = self._load_poison_chunks(poison_chunks_path)
        n_poison = getattr(self.config, "n_poison_chunks", None)
        if n_poison is not None and n_poison < len(poison_chunks):
            rng = random.Random(self.config.seed)
            poison_chunks = rng.sample(poison_chunks, n_poison)
            print(f"[Phase2-IF] Sampled {n_poison} / {len(poison_chunks)} poison chunks.")
        else:
            print(f"[Phase2-IF] {len(poison_chunks)} poison chunks to process.")

        poison_records: list[dict] = []
        inserted = blocked = 0

        for chunk in tqdm(poison_chunks, desc="  Defense-A-IF (poison)", unit="chunk"):
            embedding    = self._embed(chunk["document"])
            is_malicious, trust_score = defense_a.predict(embedding)

            poison_records.append({
                "chunk_id":               chunk["chunk_id"],
                "stage":                  "pre_injection",
                "split":                  "poison",
                "defense_score":          trust_score,
                "predicted_is_malicious": is_malicious,
                "ground_truth_is_poison": True,
                "source":                 chunk["source"],
                "attack_type":            chunk.get("attack_type"),
                "original_chunk_id":      chunk.get("original_chunk_id", ""),
                "processed_at":           _now_iso(),
            })

            if is_malicious:
                blocked += 1
                continue

            self._insert_chunk(conn, chunk, embedding, trust_score)
            inserted += 1

        # Step 3 — CDR test (fresh CUAD chunks, different seed)
        n_cdr = getattr(self.config, "n_cdr_chunks", 20)
        print(f"\n[Phase2-IF] CDR test: loading {n_cdr} fresh CUAD chunks (seed+1)...")
        cdr_chunks  = self._load_cdr_chunks(n_cdr)
        cdr_records: list[dict] = []
        cdr_blocked = 0

        for chunk in tqdm(cdr_chunks, desc="  Defense-A-IF (CDR)", unit="chunk"):
            embedding    = self._embed(chunk["document"])
            is_malicious, trust_score = defense_a.predict(embedding)
            cdr_records.append({
                "chunk_id":               chunk["chunk_id"],
                "stage":                  "pre_injection",
                "split":                  "cdr",
                "defense_score":          trust_score,
                "predicted_is_malicious": is_malicious,
                "ground_truth_is_poison": False,
                "source":                 chunk["source"],
                "attack_type":            None,
                "original_chunk_id":      "",
                "processed_at":           _now_iso(),
            })
            if is_malicious:
                cdr_blocked += 1

        conn.close()

        all_records = poison_records + cdr_records
        self._print_metrics(poison_records, cdr_records, inserted, blocked, cdr_blocked)

        _write_jsonl(Path(output_audit_path), all_records)
        print(f"[Phase2-IF] Audit log → {output_audit_path}  ({len(all_records)} records)")

        report_path = Path(output_audit_path).parent / "report.md"
        _write_report(
            report_path, poison_records, cdr_records,
            inserted, blocked, cdr_blocked, self.config,
            self._chunk_tokens, self._chunk_overlap,
        )
        print(f"[Phase2-IF] Report    → {report_path}")

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _load_clean_embeddings(self, conn) -> tuple[list[list[float]], list[str]]:
        """Read all is_original=TRUE embeddings from pgvector for IF training."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, embedding FROM chunks WHERE is_original = TRUE;"
            )
            rows = cur.fetchall()
        chunk_ids  = [r[0] for r in rows]
        embeddings = [list(r[1]) for r in rows]
        return embeddings, chunk_ids

    def _insert_chunk(
        self, conn, chunk: dict, embedding: list[float], trust_score: float
    ) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO chunks
                    (chunk_id, document, embedding, doc_id, source,
                     is_original, is_poison, attack_type, chunk_index, trust_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO NOTHING;
                """,
                (
                    chunk["chunk_id"],
                    chunk["document"],
                    np.array(embedding),
                    chunk["doc_id"],
                    chunk["source"],
                    False,        # is_original
                    True,         # is_poison
                    chunk.get("attack_type"),
                    chunk.get("chunk_index", 0),
                    trust_score,
                ),
            )
        conn.commit()

    def _connect(self):
        import psycopg2
        from pgvector.psycopg2 import register_vector

        db   = self.config.vector_db
        conn = psycopg2.connect(
            host    = db.get("host",     "localhost"),
            port    = db.get("port",     5432),
            dbname  = db.get("database", "rag_poison_if"),
            user    = db.get("user",     "postgres"),
            password= os.environ.get("PGPASSWORD", "postgres"),
        )
        register_vector(conn)
        return conn

    # ── Chunk loading ─────────────────────────────────────────────────────────

    def _load_poison_chunks(self, path: str) -> list[dict]:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return [
            {
                "chunk_id":          item["chunk_id"],
                "document":          item["generated_text"],
                "doc_id":            f"poison_{item['target_query_id']}",
                "source":            "phase1_poison",
                "attack_type":       item["attack_type"],
                "original_chunk_id": item.get("original_chunk_id", ""),
                "chunk_index":       0,
            }
            for item in raw
        ]

    def _load_cdr_chunks(self, max_chunks: int) -> list[dict]:
        """Load fresh CUAD chunks (seed+1) for CDR false-positive testing."""
        import tiktoken
        from huggingface_hub import hf_hub_download

        chunking           = getattr(self.config, "chunking", {}) or {}
        enc_name           = chunking.get("tokenizer_encoding", "cl100k_base")
        self._chunk_tokens  = chunking.get("chunk_size_tokens",  300)
        self._chunk_overlap = chunking.get("overlap_tokens",      50)
        enc = tiktoken.get_encoding(enc_name)

        local_path = hf_hub_download(
            repo_id   = "theatticusproject/cuad",
            repo_type = "dataset",
            filename  = "CUAD_v1/CUAD_v1.json",
        )
        with open(local_path, encoding="utf-8") as f:
            data = json.load(f)

        rng    = random.Random(self.config.seed + 1)
        chunks: list[dict] = []
        for entry in data["data"]:
            context = entry["paragraphs"][0]["context"]
            if len(context) > 200:
                tokens = enc.encode(context)
                start  = 0
                while start < len(tokens):
                    end        = min(start + self._chunk_tokens, len(tokens))
                    chunk_text = enc.decode(tokens[start:end])
                    if chunk_text.strip():
                        chunks.append({
                            "chunk_id": f"cdr_{uuid.uuid4().hex[:8]}",
                            "document": chunk_text,
                            "source":   "cuad_cdr",
                        })
                    start += self._chunk_tokens - self._chunk_overlap
            if len(chunks) >= max_chunks:
                break

        chunks = chunks[:max_chunks]
        rng.shuffle(chunks)
        return chunks

    # ── Embedding ─────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        import ollama
        resp = ollama.embed(model=self.config.embedding_model, input=text)
        return resp.embeddings[0]

    # ── Metrics ───────────────────────────────────────────────────────────────

    @staticmethod
    def _print_metrics(
        poison_records: list[dict],
        cdr_records:    list[dict],
        inserted:       int,
        blocked:        int,
        cdr_blocked:    int,
    ) -> None:
        total_poison = len(poison_records)
        dbr = blocked     / max(total_poison,        1)
        cdr = cdr_blocked / max(len(cdr_records), 1)
        print(f"[Phase2-IF]   inserted={inserted}  blocked={blocked}/{total_poison}")
        print(f"[Phase2-IF]   DBR-A={dbr:.2%}  CDR-A={cdr:.2%}  (CDR n={len(cdr_records)})")


# ── Module-level helpers ──────────────────────────────────────────────────────

def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_report(
    path:           Path,
    poison_records: list[dict],
    cdr_records:    list[dict],
    inserted:       int,
    blocked:        int,
    cdr_blocked:    int,
    config,
    chunk_tokens:   int = 300,
    chunk_overlap:  int = 50,
) -> None:
    total_poison = len(poison_records)
    dbr = blocked     / max(total_poison,        1)
    cdr = cdr_blocked / max(len(cdr_records), 1)

    defense   = getattr(config, "defense", {}) or {}
    if_cfg    = defense.get("isolation_forest", {})

    attack_types = sorted({r["attack_type"] for r in poison_records if r["attack_type"]})
    attack_rows  = []
    for at in attack_types:
        group  = [r for r in poison_records if r["attack_type"] == at]
        caught = sum(1 for r in group if r["predicted_is_malicious"])
        scores = [r["defense_score"] for r in group]
        avg_s  = sum(scores) / len(scores) if scores else 0.0
        attack_rows.append((at, len(group), caught, f"{caught/len(group):.0%}", f"{avg_s:.3f}"))

    lines = [
        "# Phase 2-IF — Experiment Report",
        "",
        f"**Run time**: {_now_iso()}  ",
        f"**Config**: `configs/experiment_02_if.yaml`  ",
        f"**Defense method**: Isolation Forest (bge-m3 embeddings)  ",
        f"**IF params**: n_estimators={if_cfg.get('n_estimators', 100)}, "
        f"block_percentile={if_cfg.get('block_threshold_percentile', 10)}  ",
        "",
        "---",
        "",
        "## Attack Scenario",
        "",
        f"| Item | Value |",
        f"|------|-------|",
        f"| Original chunks in DB (Phase 1) | {config.n_clean_chunks} |",
        f"| Poison chunks tested (Phase 2) | {total_poison} |",
        f"| CDR test chunks | {len(cdr_records)} |",
        f"| Embedding model | {config.embedding_model} |",
        f"| Chunk size | {chunk_tokens} tokens / {chunk_overlap} overlap |",
        "",
        "---",
        "",
        "## Defense Point A (IF) — Results",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Chunks inserted into pgvector | {inserted} |",
        f"| Chunks blocked (not inserted) | {blocked} |",
        f"| **DBR-A** (poison caught / total poison) | **{dbr:.2%}** |",
        f"| **CDR-A** (clean wrongly blocked / CDR n) | **{cdr:.2%}** |",
        "",
        "### Per-Attack-Type Breakdown",
        "",
        "| Attack Type | Total | Caught | DBR | Avg Trust Score |",
        "|-------------|-------|--------|-----|-----------------|",
    ]
    for at, total, caught, dbr_pct, avg_s in attack_rows:
        lines.append(f"| {at} | {total} | {caught} | {dbr_pct} | {avg_s} |")

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        "- trust_score: 0=normal, 1=anomalous (Isolation Forest, inverted + normalized)",
        f"- block_threshold_percentile={if_cfg.get('block_threshold_percentile', 10)}: "
        "chunks in bottom 10% of clean IF score distribution are blocked",
        "- DBR-A measures Defense A effectiveness; DBR-B measured separately in Phase 3-CR",
        "- Audit log: `output/phase2_if/audit_defense_a_if.jsonl`",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
