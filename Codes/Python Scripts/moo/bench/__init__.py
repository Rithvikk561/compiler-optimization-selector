"""
moo/bench/__init__.py — Week 9 Automated Benchmark & Dataset Generation package.

This package provides substantially stronger benchmark/dataset generation than
the legacy generate_dataset.py / process_25_tests.py scripts.

Key improvements over legacy scripts:
  - Deterministic corpus manifest with SHA-256 identity tracking.
  - Seeded synthetic C program generator (6 families, bounded execution,
    no undefined behaviour, no rand/time/scanf/malloc).
  - Batch runner reusing the existing pipeline.evaluate_program() measurement
    engine (no new timing implementation).
  - Explicit schema versions on every output artifact.
  - Failures represented as null + explicit reason (never zero-filled).
  - 70/15/15 deterministic dataset splits with family-group leakage prevention.
  - O0 baseline conventions from Week 8 are documented, not silently changed.

Output locations (separate from moo/reports/ to avoid selector cache pollution):
  Generated sources : Codes/benchmarks_generated/
  Run outputs       : Codes/Benchmarks/runs/<run_id>/
  Datasets          : Codes/Datasets/week9/
"""

from .schema import (
    BENCH_SCHEMA_VERSION,
    DATASET_SCHEMA_VERSION,
    CorpusEntry,
    RunManifest,
    ProgramRecord,
    DatasetManifest,
)
from .corpus import build_corpus_manifest, load_corpus_manifest
from .generator import BenchmarkGenerator, GENERATOR_FAMILIES
from .runner import BenchmarkRunner
from .dataset import DatasetBuilder

__all__ = [
    "BENCH_SCHEMA_VERSION",
    "DATASET_SCHEMA_VERSION",
    "CorpusEntry",
    "RunManifest",
    "ProgramRecord",
    "DatasetManifest",
    "build_corpus_manifest",
    "load_corpus_manifest",
    "BenchmarkGenerator",
    "GENERATOR_FAMILIES",
    "BenchmarkRunner",
    "DatasetBuilder",
]
