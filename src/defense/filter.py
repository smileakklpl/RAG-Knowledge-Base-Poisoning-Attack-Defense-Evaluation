"""
defense/filter.py — Corpus Consistency Defense (Defense Point A & B)

Method: LLM-based factual contradiction detection against the clean corpus.

For each chunk to evaluate:
  1. Embed the chunk and retrieve top-k semantically similar CLEAN chunks (is_original=True) from DB
  2. Ask the LLM (attacker model) whether the chunk contradicts any factual claims in those references
  3. Contradiction detected → is_malicious=True, score=1.0

This catches Stealth attacks that fool PPL-based filters by maintaining natural language
while silently altering key facts (numbers, dates, jurisdictions, amounts).

References:
  - RobustRAG (Xiang et al., arXiv 2405.15556): corpus-based isolation and aggregation
"""

import numpy as np
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import ExperimentConfig


class ConsistencyDefenseFilter:
    """
    Corpus-consistency binary classifier for detecting poisoned text chunks.

    Compares the candidate chunk against the top-k most semantically similar
    CLEAN chunks already in pgvector (is_original=True) and uses an LLM to
    detect factual contradictions.

    Usage:
        conn = psycopg2.connect(...)
        filter_a = ConsistencyDefenseFilter.from_config(config, conn)
        is_malicious, score = filter_a.predict(chunk_text)
    """

    def __init__(
        self,
        conn,
        embedding_model: str,
        llm_model:       str,
        top_k_ref:       int = 5,
    ):
        self.conn            = conn
        self.embedding_model = embedding_model
        self.llm_model       = llm_model
        self.top_k_ref       = top_k_ref

    # ── Public interface ──────────────────────────────────────────────────────

    def predict(self, chunk_text: str) -> tuple[bool, float]:
        """
        Evaluate a chunk for malicious content via corpus consistency voting.

        Returns:
            is_malicious (bool): True if the LLM detects factual contradiction.
            score (float): 1.0 if contradiction detected, 0.0 otherwise.
                           0.5 if no reference chunks found (insufficient data).
        """
        embedding = self._embed(chunk_text)
        ref_chunks = self._retrieve_similar_clean(embedding)

        if not ref_chunks:
            return False, 0.5  # no reference available, cannot judge

        contradiction = self._check_contradiction(chunk_text, ref_chunks)
        score = 1.0 if contradiction else 0.0
        return contradiction, score

    # ── LLM contradiction check ───────────────────────────────────────────────

    def _check_contradiction(self, chunk_text: str, ref_chunks: list[dict]) -> bool:
        import ollama
        refs = "\n\n".join(
            f"[Reference {i+1}]:\n{c['document']}"
            for i, c in enumerate(ref_chunks)
        )
        prompt = (
            "You are a contract fact-checking assistant.\n\n"
            f"Reference clauses from a verified clean contract database:\n{refs}\n\n"
            f"New clause to evaluate:\n{chunk_text}\n\n"
            "Does the new clause contradict any specific factual claims in the reference clauses? "
            "Look for contradictions in: numbers, dates, monetary amounts, jurisdictions, "
            "deadlines, party names, or legal terms.\n"
            "Answer with only YES or NO."
        )
        resp = ollama.chat(
            model=self.llm_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return "YES" in resp.message.content.strip().upper()

    # ── DB retrieval ──────────────────────────────────────────────────────────

    def _retrieve_similar_clean(self, embedding: list[float]) -> list[dict]:
        """Find top-k most similar CLEAN chunks (is_original=True) from pgvector."""
        vec = np.array(embedding)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT chunk_id, document, 1 - (embedding <=> %s) AS similarity
                FROM chunks
                WHERE is_original = TRUE
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (vec, vec, self.top_k_ref),
            )
            rows = cur.fetchall()
        return [
            {"chunk_id": r[0], "document": r[1], "similarity": float(r[2])}
            for r in rows
        ]

    # ── Embedding ─────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        import ollama
        resp = ollama.embed(model=self.embedding_model, input=text)
        return resp.embeddings[0]

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: "ExperimentConfig", conn) -> "ConsistencyDefenseFilter":
        """
        Instantiate from YAML config.
        Both Defense A (pre_injection) and Defense B (post_retrieval) use the same logic.
        """
        defense = getattr(config, "defense", {}) or {}
        return cls(
            conn=conn,
            embedding_model=config.embedding_model,
            llm_model=defense.get("llm_model", getattr(config, "attacker_model", "gemma4:e4b")),
            top_k_ref=int(defense.get("top_k_ref", 5)),
        )
