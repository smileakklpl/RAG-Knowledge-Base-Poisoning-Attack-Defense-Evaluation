"""
defense/isolation_forest_filter.py — Isolation Forest Defense (Defense Point A)

Method: Embedding-space anomaly detection using sklearn IsolationForest.

Key insight (TrustRAG, Zhou et al. arXiv 2501.00879):
  Attackers optimize poison embeddings to be near target query vectors.
  This "pushed" position is anomalous relative to the natural corpus distribution.
  PPL cannot detect this; embedding anomaly scores can.

Workflow:
  1. fit(clean_embeddings)  — train on Phase 1 clean chunks (is_original=TRUE)
  2. predict(embedding)     — score a single new chunk, return (is_malicious, trust_score)

trust_score ∈ [0, 1]:
  0 = very normal (low percentile in anomaly distribution)
  1 = very anomalous (poison candidate)

References:
  - TrustRAG (Zhou et al., arXiv 2501.00879, 2025)
  - Isolation Forest (Liu et al., IEEE ICDM, 2008)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.config import ExperimentConfig


class IsolationForestFilter:
    """
    Isolation Forest anomaly detector for RAG chunk embeddings.

    fit() trains on clean corpus embeddings.
    predict() scores a new embedding and returns (is_malicious, trust_score).

    Usage:
        f = IsolationForestFilter.from_config(config)
        f.fit(clean_embeddings)          # list[list[float]] from Phase 1 DB
        is_mal, score = f.predict(emb)   # single embedding list[float]
    """

    def __init__(
        self,
        n_estimators:               int   = 100,
        contamination:              str   = "auto",
        random_state:               int   = 42,
        block_threshold_percentile: float = 10.0,
    ):
        self.n_estimators               = n_estimators
        self.contamination              = contamination
        self.random_state               = random_state
        self.block_threshold_percentile = block_threshold_percentile

        self._model           = None
        self._threshold_score: float | None = None   # raw IF score below which → block
        self._score_min:       float | None = None   # for normalization
        self._score_max:       float | None = None

    # ── Training ──────────────────────────────────────────────────────────────

    def fit(self, clean_embeddings: list[list[float]]) -> None:
        """
        Train Isolation Forest on clean corpus embeddings.

        Args:
            clean_embeddings: embeddings of is_original=TRUE chunks from pgvector.
        """
        from sklearn.ensemble import IsolationForest

        X = np.array(clean_embeddings, dtype=np.float32)
        print(f"[IsolationForestFilter] Training on {X.shape[0]} clean embeddings "
              f"(dim={X.shape[1]})...")

        self._model = IsolationForest(
            n_estimators  = self.n_estimators,
            contamination = self.contamination,
            random_state  = self.random_state,
            n_jobs        = -1,
        )
        self._model.fit(X)

        # Compute score distribution on training data for normalization
        train_scores = self._model.score_samples(X)   # higher = more normal
        self._score_min = float(train_scores.min())
        self._score_max = float(train_scores.max())

        # Block threshold: percentile of clean scores (most anomalous tail)
        self._threshold_score = float(
            np.percentile(train_scores, self.block_threshold_percentile)
        )

        print(f"[IsolationForestFilter] score range: [{self._score_min:.4f}, "
              f"{self._score_max:.4f}]")
        print(f"[IsolationForestFilter] block threshold "
              f"(p{self.block_threshold_percentile:.0f}): {self._threshold_score:.4f}")

    # ── Scoring ───────────────────────────────────────────────────────────────

    def predict(self, embedding: list[float]) -> tuple[bool, float]:
        """
        Score a single chunk embedding.

        Returns:
            is_malicious (bool): True if anomaly score exceeds block threshold.
            trust_score  (float): Normalized anomaly score in [0,1].
                                  0 = very normal; 1 = very anomalous.
        """
        if self._model is None:
            raise RuntimeError("Call fit() before predict().")

        x = np.array(embedding, dtype=np.float32).reshape(1, -1)
        raw_score = float(self._model.score_samples(x)[0])  # higher = more normal

        trust_score = self._normalize(raw_score)
        is_malicious = raw_score < self._threshold_score

        return is_malicious, round(trust_score, 4)

    def _normalize(self, raw_score: float) -> float:
        """
        Map raw IF score → trust_score ∈ [0,1].
        Inverts direction: higher raw score (normal) → lower trust_score.
        Clips scores outside training range to [0,1].
        """
        span = self._score_max - self._score_min
        if span < 1e-9:
            return 0.0
        # Invert: score_max → 0.0 (normal), score_min → 1.0 (anomalous)
        trust = (self._score_max - raw_score) / span
        return float(np.clip(trust, 0.0, 1.0))

    # ── Config factory ────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config: "ExperimentConfig") -> "IsolationForestFilter":
        """Instantiate from ExperimentConfig (experiment_02_if.yaml)."""
        defense = getattr(config, "defense", {}) or {}
        if_cfg  = defense.get("isolation_forest", {})
        return cls(
            n_estimators               = if_cfg.get("n_estimators",               100),
            contamination              = if_cfg.get("contamination",              "auto"),
            random_state               = if_cfg.get("random_state",                42),
            block_threshold_percentile = if_cfg.get("block_threshold_percentile",  10.0),
        )
