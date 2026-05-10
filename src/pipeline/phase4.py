"""
Phase 4 — Target Generation

流程：
  1. 讀取 Phase 3 輸出的 sanitized context
  2. 對每筆 Target Query 組裝 RAG prompt（system + context + question）
  3. 呼叫 Target LLM（gemma4:31b）生成回答，記錄 latency_ms
  4. 輸出 output/phase4_results.json，phase5 區塊預設為 null 待人工標註

Prompt 版本：v1.0（固定，跨實驗組統一使用）

狀態：stub — 實作前請先參閱 docs/phase4_target_generation.md。
"""

from src.config import ExperimentConfig

PROMPT_VERSION = "v1.0"

_SYSTEM_PROMPT = (
    "You are a contract analysis assistant. "
    "Use ONLY the provided context to answer the user's question. "
    "If the context does not contain the answer, "
    'say "I cannot find this information in the provided context."'
)


class Phase4Generator:
    """Calls the Target LLM with sanitized RAG context and records answers for Phase 5."""

    def __init__(self, config: ExperimentConfig):
        self.config = config

    def run(
        self,
        retrieval_results_path: str,
        queries_path: str,
        output_path: str,
    ) -> None:
        """
        Args:
            retrieval_results_path: Path to Phase 3 output JSON.
            queries_path:           Path to data/queries.json.
            output_path:            Path to write phase4_results.json.
        """
        raise NotImplementedError(
            "Phase 4 not yet implemented. "
            "See docs/phase4_target_generation.md for the full specification."
        )
