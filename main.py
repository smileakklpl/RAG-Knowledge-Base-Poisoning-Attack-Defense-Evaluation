"""
main.py — RAG 知識庫污染攻擊與防禦評估管線

五階段執行流程：
  Phase 1  攻擊生成   → output/poison_chunks.json
  Phase 2  入庫防禦 A → pgvector DB + output/audit_defense_a.jsonl
  Phase 3  檢索防禦 B → output/retrieval_results.json + output/audit_defense_b.jsonl
  Phase 4  目標生成   → output/phase4_results.json
  Phase 5  人工標註   → output/phase5_annotated.json（互動式 CLI）

用法：
    python main.py                       # 完整五階段
    python main.py --phases 1 2 3 4     # 跳過 Phase 5
    python main.py --from-phase 3       # 從 Phase 3 繼續（前兩階已有輸出）
    python main.py --phase 1            # 單獨執行 Phase 1
    python main.py --force              # 無視現有輸出，重新執行全部
"""

import argparse
import json
import sys
import time
from pathlib import Path

from src.config import ExperimentConfig

CONFIG_PATH  = "configs/experiment_01.yaml"
QUERIES_PATH = "data/queries.json"

# 各 Phase 的主要輸出檔案，用於判斷是否已完成
PHASE_OUTPUTS = {
    1: Path("output/phase1/poison_chunks.json"),
    2: Path("output/phase2/audit_defense_a.jsonl"),
    3: Path("output/phase3/retrieval_results.json"),
    4: Path("output/phase4/phase4_results.json"),
    5: Path("output/phase5/phase5_annotated.json"),
}

PHASE_NAMES = {
    1: "Phase 1 — Attack Generation",
    2: "Phase 2 — Injection + Defense A",
    3: "Phase 3 — Retrieval + Defense B",
    4: "Phase 4 — Target Generation",
    5: "Phase 5 — Human Annotation",
}

# Multi-clause clean sample covering all 5 query domains (CUAD style)
_CLEAN_SAMPLE = """\
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


# ── Phase runners ─────────────────────────────────────────────────────────────

def run_phase1(config: ExperimentConfig) -> None:
    from src.pipeline.phase1 import Phase1Generator

    queries   = json.loads(Path(QUERIES_PATH).read_text(encoding="utf-8"))
    generator = Phase1Generator(config)
    chunks    = generator.run_batch(
        queries=queries,
        clean_sample=_CLEAN_SAMPLE,
        attack_types=["hijack", "blocker", "stealth"],
    )
    generator.save(chunks, str(PHASE_OUTPUTS[1]))


def run_phase2(config: ExperimentConfig) -> None:
    from src.pipeline.phase2 import Phase2Injector

    injector = Phase2Injector(config)
    injector.run(
        poison_chunks_path=str(PHASE_OUTPUTS[1]),
        output_audit_path=str(PHASE_OUTPUTS[2]),
    )


def run_phase3(config: ExperimentConfig) -> None:
    from src.pipeline.phase3 import Phase3Retriever

    retriever = Phase3Retriever(config)
    retriever.run(
        queries_path=QUERIES_PATH,
        output_results_path=str(PHASE_OUTPUTS[3]),
        output_audit_path="output/phase3/audit_defense_b.jsonl",
    )


def run_phase4(config: ExperimentConfig) -> None:
    from src.pipeline.phase4 import Phase4Generator

    generator = Phase4Generator(config)
    generator.run(
        retrieval_results_path=str(PHASE_OUTPUTS[3]),
        queries_path=QUERIES_PATH,
        output_path=str(PHASE_OUTPUTS[4]),
    )


def run_phase5(_config: ExperimentConfig) -> None:
    from src.pipeline.phase5 import run_annotation

    run_annotation(
        input_path=str(PHASE_OUTPUTS[4]),
        output_path=str(PHASE_OUTPUTS[5]),
    )


_RUNNERS = {
    1: run_phase1,
    2: run_phase2,
    3: run_phase3,
    4: run_phase4,
    5: run_phase5,
}


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAG poisoning attack & defense evaluation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--phases", nargs="+", type=int, metavar="N",
        help="Phases to run, e.g. --phases 1 2 3",
    )
    group.add_argument(
        "--from-phase", type=int, metavar="N",
        help="Start from phase N (assumes earlier phases are already done)",
    )
    group.add_argument(
        "--phase", type=int, metavar="N",
        help="Run a single phase only",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-run phases even if output already exists",
    )
    args = parser.parse_args()

    if args.phase:
        phases_to_run = [args.phase]
    elif args.phases:
        phases_to_run = sorted(set(args.phases))
    elif args.from_phase:
        phases_to_run = list(range(args.from_phase, 6))
    else:
        phases_to_run = [1, 2, 3, 4, 5]

    config = ExperimentConfig.from_yaml(CONFIG_PATH)

    print(f"\n{'='*60}")
    print(f"  RAG Poisoning Pipeline")
    print(f"  Phases   : {phases_to_run}")
    print(f"  Attacker : {config.attacker_model}")
    print(f"  Target   : {config.target_model}")
    print(f"  Embedding: {config.embedding_model}")
    print(f"{'='*60}\n")

    pipeline_start = time.perf_counter()

    for phase_num in phases_to_run:
        output = PHASE_OUTPUTS.get(phase_num)
        if output and output.exists() and not args.force and phase_num != 5:
            print(f"[SKIP]  {PHASE_NAMES[phase_num]}")
            print(f"        output already exists: {output}")
            print(f"        use --force to re-run\n")
            continue

        print(f"{'─'*60}")
        print(f"[START] {PHASE_NAMES[phase_num]}")
        print(f"{'─'*60}")

        t = time.perf_counter()
        try:
            _RUNNERS[phase_num](config)
        except NotImplementedError as exc:
            print(f"\n[NOT IMPLEMENTED] {exc}\n")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n[INTERRUPTED] Pipeline stopped by user.")
            sys.exit(0)

        elapsed = time.perf_counter() - t
        print(f"[DONE]  {PHASE_NAMES[phase_num]}  ({elapsed:.1f}s)\n")

    total = time.perf_counter() - pipeline_start
    print(f"{'='*60}")
    print(f"  Pipeline complete  ({total:.1f}s total)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
