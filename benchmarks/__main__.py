"""Run and discover Scopecat benchmarks through one local entrypoint."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable, Sequence
from typing import cast

from .registry import BENCHMARK_CASES, benchmark_case


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m benchmarks")
    subparsers = parser.add_subparsers(dest="command", required=True)
    list_parser = subparsers.add_parser("list", help="list registered cases")
    list_parser.add_argument("--json", action="store_true")
    run_parser = subparsers.add_parser("run", help="run one registered case")
    run_parser.add_argument("case", choices=tuple(case.id for case in BENCHMARK_CASES))
    run_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    selected = _parser().parse_args(argv)
    values = cast("dict[str, object]", vars(selected))
    command = cast("str", values["command"])
    if command == "list":
        if cast("bool", values["json"]):
            print(
                json.dumps(
                    [
                        {
                            "id": case.id,
                            "kind": case.kind,
                            "summary": case.summary,
                        }
                        for case in BENCHMARK_CASES
                    ],
                    indent=2,
                )
            )
        else:
            for case in BENCHMARK_CASES:
                print(f"{case.id:<24} {case.kind:<9} {case.summary}")
        return 0

    case = benchmark_case(cast("str", values["case"]))
    module = importlib.import_module(case.module)
    run = cast("Callable[[], int | None]", module.main)
    previous_argv = sys.argv
    sys.argv = [
        f"python -m benchmarks run {case.id}",
        *cast("list[str]", values["arguments"]),
    ]
    try:
        return run() or 0
    finally:
        sys.argv = previous_argv


if __name__ == "__main__":
    raise SystemExit(main())
