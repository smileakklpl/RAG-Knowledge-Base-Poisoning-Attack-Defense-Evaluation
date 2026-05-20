"""
Phase 3 — Retrieval + Post-Retrieval Defense (Defense Point B)

流程（對 data/queries.json 每筆查詢）：
  1. bge-m3 embed query → pgvector cosine 檢索 top-max(k) chunks
  2. 記錄 raw top-k（計算 RSR）
  3. Defense Filter B（PPL，post_retrieval 閾值）
     - 惡意 → 物理 DELETE from pgvector + 從 context 移除
     - 乾淨 → 保留進入 sanitized context
  4. 寫出 retrieval_results.json（每 query × k 一筆）供 Phase 4 使用
     + audit_defense_b.jsonl（每 chunk × query 一筆）

RSR 量測「防禦前」命中率，DBR-B / CDR-B 量測「防禦點 B 本身」的表現。
Defense B 的 DELETE 按查詢順序累積（前一筆查詢刪除的 chunk 後續不再出現）。
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from tqdm import tqdm

if TYPE_CHECKING:
    from src.config import ExperimentConfig


class Phase3Retriever:
    """
    Retrieves top-k chunks from pgvector, applies Defense B (PPL filtering),
    physically DELETEs malicious chunks, and outputs sanitized context for Phase 4.
    Runs all k values in config.top_k in a single pass.
    """

    def __init__(self, config: "ExperimentConfig"):
        self.config = config

    # ── Public entry point ────────────────────────────────────────────────────

    def run(
        self,
        queries_path:        str,
        output_results_path: str,
        output_audit_path:   str,
    ) -> None:
        queries = json.loads(Path(queries_path).read_text(encoding="utf-8"))

        from src.defense.filter import PPLDefenseFilter
        defense_b = PPLDefenseFilter.from_config(self.config, "post_retrieval")

        conn  = self._connect()
        max_k = max(self.config.top_k)

        all_results: list[dict] = []
        all_audit:   list[dict] = []

        for query in tqdm(queries, desc="  Retrieve + Defense-B", unit="query"):
            query_vec  = self._embed(query["text"])
            raw_chunks = self._retrieve(conn, query_vec, max_k)

            # Defense B: score every retrieved chunk, collect deletes
            blocked_ids:   set[str]              = set()
            chunk_scores:  dict[str, tuple]      = {}

            for chunk in raw_chunks:
                is_malicious, score = defense_b.predict(chunk["document"])
                chunk_scores[chunk["chunk_id"]] = (is_malicious, score)

                all_audit.append({
                    "query_id":               query["id"],
                    "chunk_id":               chunk["chunk_id"],
                    "rank":                   chunk["rank"],
                    "similarity":             chunk["similarity"],
                    "defense_score":          score,
                    "predicted_is_malicious": is_malicious,
                    "ground_truth_is_poison": chunk["is_poison"],
                    "source":                 chunk["source"],
                    "attack_type":            chunk.get("attack_type"),
                    "processed_at":           _now_iso(),
                })

                if is_malicious:
                    blocked_ids.add(chunk["chunk_id"])

            # Physical DELETE malicious chunks before next query
            if blocked_ids:
                self._delete_chunks(conn, list(blocked_ids))

            # Build per-k result records
            for k in self.config.top_k:
                raw_k       = [c for c in raw_chunks if c["rank"] <= k]
                sanitized_k = [c for c in raw_k if c["chunk_id"] not in blocked_ids]

                poison_in_raw = [c for c in raw_k if c["is_poison"]]
                all_results.append({
                    "query_id":   query["id"],
                    "query_text": query["text"],
                    "top_k":      k,
                    "raw_results": [
                        {
                            "chunk_id":      c["chunk_id"],
                            "is_poison":     c["is_poison"],
                            "attack_type":   c.get("attack_type"),
                            "rank":          c["rank"],
                            "similarity":    round(c["similarity"], 4),
                            "is_blocked":    c["chunk_id"] in blocked_ids,
                            "defense_score": chunk_scores[c["chunk_id"]][1],
                            "text_preview":  c["document"][:150],
                        }
                        for c in raw_k
                    ],
                    "poison_in_topk":      bool(poison_in_raw),
                    "poison_rank":         poison_in_raw[0]["rank"] if poison_in_raw else None,
                    "sanitized_context":   getattr(self.config, "context_separator", "\n\n---\n\n").join(c["document"] for c in sanitized_k),
                    "sanitized_chunk_ids": [c["chunk_id"] for c in sanitized_k],
                })

        conn.close()

        # Write outputs
        out = Path(output_results_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[Phase3] Retrieval results → {output_results_path}  ({len(all_results)} entries)")

        _write_jsonl(Path(output_audit_path), all_audit)
        print(f"[Phase3] Audit log         → {output_audit_path}  ({len(all_audit)} records)")

        self._print_metrics(all_results, all_audit)

        report_path = out.parent / "report.md"
        _write_report(report_path, all_results, all_audit, self.config)
        print(f"[Phase3] Report            → {report_path}")

    # ── pgvector retrieval ────────────────────────────────────────────────────

    def _retrieve(self, conn, query_vec: list[float], k: int) -> list[dict]:
        vec = np.array(query_vec)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH dist AS (
                    SELECT chunk_id, document, doc_id, source,
                           is_poison, attack_type,
                           embedding <=> %s AS distance
                    FROM chunks
                    ORDER BY distance
                    LIMIT %s
                )
                SELECT chunk_id, document, doc_id, source,
                       is_poison, attack_type,
                       1 - distance AS similarity
                FROM dist;
                """,
                (vec, k),
            )
            rows = cur.fetchall()

        return [
            {
                "chunk_id":    row[0],
                "document":    row[1],
                "doc_id":      row[2],
                "source":      row[3],
                "is_poison":   row[4],
                "attack_type": row[5],
                "similarity":  float(row[6]),
                "rank":        i + 1,
            }
            for i, row in enumerate(rows)
        ]

    def _delete_chunks(self, conn, chunk_ids: list[str]) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE chunk_id = ANY(%s);", (chunk_ids,))
        conn.commit()

    # ── Embedding + DB connection ─────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        import ollama
        resp = ollama.embed(model=self.config.embedding_model, input=text)
        return resp.embeddings[0]

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

    # ── Metrics ───────────────────────────────────────────────────────────────

    @staticmethod
    def _print_metrics(results: list[dict], audit: list[dict]) -> None:
        for k in sorted({r["top_k"] for r in results}):
            k_res = [r for r in results if r["top_k"] == k]
            hits  = sum(1 for r in k_res if r["poison_in_topk"])
            rsr   = hits / max(len(k_res), 1)
            print(f"[Phase3]   RSR (k={k:2d}): {rsr:.2%}  ({hits}/{len(k_res)} queries hit)")

        # Per-chunk dedup (same chunk may appear in multiple queries)
        seen: dict[str, dict] = {}
        for r in audit:
            seen[r["chunk_id"]] = r
        poison = [r for r in seen.values() if r["ground_truth_is_poison"]]
        clean  = [r for r in seen.values() if not r["ground_truth_is_poison"]]
        dbr_b  = sum(1 for r in poison if r["predicted_is_malicious"]) / max(len(poison), 1)
        cdr_b  = sum(1 for r in clean  if r["predicted_is_malicious"]) / max(len(clean),  1)
        print(f"[Phase3]   DBR-B={dbr_b:.2%}  CDR-B={cdr_b:.2%}")


