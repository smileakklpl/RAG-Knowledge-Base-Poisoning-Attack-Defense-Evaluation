"""
defense/counter_retrieval.py — Counter-Retrieval Verification (Defense Point B)

Method: For each gray-zone chunk retrieved at query time, extract its core claim,
        search the original corpus for supporting/contradicting evidence, then
        apply NLI to determine if the chunk should be trusted or flagged.

Design borrowed from FVA-RAG (Ravishankara, arXiv 2512.07015, 2025), adapted
from benign sycophancy detection to adversarial poison detection.

Critical constraint: evidence pool restricted to is_original=TRUE chunks only.
  Reason: poison chunks may mutually validate each other if the pool is unrestricted,
  creating circular "poison validates poison" logic.

Verdicts:
  "trusted"    — supporting evidence found, no contradiction → keep chunk
  "suspicious" — contradicting evidence found → DELETE from DB
  "isolated"   — no supporting evidence AND no contradiction (rare/niche clause) → keep

References:
  - FVA-RAG (Ravishankara, arXiv 2512.07015, 2025)
  - TrustRAG (Zhou et al., arXiv 2501.00879, 2025)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from src.config import ExperimentConfig

Verdict = Literal["trusted", "suspicious", "isolated"]


class CounterRetrievalVerifier:
    """
    Retrieval-time verifier for gray-zone chunks that passed Defense A.

    Workflow per chunk:
      1. extract_claim()  — LLM extracts one factual sentence from the chunk
      2. _embed()         — embed the claim using bge-m3
      3. _counter_retrieve() — cosine search in is_original=TRUE chunks only
      4. _run_nli()       — NLI on each evidence candidate
      5. _decide()        — aggregate NLI results → verdict

    Usage:
        verifier = CounterRetrievalVerifier.from_config(config)
        verdict, conf = verifier.verify(chunk_text, chunk_id, conn)
    """

    # Class-level NLI model cache (loaded once, shared across instances)
    _nli_model = None

    def __init__(
        self,
        embedding_model:      str   = "bge-m3",
        claim_extraction_llm: str   = "llama3.1:8b",
        nli_model_name:       str   = "cross-encoder/nli-deberta-v3-small",
        top_k_evidence:       int   = 5,
        entail_threshold:     float = 0.70,
        contradict_threshold: float = 0.70,
        max_claim_tokens:     int   = 80,
    ):
        self.embedding_model      = embedding_model
        self.claim_extraction_llm = claim_extraction_llm
        self.nli_model_name       = nli_model_name
        self.top_k_evidence       = top_k_evidence
        self.entail_threshold     = entail_threshold
        self.contradict_threshold = contradict_threshold
        self.max_claim_tokens     = max_claim_tokens

    # ── Public interface ──────────────────────────────────────────────────────

    def verify(
        self,
        chunk_text: str,
        chunk_id:   str,
        conn,
    ) -> tuple[Verdict, float]:
        """
        Run full counter-retrieval verification for one chunk.

        Args:
            chunk_text: the chunk's document text.
            chunk_id:   used to exclude the chunk itself from evidence search.
            conn:       live psycopg2 connection to pgvector DB.

        Returns:
            verdict    (str):   "trusted" | "suspicious" | "isolated"
            confidence (float): max NLI score that drove the verdict.
        """
        claim = self.extract_claim(chunk_text)
        if not claim.strip():
            return "isolated", 0.0

        try:
            claim_embedding = self._embed(claim)
        except Exception as exc:
            print(f"[CounterRetrieval] embed failed for claim '{claim[:60]}': {exc}")
            return "isolated", 0.0

        if claim_embedding is None:
            return "isolated", 0.0

        evidence_chunks = self._counter_retrieve(conn, claim_embedding, exclude_id=chunk_id)

        if not evidence_chunks:
            return "isolated", 0.0

        return self._decide(claim, evidence_chunks)

    # ── Claim extraction ──────────────────────────────────────────────────────

    def extract_claim(self, chunk_text: str) -> str:
        """
        Ask llama3.1:8b to distill the chunk's core factual claim into one sentence.
        Returns empty string on failure (treated as isolated).
        """
        import ollama

        prompt = (
            "Extract the single most important factual claim from the following contract text. "
            "Respond with exactly one short declarative sentence. "
            "Do not include opinions, summaries, or meta-commentary.\n\n"
            f"Text:\n{chunk_text[:1200]}\n\n"
            "Claim:"
        )
        try:
            resp = ollama.generate(
                model  = self.claim_extraction_llm,
                prompt = prompt,
                options={"num_predict": self.max_claim_tokens, "temperature": 0.0},
            )
            claim = resp["response"].strip().split("\n")[0]
            return claim[:500]   # hard cap to avoid runaway output
        except Exception as exc:
            print(f"[CounterRetrieval] claim extraction failed: {exc}")
            return ""

    # ── Counter-retrieval ─────────────────────────────────────────────────────

    def _counter_retrieve(
        self,
        conn,
        claim_embedding: list[float],
        exclude_id: str,
    ) -> list[dict]:
        """
        Search pgvector for chunks most semantically similar to the claim.

        CRITICAL: WHERE is_original = TRUE restricts the pool to clean original
        chunks only. This prevents poison chunks from mutually validating each other.
        """
        vec = np.array(claim_embedding, dtype=np.float32)
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH dist AS (
                    SELECT chunk_id, document,
                           embedding <=> %s AS distance
                    FROM   chunks
                    WHERE  is_original = TRUE
                      AND  chunk_id   != %s
                    ORDER  BY distance
                    LIMIT  %s
                )
                SELECT chunk_id, document, 1 - distance AS similarity
                FROM   dist;
                """,
                (vec, exclude_id, self.top_k_evidence),
            )
            rows = cur.fetchall()

        return [
            {"chunk_id": r[0], "document": r[1], "similarity": float(r[2])}
            for r in rows
        ]

    # ── NLI ───────────────────────────────────────────────────────────────────

    @classmethod
    def _ensure_nli(cls, model_name: str) -> None:
        """Lazy-load NLI cross-encoder once; cached at class level."""
        if cls._nli_model is not None:
            return
        from sentence_transformers import CrossEncoder
        print(f"[CounterRetrieval] Loading NLI model: {model_name}...")
        cls._nli_model = CrossEncoder(model_name, num_labels=3)
        print("[CounterRetrieval] NLI model ready.")

    def _run_nli(self, claim: str, evidence_text: str) -> dict[str, float]:
        """
        Run NLI on (claim, evidence) pair.
        Returns dict with keys: entailment, neutral, contradiction (sum to ~1).
        Label order for deberta-v3-small: [contradiction, neutral, entailment].
        """
        self._ensure_nli(self.nli_model_name)
        scores = self._nli_model.predict([(evidence_text[:512], claim[:512])])
        probs  = _softmax(scores[0])
        return {
            "contradiction": float(probs[0]),
            "neutral":       float(probs[1]),
            "entailment":    float(probs[2]),
        }

    # ── Verdict aggregation ───────────────────────────────────────────────────

    def _decide(self, claim: str, evidence_chunks: list[dict]) -> tuple[Verdict, float]:
        """
        Aggregate NLI results across all evidence chunks.

        Logic:
          - Any evidence with entailment >= threshold  → supporting evidence found
          - Any evidence with contradiction >= threshold → contradicting evidence found

        Verdict rules:
          supporting AND NOT contradicting → "trusted"
          contradicting (regardless of support)  → "suspicious"
          neither                                → "isolated"
        """
        has_support      = False
        has_contradiction = False
        max_conf         = 0.0

        for ev in evidence_chunks:
            nli = self._run_nli(claim, ev["document"])

            if nli["entailment"]    >= self.entail_threshold:
                has_support       = True
                max_conf          = max(max_conf, nli["entailment"])
            if nli["contradiction"] >= self.contradict_threshold:
                has_contradiction = True
                max_conf          = max(max_conf, nli["contradiction"])

        if has_contradiction:
            return "suspicious", round(max_conf, 4)
        if has_support:
            return "trusted",    round(max_conf, 4)
        return "isolated", 0.0

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float] | None:
        import ollama
        import math
        text = text.strip()
        if not text:
            return None
        resp = ollama.embed(model=self.embedding_model, input=text)
        emb = resp.embeddings[0]
        if any(math.isnan(v) or math.isinf(v) for v in emb):
            print(f"[CounterRetrieval] NaN/Inf in embedding, treating as isolated.")
            return None
        return emb

    # ── Config factory ────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: "ExperimentConfig") -> "CounterRetrievalVerifier":
        defense = getattr(config, "defense", {}) or {}
        cr_cfg  = defense.get("counter_retrieval", {})
        return cls(
            embedding_model      = getattr(config, "embedding_model", "bge-m3"),
            claim_extraction_llm = cr_cfg.get("claim_extraction_model", "llama3.1:8b"),
            nli_model_name       = cr_cfg.get("nli_model", "cross-encoder/nli-deberta-v3-small"),
            top_k_evidence       = cr_cfg.get("top_k_evidence",       5),
            entail_threshold     = cr_cfg.get("entail_threshold",     0.70),
            contradict_threshold = cr_cfg.get("contradict_threshold", 0.70),
            max_claim_tokens     = cr_cfg.get("max_claim_tokens",     80),
        )


# ── Module helpers ────────────────────────────────────────────────────────────

def _softmax(x) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()
