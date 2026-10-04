"""
moo/bench/__main__.py — CLI entry point for the Week 9 benchmark system.

Usage
-----
python -m moo.bench [command] [options]

Commands
--------
  corpus     Print or save the corpus manifest.
  generate   Generate synthetic C benchmark programs.
  run        Run the benchmark suite (requires clang toolchain).
  dataset    Build CSV datasets from a completed run.
  info       Show package configuration.

Examples
--------
  python -m moo.bench corpus
  python -m moo.bench generate --seed 42 --n 5 --out Codes/benchmarks_generated
  python -m moo.bench info
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def _find_project_dirs() -> tuple[str, str]:
    """
    Locate Codes/ and Python Scripts/ relative to this file.
    Returns (codes_dir, ps_dir).
    """
    here = os.path.dirname(os.path.abspath(__file__))  # moo/bench/
    moo_dir = os.path.dirname(here)                     # moo/
    ps_dir  = os.path.dirname(moo_dir)                  # Python Scripts/
    codes_dir = os.path.dirname(ps_dir)                 # Codes/
    return codes_dir, ps_dir


def cmd_info(args: argparse.Namespace) -> int:
    """Show configuration and package information."""
    codes_dir, ps_dir = _find_project_dirs()

    from moo.bench.schema import BENCH_SCHEMA_VERSION, DATASET_SCHEMA_VERSION
    from moo.bench.generator import GENERATOR_FAMILIES

    try:
        from moo.config import CLANG_PATH, OPT_PATH, ACTIONS, WARMUP_RUNS, MEASURE_RUNS
        clang = CLANG_PATH or "NOT FOUND"
        opt   = OPT_PATH or "NOT FOUND"
        n_actions = len(ACTIONS)
        warmup = WARMUP_RUNS
        measure = MEASURE_RUNS
    except Exception as exc:
        clang = opt = f"(config error: {exc})"
        n_actions = warmup = measure = "?"

    print("TOACD Week 9 — Automated Benchmark & Dataset Generation")
    print(f"  Bench schema version   : {BENCH_SCHEMA_VERSION}")
    print(f"  Dataset schema version : {DATASET_SCHEMA_VERSION}")
    print(f"  Generator families     : {', '.join(GENERATOR_FAMILIES)}")
    print(f"  clang                  : {clang}")
    print(f"  opt                    : {opt}")
    print(f"  strategies (ACTIONS)   : {n_actions}")
    print(f"  warmup runs            : {warmup}")
    print(f"  measure runs           : {measure}")
    print(f"  codes_dir              : {codes_dir}")
    print(f"  test_cases_dir         : {os.path.join(codes_dir, 'test_cases')}")
    return 0


def cmd_corpus(args: argparse.Namespace) -> int:
    """Build and display the corpus manifest."""
    codes_dir, _ = _find_project_dirs()
    test_cases_dir = os.path.join(codes_dir, "test_cases")

    from moo.bench.corpus import build_corpus_manifest, save_corpus_manifest

    entries = build_corpus_manifest(test_cases_dir)
    active = [e for e in entries if not e.excluded]
    excluded = [e for e in entries if e.excluded]

    print(f"Corpus: {len(entries)} total, {len(active)} active, {len(excluded)} excluded")
    for e in entries:
        tag = "EXCL" if e.excluded else "OK  "
        print(f"  [{tag}] {e.program_id:40s} {e.source_sha256[:12]}... ({e.origin})")

    if args.output:
        save_corpus_manifest(entries, args.output)
        print(f"Manifest saved to: {args.output}")

    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate synthetic C benchmark programs."""
    from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES

    out_dir = args.out or os.path.join(
        _find_project_dirs()[0], "benchmarks_generated"
    )
    seed = args.seed
    n    = args.n

    fams = args.families.split(",") if args.families else list(GENERATOR_FAMILIES)
    fams = [f.strip() for f in fams if f.strip() in GENERATOR_FAMILIES]
    if not fams:
        print(f"No valid families. Choose from: {', '.join(GENERATOR_FAMILIES)}")
        return 1

    gen = BenchmarkGenerator(seed=seed, output_dir=out_dir)
    entries = gen.generate(n_per_family=n, families=tuple(fams))

    print(f"Generated {len(entries)} programs (seed={seed}, n_per_family={n})")
    for e in entries:
        print(f"  {e.program_id:50s} -> {e.source_path}")

    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run the benchmark suite (requires clang)."""
    codes_dir, _ = _find_project_dirs()
    test_cases_dir = os.path.join(codes_dir, "test_cases")

    from moo.bench.corpus import build_corpus_manifest
    from moo.bench.runner import BenchmarkRunner

    run_dir = args.run_dir or os.path.join(codes_dir, "Benchmarks", "runs", "latest")

    entries = build_corpus_manifest(test_cases_dir)
    active = [e for e in entries if not e.excluded]
    print(f"Suite: {len(active)} active programs")

    runner = BenchmarkRunner(
        run_dir=run_dir,
        suite_name=args.suite_name or "week9_benchmark",
        resume=not args.no_resume,
    )
    manifest = runner.run(active, verbose=True)
    print(f"Run complete: {manifest.status}")
    print(f"  ok={manifest.n_programs_ok}, failed={manifest.n_programs_failed}")
    return 0


def cmd_dataset(args: argparse.Namespace) -> int:
    """Build CSV datasets from a completed run."""
    codes_dir, _ = _find_project_dirs()

    from moo.bench.runner import BenchmarkRunner
    from moo.bench.dataset import DatasetBuilder

    run_dir = args.run_dir
    if not run_dir or not os.path.isdir(run_dir):
        print(f"Run directory not found: {run_dir!r}")
        return 1

    out_dir = args.out or os.path.join(codes_dir, "Datasets", "week9")

    runner = BenchmarkRunner(run_dir=run_dir)
    records = runner.load_records()

    # Get run_id from manifest if available
    manifest_path = os.path.join(run_dir, "run_manifest.json")
    run_id = "unknown"
    if os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            run_id = json.load(fh).get("run_id", "unknown")

    builder = DatasetBuilder(output_dir=out_dir)
    ds_manifest = builder.build(records, run_id=run_id, verbose=True)
    print(f"Dataset: {ds_manifest.n_candidate_rows} candidate rows, "
          f"{ds_manifest.n_program_rows} program rows")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m moo.bench",
        description="TOACD Week 9 Automated Benchmark & Dataset Generation",
    )
    sub = parser.add_subparsers(dest="command")

    # info
    sub.add_parser("info", help="Show configuration and package info")

    # corpus
    p_corpus = sub.add_parser("corpus", help="Build/display corpus manifest")
    p_corpus.add_argument("--output", "-o", help="Save manifest to JSON file")

    # generate
    p_gen = sub.add_parser("generate", help="Generate synthetic C programs")
    p_gen.add_argument("--seed",     "-s", type=int, default=42, help="Random seed (default: 42)")
    p_gen.add_argument("--n",        "-n", type=int, default=5,  help="Programs per family (default: 5)")
    p_gen.add_argument("--out",      "-o", help="Output directory for .c files")
    p_gen.add_argument("--families", "-f", help="Comma-separated family list (default: all)")

    # run
    p_run = sub.add_parser("run", help="Run benchmark suite (requires clang)")
    p_run.add_argument("--run-dir",    help="Output directory for run results")
    p_run.add_argument("--suite-name", help="Suite label (default: week9_benchmark)")
    p_run.add_argument("--no-resume",  action="store_true",
                       help="Re-run already-completed programs")

    # dataset
    p_ds = sub.add_parser("dataset", help="Build CSV datasets from a completed run")
    p_ds.add_argument("run_dir",   help="Run output directory (containing run_manifest.json)")
    p_ds.add_argument("--out", "-o", help="Output directory for CSV/manifest files")

    args = parser.parse_args()

    commands = {
        "info":     cmd_info,
        "corpus":   cmd_corpus,
        "generate": cmd_generate,
        "run":      cmd_run,
        "dataset":  cmd_dataset,
    }

    if args.command not in commands:
        parser.print_help()
        sys.exit(0)

    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
