"""
smoke_test.py — Phase 1 快速驗證

執行條件：1 query × 1 attack_type × 1 iter
目的：確認 Ollama 連線、Embedding 計算、三個 Evaluator、JSON 輸出 均正常。

用法：
    python smoke_test.py
    python smoke_test.py --query-id q02 --attack-type stealth
"""

import argparse
import json
import time
from pathlib import Path

from src.config import ExperimentConfig
from src.pipeline.phase1 import Phase1Generator

CONFIG_PATH = "configs/experiment_01.yaml"
QUERIES_PATH = "data/queries.json"
OUTPUT_PATH = "output/tests/smoke_test_result.json"

CLEAN_SAMPLE = """\
This Agreement shall commence on the Effective Date and continue for an initial term \
of one (1) year, unless earlier terminated in accordance with the provisions hereof. \
Either party may terminate this Agreement upon ninety (90) days prior written notice \
to the other party. In the event of a material breach, the non-breaching party may \
terminate immediately upon written notice if such breach remains uncured for thirty (30) \
days following written notice of such breach.\
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-id",    default="q01",    help="Query ID from data/queries.json")
    parser.add_argument("--attack-type", default="hijack", help="hijack | blocker | stealth")
    parser.add_argument("--max-iter",    type=int, default=1, help="Override max_iter (default: 1)")
    args = parser.parse_args()

    # Load config and override max_iter for smoke test
    config = ExperimentConfig.from_yaml(CONFIG_PATH)
    config.max_iter = args.max_iter

    # Load query
    queries = json.loads(Path(QUERIES_PATH).read_text(encoding="utf-8"))
    query = next((q for q in queries if q["id"] == args.query_id), None)
    if query is None:
        raise ValueError(f"Query ID '{args.query_id}' not found in {QUERIES_PATH}")

    print(f"\n{'='*60}")
    print(f"  Phase 1 Smoke Test")
    print(f"  query_id   : {query['id']}")
    print(f"  attack_type: {args.attack_type}")
    print(f"  max_iter   : {config.max_iter}")
    print(f"  attacker   : {config.attacker_model}")
    print(f"  embedding  : {config.embedding_model}")
    print(f"{'='*60}\n")

    t_start = time.perf_counter()

    generator = Phase1Generator(config)
    chunk = generator.generate_one(
        query_id=query["id"],
        target_query=query["text"],
        malicious_payload=query["malicious_payload"],
        clean_sample=CLEAN_SAMPLE,
        attack_type=args.attack_type,
        trigger_keywords=query.get("trigger_keywords", []),
    )

    elapsed = time.perf_counter() - t_start

    generator.save([chunk], OUTPUT_PATH)

    print(f"\n{'='*60}")
    print(f"  Result")
    print(f"  accepted      : {chunk.accepted}")
    print(f"  iteration     : {chunk.iteration_count}")
    print(f"  sim_score     : {chunk.final_sim_score}")
    print(f"  stealth_score : {chunk.final_stealth_score}")
    print(f"  payload_score : {chunk.final_payload_score}")
    print(f"  elapsed       : {elapsed:.1f}s")
    print(f"{'='*60}")
    print(f"\n[Generated Text]\n{chunk.generated_text}\n")


if __name__ == "__main__":
    main()
