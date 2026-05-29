"""
Phase 3 — Retrieval + Post-Retrieval Defense (Defense Point B)

流程（對 data/queries.json 每筆查詢）：
  1. bge-m3 embed query → pgvector cosine 檢索 top-max(k) chunks
  2. 記錄 raw top-k（計算 RSR）
  3. Defense Filter B（語料庫一致性投票，比對 is_original=True chunks）
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
    Retrieves top-k chunks from pgvector, applies Defense B (corpus consistency voting),
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

        conn  = self._connect()
        max_k = max(self.config.top_k)

        defense_b = _make_defense_filter_b(self.config, conn)

        all_results: list[dict] = []
        all_audit:   list[dict] = []

        for query in tqdm(queries, desc="  Retrieve + Defense-B", unit="query"):
            tqdm.write(f"\n  [Query] {query['id']}: {query['text'][:80].strip()!r}")
            query_vec  = self._embed(query["text"])
            raw_chunks = self._retrieve(conn, query_vec, max_k)
            tqdm.write(f"    retrieved {len(raw_chunks)} chunks (top-{max_k})")

            # Defense B: score every retrieved chunk, collect deletes
            blocked_ids:   set[str]              = set()
            chunk_scores:  dict[str, tuple]      = {}

            for chunk in raw_chunks:
                tqdm.write(
                    f"    [chunk] rank={chunk['rank']}  {chunk['chunk_id']}"
                    f"  poison={chunk['is_poison']}  sim={chunk['similarity']:.3f}"
                )
                is_malicious, score = defense_b.predict(chunk["document"], query_text=query["text"])
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
                            "document":      c["document"],
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
        _write_report(report_path, all_results, all_audit, self.config,
                      defense_method=_defense_method_label(self.config))
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


def _make_defense_filter_b(config, conn):
    """Return the Defense B filter instance based on config.defense.method."""
    method = (getattr(config, "defense", {}) or {}).get("method", "voting")
    if method == "ppl":
        from src.defense.filter_PPL import PPLDefenseFilter
        return PPLDefenseFilter.for_phase_b(config)
    from src.defense.filter import ConsistencyDefenseFilter
    return ConsistencyDefenseFilter.for_phase_b(config, conn)


def _defense_method_label(config) -> str:
    defense = getattr(config, "defense", {}) or {}
    pre  = (defense.get("pre_injection",  {}) or {}).get("enabled", True)
    post = (defense.get("post_retrieval", {}) or {}).get("enabled", True)
    if not pre and not post:
        return "No Defense (Disabled)"
    method = defense.get("method", "voting")
    return (
        "PPL Perplexity Filtering (GPT-2 anomaly detection)"
        if method == "ppl" else
        "Corpus Consistency Voting (LLM-based contradiction detection)"
    )


def _write_report(
    path:    Path,
    results: list[dict],
    audit:   list[dict],
    config,
    defense_method: str = "Corpus Consistency Voting (LLM-based contradiction detection)",
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

    # Per-attack-type RSR: queries that retrieved ≥1 chunk of each type (max k)
    max_k      = max(k_values)
    max_k_res  = [r for r in results if r["top_k"] == max_k]
    n_queries   = len(max_k_res)
    at_rsr: dict[str, int] = {}
    for r in max_k_res:
        seen_types: set[str] = set()
        for raw in r["raw_results"]:
            if raw["is_poison"] and raw["attack_type"] and raw["attack_type"] not in seen_types:
                at = raw["attack_type"]
                at_rsr[at] = at_rsr.get(at, 0) + 1
                seen_types.add(at)

    # Per-attack-type DBR-B (from deduped audit)
    at_dbr: dict[str, list[dict]] = {}
    for r in poison:
        at = r.get("attack_type") or "unknown"
        at_dbr.setdefault(at, []).append(r)

    attack_types = sorted(set(list(at_dbr.keys()) + list(at_rsr.keys())))
    at_rows = []
    for at in attack_types:
        in_topk = len(at_dbr.get(at, []))
        caught  = sum(1 for r in at_dbr.get(at, []) if r["predicted_is_malicious"])
        avg_s   = sum(r["defense_score"] for r in at_dbr.get(at, [])) / max(in_topk, 1)
        q_hit   = at_rsr.get(at, 0)
        at_rows.append((
            at,
            f"{q_hit}/{n_queries} ({q_hit / max(n_queries, 1):.0%})",
            in_topk,
            caught,
            f"{caught / max(in_topk, 1):.0%}",
            f"{avg_s:.3f}",
        ))

    lines = [
        "# Phase 3 — Experiment Report",
        "",
        f"**Run time**: {_now_iso()}  ",
        f"**Config**: `{config.config_path}`  ",
        f"**Defense method**: {defense_method}  ",
        *(
            [f"**Defense B LLM**: `{config.defense.get('llm_model', 'gemma4:e4b')}`  "
             f"top_k_ref={config.defense.get('top_k_ref', 5)}  "]
            if config.defense.get("method", "voting") != "ppl" else
            [f"**PPL model**: GPT-2 small  "
             f"global_thresh={config.defense.get('post_retrieval', {}).get('global_ppl_threshold', 100.0)}  "
             f"spike_thresh={config.defense.get('post_retrieval', {}).get('spike_ppl_threshold', 150.0)}  "]
        ),
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
        "### Per-Attack-Type Breakdown",
        "",
        "| Attack Type | Queries Hit (RSR) | In Top-K | Caught | DBR-B | Avg Score |",
        "|-------------|-------------------|----------|--------|-------|-----------|",
    ]
    for at, rsr_str, in_topk, caught, dbr_pct, avg_s in at_rows:
        lines.append(f"| {at} | {rsr_str} | {in_topk} | {caught} | {dbr_pct} | {avg_s} |")

    lines += [
        "",
        "---",
        "",
        "## Notes",
        "",
        "- RSR measures attack strength (before defense); DBR-B measures defense effectiveness at B",
        "- Stealth attacks alter key facts while maintaining semantic similarity; consistency voting targets this",
        "- Physical DELETE applied incrementally: earlier queries' deletions affect later queries",
        f"- Retrieval results with sanitized context: `{path.parent / 'retrieval_results.json'}`",
        f"- Per-chunk audit log: `{path.parent / 'audit_defense_b.jsonl'}`",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
