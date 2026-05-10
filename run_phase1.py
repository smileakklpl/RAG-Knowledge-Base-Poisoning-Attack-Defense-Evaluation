"""
run_phase1.py — Phase 1 批次攻擊生成

對所有 Target Queries × 所有 Attack Types 執行完整批次生成，
輸出 output/poison_chunks.json 供 Phase 2 使用。

用法：
    python run_phase1.py
    python run_phase1.py --attack-types hijack stealth
    python run_phase1.py --output output/custom.json
"""

import argparse
import json
import time
from pathlib import Path

from src.config import ExperimentConfig
from src.pipeline.phase1 import Phase1Generator

CONFIG_PATH  = "configs/experiment_01.yaml"
QUERIES_PATH = "data/queries.json"
OUTPUT_PATH  = "output/poison_chunks.json"

# Representative multi-clause sample covering all 5 query domains (CUAD style)
CLEAN_SAMPLE = """\
ARTICLE 5 — TERM AND TERMINATION
This Agreement shall commence on the Effective Date and continue for an initial term \
of one (1) year. Either Party may terminate this Agreement without cause upon ninety \
(90) days prior written notice to the other Party. Termination for material breach \
shall become effective thirty (30) days after written notice of such breach, provided \
the breach remains uncured during that period.

ARTICLE 8 — GOVERNING LAW AND DISPUTE RESOLUTION
This Agreement shall be governed by and construed in accordance with the laws of the \
State of Delaware, without regard to its conflict of law provisions. Any dispute \
arising out of or relating to this Agreement shall be subject to the exclusive \
jurisdiction of the state and federal courts located in Wilmington, Delaware.

ARTICLE 11 — LIMITATION OF LIABILITY
IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR \
CONSEQUENTIAL DAMAGES. EACH PARTY'S TOTAL CUMULATIVE LIABILITY ARISING OUT OF OR \
RELATED TO THIS AGREEMENT SHALL NOT EXCEED THE TOTAL FEES PAID IN THE TWELVE (12) \
MONTHS IMMEDIATELY PRECEDING THE EVENT GIVING RISE TO THE CLAIM.

ARTICLE 14 — RESTRICTIVE COVENANTS
During the term of employment and for a period of twelve (12) months following any \
termination, Employee shall not engage in any activity that directly competes with \
the Company's business within the Territory, and shall not solicit any clients or \
employees of the Company for competitive purposes.

ARTICLE 17 — PAYMENT TERMS
All invoices shall be due and payable within thirty (30) days of the invoice date. \
Late payments shall accrue interest at 1.5% per month. The Client retains the right \
to dispute any invoice in writing within ten (10) days of receipt, after which the \
invoice shall be deemed accepted.\
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--attack-types", nargs="+",
        default=["hijack", "blocker", "stealth"],
        help="Attack types to generate (default: all three)",
    )
    parser.add_argument(
        "--output", default=OUTPUT_PATH,
        help=f"Output JSON path (default: {OUTPUT_PATH})",
    )
    args = parser.parse_args()

    config  = ExperimentConfig.from_yaml(CONFIG_PATH)
    queries = json.loads(Path(QUERIES_PATH).read_text(encoding="utf-8"))

    total = len(queries) * len(args.attack_types)
    print(f"\n{'='*60}")
    print(f"  Phase 1 Batch Generation")
    print(f"  queries      : {len(queries)}")
    print(f"  attack_types : {args.attack_types}")
    print(f"  total jobs   : {total}")
    print(f"  max_iter     : {config.max_iter}")
    print(f"  attacker     : {config.attacker_model}")
    print(f"  embedding    : {config.embedding_model}")
    print(f"  output       : {args.output}")
    print(f"{'='*60}\n")

    t_start   = time.perf_counter()
    generator = Phase1Generator(config)

    chunks = generator.run_batch(
        queries=queries,
        clean_sample=CLEAN_SAMPLE,
        attack_types=args.attack_types,
    )

    generator.save(chunks, args.output)
    elapsed = time.perf_counter() - t_start

    accepted = sum(c.accepted for c in chunks)
    print(f"\n{'='*60}")
    print(f"  Summary")
    print(f"  total chunks : {len(chunks)}")
    print(f"  accepted     : {accepted} / {len(chunks)}")
    print(f"  elapsed      : {elapsed:.1f}s  ({elapsed / len(chunks):.1f}s/chunk avg)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
