"""
defense/filter.py — PPL Filtering Defense (Defense Point A & B)

Method: Perplexity-based anomaly detection using GPT-2 small.

Two detection signals:
  1. Global PPL  — overall chunk perplexity; high value indicates Blocker-type anomaly
  2. Window spike PPL — maximum PPL over sliding windows; detects Hijack-type transition points

References:
  - RAGuard (Cheng et al., IEEE BigData 2025): chunk-wise PPL filtering for RAG poisoning defense
  - Alon & Kamfonas (arXiv 2308.14132): PPL-based adversarial text detection with GPT-2
"""

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import ExperimentConfig


class PPLDefenseFilter:
    """
    Perplexity-based binary classifier for detecting poisoned text chunks.

    GPT-2 small is loaded once at class level and shared across all instances.
    Typical thresholds (tunable):
        Defense A (pre-injection, strict) : global=80,  spike=120
        Defense B (post-retrieval, lenient): global=100, spike=150

    Usage:
        filter_a = PPLDefenseFilter.from_config(config, "pre_injection")
        filter_b = PPLDefenseFilter.from_config(config, "post_retrieval")
        is_malicious, score = filter_a.predict(chunk_text)
    """

    # Class-level cache: GPT-2 is loaded once and reused across all instances
    _tokenizer = None
    _model     = None

    def __init__(
        self,
        global_ppl_threshold: float = 100.0,
        spike_ppl_threshold:  float = 150.0,
        window_size:          int   = 50,
        stride:               int   = 25,
        max_tokens:           int   = 512,
    ):
        self.global_threshold = global_ppl_threshold
        self.spike_threshold  = spike_ppl_threshold
        self.window_size      = window_size
        self.stride           = stride
        self.max_tokens       = max_tokens
        self._ensure_model()

    # ── Model loading ─────────────────────────────────────────────────────────

    @classmethod
    def _ensure_model(cls) -> None:
        """Lazy-load GPT-2 small on first use. Cached across all instances."""
        if cls._model is not None:
            return
        from transformers import GPT2LMHeadModel, GPT2TokenizerFast
        print("[DefenseFilter] Loading GPT-2 small for PPL computation...")
        cls._tokenizer = GPT2TokenizerFast.from_pretrained("gpt2")
        cls._model     = GPT2LMHeadModel.from_pretrained("gpt2")
        cls._model.eval()
        print("[DefenseFilter] GPT-2 ready.")

    # ── PPL computation ───────────────────────────────────────────────────────

    def _ppl_from_ids(self, input_ids) -> float:
        """Compute PPL for a single tensor of token ids."""
        import torch
        with torch.no_grad():
            outputs = self._model(input_ids, labels=input_ids)
        return math.exp(outputs.loss.item())

    def compute_global_ppl(self, text: str) -> float:
        """Global PPL over the full chunk (truncated to max_tokens)."""
        ids = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_tokens,
        ).input_ids
        return self._ppl_from_ids(ids)

    def compute_max_window_ppl(self, text: str) -> float:
        """
        Maximum PPL over sliding windows.
        Detects local perplexity spikes at instruction-injection transition points.
        """
        ids = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_tokens,
        ).input_ids[0]

        n = len(ids)
        if n <= self.window_size:
            return self._ppl_from_ids(ids.unsqueeze(0))

        max_ppl = 0.0
        for start in range(0, n - self.window_size + 1, self.stride):
            window = ids[start : start + self.window_size].unsqueeze(0)
            max_ppl = max(max_ppl, self._ppl_from_ids(window))
        return max_ppl

    # ── Public interface ──────────────────────────────────────────────────────

    def predict(self, chunk_text: str) -> tuple[bool, float]:
        """
        Evaluate a chunk for malicious content via PPL anomaly detection.

        Returns:
            is_malicious (bool): True if either PPL signal exceeds its threshold.
            anomaly_score (float): Normalized score in [0, 1].
                - < 1.0: below threshold (not flagged)
                - = 1.0: at or above threshold (flagged)
                Score is capped at 1.0; raw excess is encoded in is_malicious.
        """
        global_ppl   = self.compute_global_ppl(chunk_text)
        max_win_ppl  = self.compute_max_window_ppl(chunk_text)

        global_ratio = global_ppl  / self.global_threshold
        spike_ratio  = max_win_ppl / self.spike_threshold
        raw          = max(global_ratio, spike_ratio)

        is_malicious  = raw >= 1.0
        anomaly_score = min(raw, 1.0)
        return is_malicious, round(anomaly_score, 4)

    @classmethod
    def from_config(cls, _config: "ExperimentConfig", point: str) -> "PPLDefenseFilter":
        """
        Instantiate with preset thresholds based on defense point.

        Args:
            config: ExperimentConfig (reserved for future YAML-level threshold config).
            point:  'pre_injection'  → Defense A (strict, lower thresholds)
                    'post_retrieval' → Defense B (lenient, higher thresholds)
        """
        if point == "pre_injection":
            return cls(global_ppl_threshold=80.0, spike_ppl_threshold=120.0)
        elif point == "post_retrieval":
            return cls(global_ppl_threshold=100.0, spike_ppl_threshold=150.0)
        else:
            raise ValueError(f"Unknown defense point: '{point}'. Use 'pre_injection' or 'post_retrieval'.")
