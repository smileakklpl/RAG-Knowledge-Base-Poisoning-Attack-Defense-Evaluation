"""
Phase 2 — Injection + Pre-Storage Defense (Defense Point A)

流程：
  1. 讀取 Phase 1 輸出（poison_chunks.json）與 CUAD 乾淨語料
  2. 依 poison_ratio 混合成候選 chunk 列表
  3. 對每筆候選 chunk 執行 Defense Filter A
     - 判定為惡意 → 不寫入 pgvector，記錄到 audit log
     - 判定為乾淨 → 寫入 pgvector，建立 HNSW 索引
  4. 輸出 output/audit_defense_a.jsonl（含所有 chunk 的判定結果）

狀態：stub — 實作前請先參閱 docs/phase2_injection_indexing.md。
"""

from src.config import ExperimentConfig


class Phase2Injector:
    """Injects Phase 1 poison chunks + CUAD clean corpus into pgvector with Defense Point A."""

    def __init__(self, config: ExperimentConfig):
        self.config = config

    def run(self, poison_chunks_path: str, output_audit_path: str) -> None:
        """
        Args:
            poison_chunks_path: Path to Phase 1 output JSON (output/poison_chunks.json).
            output_audit_path:  Path to write the Defense A audit log JSONL.
        """
        raise NotImplementedError(
            "Phase 2 not yet implemented. "
            "See docs/phase2_injection_indexing.md for the full specification."
        )
