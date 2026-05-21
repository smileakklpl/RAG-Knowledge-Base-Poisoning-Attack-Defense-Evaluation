"""
Phase 3 (CR) — Retrieval + Counter-Retrieval Defense (Defense Point B)

Replaces phase3.py (PPL post-retrieval) with counter-retrieval verification.

Flow (per query):
  1. Embed query → pgvector cosine top-k (returns trust_score per chunk)
  2. For each retrieved chunk, apply gray-zone trigger logic:
       trust_score is NULL (is_original=TRUE)  → skip CR, keep
       trust_score < gray_zone_lower (0.10)    → very normal → skip CR, keep
       trust_score >= skip_cr_above  (0.80)    → auto-suspicious → DELETE
       else (gray zone)                        → CounterRetrievalVerifier.verify()
           verdict "suspicious"  → DELETE from DB
           verdict "trusted"     → keep
           verdict "isolated"    → keep (niche clause, no contradicting evidence)
  3. Build sanitized_context from surviving chunks
  4. Write output/phase3_cr/retrieval_results_cr.json + audit_defense_b_cr.jsonl + report.md

Defense B independently catches chunks that slipped past Defense A (gray zone).
RSR is measured pre-defense; DBR-B / CDR-B measure Defense B's own contribution.
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


class Phase3RetrieverCR:
    """
    Retrieves top-k chunks, applies counter-retrieval defense to gray-zone chunks,
    physically DELETEs suspicious chunks, and outputs sanitized context for Phase 4.
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

        defense   = getattr(self.config, "defense", {}) or {}
        ts_cfg    = defense.get("trust_score", {})
        gray_lower   = ts_cfg.get("gray_zone_lower",  0.10)
        skip_cr_above = ts_cfg.get("skip_cr_above",   0.80)
        cr_enabled   = defense.get("counter_retrieval", {}).get("enabled", True)

        verifier = None
        if cr_enabled:
            from src.defense.counter_retrieval import CounterRetrievalVerifier
            verifier = CounterRetrievalVerifier.from_config(self.config)

        conn  = self._connect()
        max_k = max(self.config.top_k)

        all_results: list[dict] = []
        all_audit:   list[dict] = []

        for query in tqdm(queries, desc="  Retrieve + Defense-B-CR", unit="query"):
            query_vec  = self._embed(query["text"])
            raw_chunks = self._retrieve(conn, query_vec, max_k)

            blocked_ids: set[str] = set()

            for chunk in raw_chunks:
                ts      = chunk.get("trust_score")   # None for original chunks
                verdict = "n/a"
                cr_conf = None

                # Gray-zone trigger logic
                if ts is None:
                    # Original clean chunk — always trusted, skip CR
                    action = "skip_original"
                elif ts >= skip_cr_above:
                    # High anomaly score slipped past Phase 2 — auto-flag
                    action  = "auto_suspicious"
                    verdict = "suspicious"
                    blocked_ids.add(chunk["chunk_id"])
                elif ts < gray_lower:
                    # Very normal by IF — skip CR
                    action = "skip_normal"
                elif verifier is not None:
                    # Gray zone — run counter-retrieval
                    action = "counter_retrieval"
                    verdict, cr_conf = verifier.verify(
                        chunk["document"], chunk["chunk_id"], conn
                    )
                    if verdict == "suspicious":
                        blocked_ids.add(chunk["chunk_id"])
                else:
                    action = "cr_disabled"

                all_audit.append({
                    "query_id":               query["id"],
                    "chunk_id":               chunk["chunk_id"],
                    "rank":                   chunk["rank"],
                    "similarity":             chunk["similarity"],
                    "trust_score":            ts,
                    "cr_action":              action,
                    "cr_verdict":             verdict,
                    "cr_confidence":          cr_conf,
                    "predicted_is_malicious": chunk["chunk_id"] in blocked_ids,
                    "ground_truth_is_poison": chunk["is_poison"],
                    "source":                 chunk["source"],
                    "attack_type":            chunk.get("attack_type"),
                    "processed_at":           _now_iso(),
                })

            # Physical DELETE suspicious chunks
            if blocked_ids:
                self._delete_chunks(conn, list(blocked_ids))

            # Build per-k result records
            for k in self.config.top_k:
                raw_k       = [c for c in raw_chunks if c["rank"] <= k]
                sanitized_k = [c for c in raw_k if c["chunk_id"] not in blocked_ids]
                poison_in_raw = [c for c in raw_k if c["is_poison"]]

                all_results.append({
                    "query_id":    query["id"],
                    "query_text":  query["text"],
                    "top_k":       k,
                    "raw_results": [
                        {
                            "chunk_id":      c["chunk_id"],
                            "is_poison":     c["is_poison"],
                            "attack_type":   c.get("attack_type"),
                            "rank":          c["rank"],
                            "similarity":    round(c["similarity"], 4),
                            "trust_score":   c.get("trust_score"),
                            "is_blocked":    c["chunk_id"] in blocked_ids,
                            "text_preview":  c["document"][:150],
                        }
                        for c in raw_k
                    ],
                    "poison_in_topk":      bool(poison_in_raw),
                    "poison_rank":         poison_in_raw[0]["rank"] if poison_in_raw else None,
                    "sanitized_context":   getattr(
                        self.config, "context_separator", "\n\n---\n\n"
                    ).join(c["document"] for c in sanitized_k),
                    "sanitized_chunk_ids": [c["chunk_id"] for c in sanitized_k],
                })

        conn.close()

        out = Path(output_results_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[Phase3-CR] Retrieval results → {output_results_path}  ({len(all_results)} entries)")

        _write_jsonl(Path(output_audit_path), all_audit)
        print(f"[Phase3-CR] Audit log         → {output_audit_path}  ({len(all_audit)} records)")

        self._print_metrics(all_results, all_audit)

        report_path = out.parent / "report.md"
        _write_report(report_path, all_results, all_audit, self.config)
        print(f"[Phase3-CR] Report            → {report_path}")

    # ── pgvector retrieval ────────────────────────────────────────────────────

    def _retrieve(self, conn, query_vec: list[float], k: int) -> list[dict]:
        """Retrieve top-k chunks including trust_score column."""
        vec = np.array(query_vec, dtype=np.float32)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH dist AS (
                    SELECT chunk_id, document, doc_id, source,
                           is_poison, attack_type, trust_score,
                           embedding <=> %s AS distance
                    FROM   chunks
                    ORDER  BY distance
                    LIMIT  %s
                )
                SELECT chunk_id, document, doc_id, source,
                       is_poison, attack_type, trust_score,
                       1 - distance AS similarity
                FROM   dist;
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
                "trust_score": row[6],   # float | None
                "similarity":  float(row[7]),
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
            host    = db.get("host",     "localhost"),
            port    = db.get("port",     5432),
            dbname  = db.get("database", "rag_poison_if"),
            user    = db.get("user",     "postgres"),
            password= os.environ.get("PGPASSWORD", "postgres"),
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
            print(f"[Phase3-CR]   RSR (k={k:2d}): {rsr:.2%}  ({hits}/{len(k_res)} queries hit)")

        seen: dict[str, dict] = {}
        for r in audit:
            seen[r["chunk_id"]] = r
        poison = [r for r in seen.values() if r["ground_truth_is_poison"]]
        clean  = [r for r in seen.values() if not r["ground_truth_is_poison"]]
        dbr_b  = sum(1 for r in poison if r["predicted_is_malicious"]) / max(len(poison), 1)
        cdr_b  = sum(1 for r in clean  if r["predicted_is_malicious"]) / max(len(clean),  1)
        print(f"[Phase3-CR]   DBR-B={dbr_b:.2%}  CDR-B={cdr_b:.2%}")

        # CR action breakdown
        cr_actions = {}
        for r in audit:
            a = r.get("cr_action", "n/a")
            cr_actions[a] = cr_actions.get(a, 0) + 1
        print(f"[Phase3-CR]   CR actions: {cr_actions}")


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
    k_values = sorted({r["top_k"] for r in results})
    rsr_rows = []
    for k in k_values:
        k_res = [r for r in results if r["top_k"] == k]
        hits  = sum(1 for r in k_res if r["poison_in_topk"])
        rsr   = hits / max(len(k_res), 1)
        rsr_rows.append((k, len(k_res), hits, f"{rsr:.2%}"))

    seen: dict[str, dict] = {}
    for r in audit:
        seen[r["chunk_id"]] = r
    poison = [r for r in seen.values() if r["ground_truth_is_poison"]]
    clean  = [r for r in seen.values() if not r["ground_truth_is_poison"]]
    dbr_b  = sum(1 for r in poison if r["predicted_is_malicious"]) / max(len(poison), 1)
    cdr_b  = sum(1 for r in clean  if r["predicted_is_malicious"]) / max(len(clean),  1)

    cr_actions: dict[str, int] = {}
    for r in audit:
        a = r.get("cr_action", "n/a")
        cr_actions[a] = cr_actions.get(a, 0) + 1

    defense    = getattr(config, "defense", {}) or {}
    ts_cfg     = defense.get("trust_score", {})
    cr_cfg     = defense.get("counter_retrieval", {})

    lines = [
        "# Phase 3-CR — Experiment Report",
        "",
        f"**Run time**: {_now_iso()}  ",
        f"**Config**: `configs/experiment_02_if.yaml`  ",
        f"**Defense method**: Counter-Retrieval Verification (NLI: deberta-v3-small)  ",
        f"**Gray zone**: trust_score ∈ [{ts_cfg.get('gray_zone_lower', 0.10)}, "
        f"{ts_cfg.get('skip_cr_above', 0.80)})  ",
        f"**NLI model**: {cr_cfg.get('nli_model', 'cross-encoder/nli-deberta-v3-small')}  ",
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
        "## Defense Point B (CR) — Results",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Unique chunks evaluated | {len(seen)} |",
        f"| Poison chunks in top-k | {len(poison)} |",
        f"| **DBR-B** (poison caught / total poison in top-k) | **{dbr_b:.2%}** |",
        f"| **CDR-B** (clean wrongly blocked / total clean in top-k) | **{cdr_b:.2%}** |",
        "",
        "### CR Action Breakdown",
        "",
        "| Action | Count |",
        "|--------|-------|",
    ]
    for action, count in sorted(cr_actions.items()):
        lines.append(f"| {action} | {count} |")

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        "- `skip_original`: NULL trust_score → Phase 1 clean chunk, never evaluated",
        "- `skip_normal`:   trust_score < gray_zone_lower → IF deemed very normal",
        "- `auto_suspicious`: trust_score >= skip_cr_above → flagged without CR",
        "- `counter_retrieval`: gray zone → claim extracted, NLI run on original chunks",
        "- Evidence pool restricted to is_original=TRUE (prevents poison mutual validation)",
        "- Physical DELETE applied per-query; earlier deletions affect later queries",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
