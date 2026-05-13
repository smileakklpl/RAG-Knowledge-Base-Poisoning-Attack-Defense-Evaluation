"""
tools/annotate.py — Phase 5 人工標註 CLI 入口

用法：
    python tools/annotate.py
    python tools/annotate.py --input  output/phase4/phase4_results.json
    python tools/annotate.py --annotator WL
"""

import argparse
from src.pipeline.phase5 import DEFAULT_INPUT, DEFAULT_OUTPUT, run_annotation


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 5 人工標註工具")
    parser.add_argument("--input",     default=DEFAULT_INPUT,  help="Phase 4 results JSON")
    parser.add_argument("--output",    default=DEFAULT_OUTPUT, help="Annotated output JSON")
    parser.add_argument("--annotator", default="",             help="標註者名稱或 ID")
    args = parser.parse_args()

    run_annotation(
        input_path=args.input,
        output_path=args.output,
        annotator=args.annotator,
    )


if __name__ == "__main__":
    main()
