"""
main_if.py — Isolation Forest + Counter-Retrieval Defense Pipeline

New experiment pipeline using experiment_02_if.yaml.
Targets rag_poison_if database — does NOT touch the original rag_poison DB.

Prerequisites (run once before first experiment):
  1. Create new DB:
       createdb -U postgres rag_poison_if
  2. Apply schema:
       psql -U postgres -d rag_poison_if -f db/init.sql
  3. Apply trust_score migration:
       psql -U postgres -d rag_poison_if -f db/migration_01_trust_score.sql

Pipeline stages:
  Phase 1  Attack generation    → output/phase1/poison_chunks.json    (reuse existing)
  Phase 2  IF Defense A         → output/phase2_if/audit_defense_a_if.jsonl
  Phase 3  CR Defense B         → output/phase3_cr/retrieval_results_cr.json
  Phase 4  Target LLM answer    → output/phase4_if/phase4_results.json
  Phase 5  Human annotation     → output/phase5_if/phase5_annotated.json

Usage:
  python main_if.py                        # full pipeline (Phase 2–5)
  python main_if.py --phases 2 3           # only Defense A + B
  python main_if.py --from-phase 3         # resume from Phase 3
  python main_if.py --phase 2              # single phase
  python main_if.py --force                # re-run even if output exists
  python main_if.py --setup-db             # print DB setup instructions and exit
"""

import argparse
import json
import sys
import time
from pathlib import Path

from src.config import ExperimentConfig

CONFIG_PATH  = "configs/experiment_02_if.yaml"
QUERIES_PATH = "data/queries.json"

PHASE_OUTPUTS = {
    1: Path("output/phase1/poison_chunks.json"),          # shared with original pipeline
    2: Path("output/phase2_if/audit_defense_a_if.jsonl"),
    3: Path("output/phase3_cr/retrieval_results_cr.json"),
    4: Path("output/phase4_if/phase4_results.json"),
    5: Path("output/phase5_if/phase5_annotated.json"),
}

PHASE_NAMES = {
    1: "Phase 1 — Attack Generation     (shared output, usually skipped)",
    2: "Phase 2 — IF Defense A          (Isolation Forest ingestion filter)",
    3: "Phase 3 — CR Defense B          (Counter-Retrieval Verification)",
    4: "Phase 4 — Target LLM Generation",
    5: "Phase 5 — Human Annotation",
}

# ── Phase runners ─────────────────────────────────────────────────────────────

def run_phase1(config: ExperimentConfig) -> None:
    """Phase 1 is shared — reuse output from original pipeline if available."""
    from src.pipeline.phase1 import Phase1Generator

    queries   = json.loads(Path(QUERIES_PATH).read_text(encoding="utf-8"))
    generator = Phase1Generator(config)
    generator.run(
        queries      = queries,
        output_path  = str(PHASE_OUTPUTS[1]),
        attack_types = ["hijack", "blocker", "stealth"],
    )


def run_phase2(config: ExperimentConfig) -> None:
    from src.pipeline.phase2_if import Phase2InjectorIF

    injector = Phase2InjectorIF(config)
    injector.run(
        poison_chunks_path = str(PHASE_OUTPUTS[1]),
        output_audit_path  = str(PHASE_OUTPUTS[2]),
    )


def run_phase3(config: ExperimentConfig) -> None:
    from src.pipeline.phase3_cr import Phase3RetrieverCR

    retriever = Phase3RetrieverCR(config)
    retriever.run(
        queries_path        = QUERIES_PATH,
        output_results_path = str(PHASE_OUTPUTS[3]),
        output_audit_path   = "output/phase3_cr/audit_defense_b_cr.jsonl",
    )


def run_phase4(config: ExperimentConfig) -> None:
    from src.pipeline.phase4 import Phase4Generator

    generator = Phase4Generator(config)
    generator.run(
        retrieval_results_path = str(PHASE_OUTPUTS[3]),
        queries_path           = QUERIES_PATH,
        output_path            = str(PHASE_OUTPUTS[4]),
    )


def run_phase5(_config: ExperimentConfig) -> None:
    from src.pipeline.phase5 import run_annotation

    run_annotation(
        input_path  = str(PHASE_OUTPUTS[4]),
        output_path = str(PHASE_OUTPUTS[5]),
    )


_RUNNERS = {
    1: run_phase1,
    2: run_phase2,
    3: run_phase3,
    4: run_phase4,
    5: run_phase5,
}

# ── DB setup helper ───────────────────────────────────────────────────────────

def print_setup_instructions() -> None:
    print("""
DB Setup Instructions (run once, then use main_if.py normally)
===============================================================

1. Create the isolated experiment database:

       createdb -U postgres rag_poison_if

   Or via psql:
       psql -U postgres -c "CREATE DATABASE rag_poison_if;"

2. Apply the base schema (same as rag_poison):

       psql -U postgres -d rag_poison_if -f db/init.sql

3. Add the trust_score column:

       psql -U postgres -d rag_poison_if -f db/migration_01_trust_score.sql

4. Run Phase 1 to populate clean chunks (or reuse existing output):

       python main_if.py --phase 1
         -- OR if output/phase1/poison_chunks.json already exists, skip Phase 1.

5. Run the full IF+CR defense pipeline:

       python main_if.py --from-phase 2

Note: rag_poison (original experiment DB) is never touched.
""")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAG poisoning — Isolation Forest + Counter-Retrieval pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--phases", nargs="+", type=int, metavar="N",
        help="Phases to run, e.g. --phases 2 3 4",
    )
    group.add_argument(
        "--from-phase", type=int, metavar="N",
        help="Start from phase N (assumes Phase 1 output already exists)",
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
        "--setup-db", action="store_true",
        help="Print DB setup instructions and exit",
    )
    args = parser.parse_args()

    if args.setup_db:
        print_setup_instructions()
        sys.exit(0)

    if args.phase:
        phases_to_run = [args.phase]
    elif args.phases:
        phases_to_run = sorted(set(args.phases))
    elif args.from_phase:
        phases_to_run = list(range(args.from_phase, 6))
    else:
        # Default: skip Phase 1 if output already exists (reuse attack generation)
        phases_to_run = [2, 3, 4, 5]

    config = ExperimentConfig.from_yaml(CONFIG_PATH)

    print(f"\n{'='*60}")
    print(f"  RAG Poisoning — IF + CR Defense Pipeline")
    print(f"  Config   : {CONFIG_PATH}")
    print(f"  Database : {config.vector_db.get('database', 'rag_poison_if')}")
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
            print(f"        output exists: {output}  (use --force to re-run)\n")
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
