"""
moo/__main__.py — Entry point for running the diagnostic as a package:
    python -m moo [--help] [--report-dir <dir>]

This module is the ONLY way to run strategy_diagnostic.py directly,
because the package uses relative imports throughout.
"""

from __future__ import annotations

import argparse
import sys
import os

# ---------------------------------------------------------------------------
# Force UTF-8 output on Windows so box-drawing / emoji chars in
# strategy_diagnostic.py don't cause UnicodeEncodeError on cp1252 consoles.
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    except Exception:
        pass  # If reconfiguration fails, continue anyway


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m moo",
        description=(
            "TOACD MOO Diagnostic — Stage 1: Strategy Verification\n\n"
            "Runs all 9 existing optimization strategies on two test programs\n"
            "(TC1_loop_heavy.c and security_checks.c), captures commands,\n"
            "return codes, stdout/stderr, IR SHA-256 hashes, and correctness\n"
            "vs. the reference (baseline) execution.\n\n"
            "Does NOT modify any existing project files.\n"
            "Does NOT implement MOO, Pareto, scoring, or any ML logic."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--report-dir",
        metavar="DIR",
        default=None,
        help=(
            "Directory where JSON diagnostic reports are saved. "
            "Defaults to Codes/Python Scripts/moo/reports/. "
            "Can also be set via the TOACD_REPORT_DIR environment variable."
        ),
    )
    parser.add_argument(
        "--clang",
        metavar="PATH",
        default=None,
        help=(
            "Override the clang executable path. "
            "Can also be set via TOACD_CLANG_PATH environment variable."
        ),
    )
    parser.add_argument(
        "--opt",
        metavar="PATH",
        default=None,
        help=(
            "Override the opt executable path. "
            "Can also be set via TOACD_OPT_PATH environment variable."
        ),
    )

    args = parser.parse_args()

    # Apply CLI overrides to environment before importing config
    # (config.py reads env vars at import time).
    if args.clang:
        os.environ["TOACD_CLANG_PATH"] = args.clang
    if args.opt:
        os.environ["TOACD_OPT_PATH"] = args.opt
    if args.report_dir:
        os.environ["TOACD_REPORT_DIR"] = args.report_dir

    # Import after potential env-var overrides
    from .strategy_diagnostic import run_diagnostic

    return run_diagnostic(report_dir=args.report_dir)


if __name__ == "__main__":
    sys.exit(main())
