"""
main.py — RAG 知識庫污染攻擊與防禦評估管線

五階段執行流程：
  Phase 1  攻擊生成   → <output>/phase1/poison_chunks.json
  Phase 2  入庫防禦 A → pgvector DB + <output>/phase2/audit_defense_a.jsonl
  Phase 3  檢索防禦 B → <output>/phase3/retrieval_results.json + audit_defense_b.jsonl
  Phase 4  目標生成   → <output>/phase4/phase4_results.json
  Phase 5  人工標註   → <output>/phase5/phase5_annotated.json（互動式 CLI）

用法：
    python main.py                                           # 完整五階段（預設 config + output/）
    python main.py --phases 1 2 3 4                         # 跳過 Phase 5
    python main.py --from-phase 3                           # 從 Phase 3 繼續
    python main.py --phase 1                                # 單獨執行 Phase 1
    python main.py --force                                  # 無視現有輸出，重新執行全部
    python main.py --config configs/experiment_no_defense.yaml --output-dir output/no_defense --phases 1 2 3 4 --force
"""

import argparse
import json
import sys
import time
from pathlib import Path

from src.config import ExperimentConfig

DEFAULT_CONFIG     = "configs/experiment_01.yaml"
DEFAULT_OUTPUT_DIR = "output"
QUERIES_PATH       = "data/queries.json"

PHASE_NAMES = {
    1: "Phase 1 — Attack Generation",
    2: "Phase 2 — Injection + Defense A",
    3: "Phase 3 — Retrieval + Defense B",
    4: "Phase 4 — Target Generation",
    5: "Phase 5 — Human Annotation",
}


def _phase_outputs(output_dir: str) -> dict[int, Path]:
    base = Path(output_dir)
    return {
        1: base / "phase1/poison_chunks.json",
        2: base / "phase2/audit_defense_a.jsonl",
        3: base / "phase3/retrieval_results.json",
        4: base / "phase4/phase4_results.json",
        5: base / "phase5/phase5_annotated.json",
    }


# ── Phase runners ─────────────────────────────────────────────────────────────

def run_phase1(config: ExperimentConfig, paths: dict[int, Path]) -> None:
    from src.pipeline.phase1 import Phase1Generator

    queries   = json.loads(Path(QUERIES_PATH).read_text(encoding="utf-8"))
    generator = Phase1Generator(config)
    generator.run(
        queries=queries,
        output_path=str(paths[1]),
        attack_types=["hijack", "blocker", "stealth"],
    )


def run_phase2(
    config: ExperimentConfig,
    paths: dict[int, Path],
    phase1_dir: str | None = None,
) -> None:
    from src.pipeline.phase2 import Phase2Injector

    poison_path = (
        Path(phase1_dir) / "phase1" / "poison_chunks.json"
        if phase1_dir else paths[1]
    )
    injector = Phase2Injector(config)
    injector.run(
        poison_chunks_path=str(poison_path),
        output_audit_path=str(paths[2]),
    )


def run_phase3(config: ExperimentConfig, paths: dict[int, Path]) -> None:
    from src.pipeline.phase3 import Phase3Retriever

    retriever = Phase3Retriever(config)
    retriever.run(
        queries_path=QUERIES_PATH,
        output_results_path=str(paths[3]),
        output_audit_path=str(paths[3].parent / "audit_defense_b.jsonl"),
    )


def run_phase4(config: ExperimentConfig, paths: dict[int, Path]) -> None:
    from src.pipeline.phase4 import Phase4Generator

    generator = Phase4Generator(config)
    generator.run(
        retrieval_results_path=str(paths[3]),
        queries_path=QUERIES_PATH,
        output_path=str(paths[4]),
    )


def run_phase5(_config: ExperimentConfig, paths: dict[int, Path]) -> None:
    from src.pipeline.phase5 import run_annotation

    run_annotation(
        input_path=str(paths[4]),
        output_path=str(paths[5]),
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
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG, metavar="PATH",
        help=f"Path to experiment YAML config (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR, dest="output_dir", metavar="DIR",
        help=f"Root directory for all phase outputs (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--phase1-dir", default=None, dest="phase1_dir", metavar="DIR",
        help="Directory that contains phase1/poison_chunks.json (default: same as --output-dir). "
             "Use when re-running Phase 2+ with a different config but the same Phase 1 output.",
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

    config        = ExperimentConfig.from_yaml(args.config)
    phase_outputs = _phase_outputs(args.output_dir)
    phase1_dir    = args.phase1_dir

    print(f"\n{'='*60}")
    print(f"  RAG Poisoning Pipeline")
    print(f"  Config   : {args.config}")
    print(f"  Output   : {args.output_dir}")
    print(f"  Phases   : {phases_to_run}")
    print(f"  Attacker : {config.attacker_model}")
    print(f"  Target   : {config.target_model}")
    print(f"  Embedding: {config.embedding_model}")
    print(f"{'='*60}\n")

    pipeline_start = time.perf_counter()

    for phase_num in phases_to_run:
        output = phase_outputs.get(phase_num)
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
            if phase_num == 2:
                run_phase2(config, phase_outputs, phase1_dir)
            else:
                _RUNNERS[phase_num](config, phase_outputs)
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
