"""
defense/filter.py — Defense Filter（防禦點 A 與 B 共用）

最終方法論：特徵提取 + XGBoost 二元分類（見 docs/defense_methodology.md）
候選特徵（8 個）：PPL、字元熵、特殊字元比例、重複 n-gram 比例、
                    指令語氣詞密度、文本長度、語意跳躍分數、TTR

狀態：stub — XGBoost 模型尚未訓練，實作前請先完成 Phase 1 批次生成
       以取得足夠的 poison chunk 訓練資料。
"""

from src.config import ExperimentConfig


class DefenseFilter:
    """
    Binary classifier: predicts whether a text chunk is a poisoned injection.

    Production path:
        1. Extract 8 features from chunk text
        2. XGBoost predict_proba → malicious probability
        3. Compare against threshold → bool decision

    Usage:
        filter_a = DefenseFilter(threshold=0.4)   # Defense Point A (strict)
        filter_b = DefenseFilter(threshold=0.6)   # Defense Point B (lenient)
        is_malicious, score = filter_a.predict(chunk_text)
    """

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def predict(self, chunk_text: str) -> tuple[bool, float]:
        """
        Returns:
            (is_malicious, malicious_probability)
        """
        raise NotImplementedError(
            "DefenseFilter not yet implemented. "
            "See docs/defense_methodology.md for the full specification."
        )

    @classmethod
    def from_config(cls, config: ExperimentConfig, point: str) -> "DefenseFilter":
        """
        Args:
            point: 'pre_injection' or 'post_retrieval'
        """
        raise NotImplementedError(
            "DefenseFilter.from_config not yet implemented."
        )