# ── Module-level helpers ──────────────────────────────────────────────────────

def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_report(
    path:    Path,
    results: list[dict],
    audit:   list[dict],
    config,
) -> None:
    # RSR per k
    k_values = sorted({r["top_k"] for r in results})
    rsr_rows = []
    for k in k_values:
        k_res = [r for r in results if r["top_k"] == k]
        hits  = sum(1 for r in k_res if r["poison_in_topk"])
        rsr   = hits / max(len(k_res), 1)
        rsr_rows.append((k, len(k_res), hits, f"{rsr:.2%}"))

    # Defense B metrics (chunk-level dedup)
    seen: dict[str, dict] = {}
    for r in audit:
        seen[r["chunk_id"]] = r
    poison = [r for r in seen.values() if r["ground_truth_is_poison"]]
    clean  = [r for r in seen.values() if not r["ground_truth_is_poison"]]
    dbr_b  = sum(1 for r in poison if r["predicted_is_malicious"]) / max(len(poison), 1)
    cdr_b  = sum(1 for r in clean  if r["predicted_is_malicious"]) / max(len(clean),  1)

    # Per-attack-type RSR (use max k for overview)
    max_k     = max(k_values)
    max_k_res = [r for r in results if r["top_k"] == max_k]
    at_rsr: dict[str, tuple[int, int]] = {}
    for r in max_k_res:
        for raw in r["raw_results"]:
            if raw["is_poison"] and raw["attack_type"]:
                at = raw["attack_type"]
                total, hit = at_rsr.get(at, (0, 0))
                at_rsr[at] = (total + 1, hit + (1 if raw["rank"] <= max_k else 0))

    lines = [
        "# Phase 3 — Experiment Report",
        "",
        f"**Run time**: {_now_iso()}  ",
        f"**Config**: `configs/experiment_01.yaml`  ",
        f"**Defense method**: PPL Filtering (GPT-2 small)  ",
        f"**Thresholds (Defense B)**: global_ppl=100, spike_ppl=150  ",
        f"**Top-K values tested**: {k_values}  ",
        "",
        "---",
        "",
        "## RSR — Retrieval Success Rate (pre-defense)",
        "",
        "| Top-K | Queries | Poison Hit | RSR |",
        "|-------|---------|------------|-----|",
    ]
    for k, n_q, hits, rsr_pct in rsr_rows:
        lines.append(f"| {k} | {n_q} | {hits} | {rsr_pct} |")

    lines += [
        "",
        "---",
        "",
        "## Defense Point B — Results",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Unique chunks evaluated | {len(seen)} |",
        f"| Poison chunks in top-k | {len(poison)} |",
        f"| **DBR-B** (poison caught / total poison in top-k) | **{dbr_b:.2%}** |",
        f"| **CDR-B** (clean wrongly blocked / total clean in top-k) | **{cdr_b:.2%}** |",
        "",
        "---",
        "",
        "## Notes",
        "",
        "- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B",
        "- Stealth attacks are expected to have low DBR-B (low PPL by design)",
        "- Physical DELETE applied incrementally: earlier queries' deletions affect later queries",
        "- Retrieval results with sanitized context: `output/retrieval_results.json`",
        "- Per-chunk audit log: `output/audit_defense_b.jsonl`",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
