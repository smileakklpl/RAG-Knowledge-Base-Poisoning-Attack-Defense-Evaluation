"""
Phase 3 — Retrieval + Post-Retrieval Defense (Defense Point B)

流程：
  1. 對每筆 Target Query 進行 embedding，向 pgvector 檢索 Top-K
  2. 記錄 Raw Top-K（用於計算 RSR）
  3. 對每筆 Top-K chunk 執行 Defense Filter B
     - 判定為惡意 → 從 pgvector 物理 DELETE，記錄到 audit log
     - 判定為乾淨 → 保留進入 sanitized context
  4. 輸出 output/retrieval_results.json 與 output/audit_defense_b.jsonl

狀態：stub — 實作前請先參閱 docs/phase3_trigger_retrieval.md。
"""

from src.config import ExperimentConfig


class Phase3Retriever:
    """Retrieves Top-K chunks from pgvector and applies Defense Point B."""

    def __init__(self, config: ExperimentConfig):
        self.config = config

    def run(
        self,
        queries_path: str,
        output_results_path: str,
        output_audit_path: str,
    ) -> None:
        """
        Args:
            queries_path:        Path to data/queries.json.
            output_results_path: Path to write retrieval results JSON.
            output_audit_path:   Path to write Defense B audit log JSONL.
        """
        raise NotImplementedError(
            "Phase 3 not yet implemented. "
            "See docs/phase3_trigger_retrieval.md for the full specification."
        )
