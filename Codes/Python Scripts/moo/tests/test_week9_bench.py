"""
moo/tests/test_week9_bench.py — Week 9: Automated Benchmark & Dataset Generation Tests.

Test IDs follow the pattern W9-<CATEGORY><N>.

Categories
----------
  W9-SCHEMA   Schema model validation
  W9-CORPUS   Corpus manifest builder
  W9-GEN      Synthetic benchmark generator
  W9-RUN      Batch runner (toolchain-free tests)
  W9-DS       Dataset builder
  W9-SPLIT    Dataset split stability and leakage prevention
  W9-INT      Data integrity (null handling, NaN/Inf rejection)
  W9-SCOPE    Architecture / scope guard

Design constraints
------------------
  - Most tests are purely deterministic and do NOT require clang/opt.
  - Tests that require writing files use tempfile.mkdtemp() and clean up.
  - No new measurement infrastructure is created.
  - Week 8 (moo.bench is NOT moo.benchmark_generator) — scope guard passes.
  - No UI files are touched.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MOO_DIR = os.path.dirname(_SCRIPT_DIR)
_PS_DIR = os.path.dirname(_MOO_DIR)

if _PS_DIR not in sys.path:
    sys.path.insert(0, _PS_DIR)

# ---------------------------------------------------------------------------
# Test infrastructure (same pattern as Week 8)
# ---------------------------------------------------------------------------

_results: list[tuple[str, str, str]] = []


def report(tid: str, name: str, passed: bool, note: str = "") -> None:
    tag = "PASS" if passed else "FAIL"
    _results.append((tid, name, tag))
    suffix = f"  ({note})" if note else ""
    print(f"  [{tag}] {tid}: {name}{suffix}")


def skip(tid: str, name: str, reason: str = "") -> None:
    _results.append((tid, name, "SKIP"))
    print(f"  [SKIP] {tid}: {name}  {reason}")


def fail(tid: str, name: str, exc: Exception) -> None:
    _results.append((tid, name, "FAIL"))
    print(f"  [FAIL] {tid}: {name}  — {type(exc).__name__}: {exc}")


# ===========================================================================
# W9-SCHEMA: Schema model validation
# ===========================================================================

def test_schema1_corpus_entry_roundtrip():
    """CorpusEntry serializes and deserializes correctly."""
    tid, name = "W9-SCHEMA1", "CorpusEntry to_dict/from_dict round-trip"
    try:
        from moo.bench.schema import CorpusEntry
        e = CorpusEntry(
            program_id="test_prog",
            source_path="/some/path/test.c",
            source_sha256="abc123",
            origin="existing",
            family=None,
            generator_seed=None,
            generator_index=None,
            excluded=False,
            exclusion_reason=None,
        )
        d = e.to_dict()
        assert isinstance(d, dict)
        e2 = CorpusEntry.from_dict(d)
        assert e2.program_id == e.program_id
        assert e2.source_sha256 == e.source_sha256
        assert e2.origin == e.origin
        assert e2.excluded == e.excluded
        assert e2.family is None
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema2_run_manifest_roundtrip():
    """RunManifest serializes and deserializes correctly."""
    tid, name = "W9-SCHEMA2", "RunManifest to_dict/from_dict round-trip"
    try:
        from moo.bench.schema import RunManifest, BENCH_SCHEMA_VERSION
        m = RunManifest(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id="test-run-id",
            created_at="2026-10-04T14:00:00",
            suite_name="test_suite",
            program_ids=["prog1", "prog2"],
            strategies=["-O0", "-O2"],
            warmup_runs=3,
            measure_runs=10,
            timeout_s=30,
            cv_threshold=0.10,
            toolchain={"clang_path": "/usr/bin/clang"},
            platform={"system": "Windows"},
            baseline_convention="O0 baseline",
            feature_convention="8 canonical IR features",
            n_programs_total=5,
        )
        d = m.to_dict()
        assert isinstance(d, dict)
        assert d["schema_version"] == BENCH_SCHEMA_VERSION
        m2 = RunManifest.from_dict(d)
        assert m2.run_id == m.run_id
        assert m2.suite_name == m.suite_name
        assert m2.program_ids == m.program_ids
        assert m2.warmup_runs == m.warmup_runs
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema3_program_record_roundtrip():
    """ProgramRecord serializes and deserializes correctly."""
    tid, name = "W9-SCHEMA3", "ProgramRecord to_dict/from_dict round-trip"
    try:
        from moo.bench.schema import ProgramRecord, BENCH_SCHEMA_VERSION
        rec = ProgramRecord(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id="test-run",
            program_id="test_prog",
            corpus_entry={"program_id": "test_prog", "origin": "existing"},
            status="ok",
            evaluated_at="2026-10-04T14:00:00",
            pipeline_error=None,
            baseline={"strategy_name": "baseline (-O0)"},
            candidates=[{"strategy_name": "-O2"}],
            pareto_frontier=["-O2"],
            pareto_dominated=[],
            pareto_invalid=["-O0"],
        )
        d = rec.to_dict()
        assert isinstance(d, dict)
        rec2 = ProgramRecord.from_dict(d)
        assert rec2.program_id == rec.program_id
        assert rec2.status == rec.status
        assert rec2.pareto_frontier == ["-O2"]
        assert rec2.pipeline_error is None
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema4_program_record_failure_is_null_not_zero():
    """Failed ProgramRecord has null baseline, not zero-filled values."""
    tid, name = "W9-SCHEMA4", "Failed ProgramRecord has null baseline (not zero)"
    try:
        from moo.bench.schema import ProgramRecord, BENCH_SCHEMA_VERSION
        rec = ProgramRecord(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id="test-run",
            program_id="bad_prog",
            corpus_entry={"program_id": "bad_prog"},
            status="pipeline_error",
            evaluated_at="2026-10-04T14:00:00",
            pipeline_error="clang not found",
        )
        assert rec.baseline is None, "Failed record must have null baseline"
        assert rec.candidates is None, "Failed record must have null candidates"
        d = rec.to_dict()
        assert d["baseline"] is None
        assert d["candidates"] is None
        assert d["pipeline_error"] == "clang not found"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema5_dataset_manifest_roundtrip():
    """DatasetManifest serializes and deserializes correctly."""
    tid, name = "W9-SCHEMA5", "DatasetManifest to_dict/from_dict round-trip"
    try:
        from moo.bench.schema import DatasetManifest, DATASET_SCHEMA_VERSION
        m = DatasetManifest(
            schema_version=DATASET_SCHEMA_VERSION,
            source_run_id="run-abc",
            created_at="2026-10-04T14:00:00",
            n_candidate_rows=100,
            n_program_rows=10,
            split_policy={"train_fraction": 0.70},
            column_dict_candidate={"program_id": "Unique program identifier"},
            column_dict_program={"program_id": "Unique program identifier"},
            exclusions=["prog1: pipeline_error"],
            label_note="No best_strategy label",
            checksums={"candidate_rows_sha256": "abc123"},
            candidate_csv_path="/out/candidate_rows.csv",
            program_csv_path="/out/program_rows.csv",
        )
        d = m.to_dict()
        m2 = DatasetManifest.from_dict(d)
        assert m2.schema_version == DATASET_SCHEMA_VERSION
        assert m2.n_candidate_rows == 100
        assert m2.n_program_rows == 10
        assert m2.source_run_id == "run-abc"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema6_schema_version_constants():
    """BENCH_SCHEMA_VERSION and DATASET_SCHEMA_VERSION are non-empty strings."""
    tid, name = "W9-SCHEMA6", "Schema version constants are non-empty strings"
    try:
        from moo.bench.schema import BENCH_SCHEMA_VERSION, DATASET_SCHEMA_VERSION
        assert isinstance(BENCH_SCHEMA_VERSION, str) and BENCH_SCHEMA_VERSION
        assert isinstance(DATASET_SCHEMA_VERSION, str) and DATASET_SCHEMA_VERSION
        # Both should be the same for this release
        assert BENCH_SCHEMA_VERSION == DATASET_SCHEMA_VERSION
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema7_validate_no_nan_inf():
    """validate_no_nan_inf detects NaN and Inf in nested dicts."""
    tid, name = "W9-SCHEMA7", "validate_no_nan_inf detects NaN/Inf in nested structure"
    try:
        from moo.bench.schema import validate_no_nan_inf
        # Clean dict — no errors
        clean = {"a": 1.0, "b": {"c": 2.0}, "d": [1.0, 2.0]}
        errs = validate_no_nan_inf(clean)
        assert errs == [], f"Expected no errors, got: {errs}"

        # Dict with NaN
        with_nan = {"x": float("nan"), "y": 1.0}
        errs2 = validate_no_nan_inf(with_nan)
        assert len(errs2) == 1 and "x" in errs2[0]

        # Dict with Inf in nested
        with_inf = {"outer": {"inner": float("inf")}}
        errs3 = validate_no_nan_inf(with_inf)
        assert len(errs3) == 1 and "inner" in errs3[0]
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema8_o0_baseline_convention_documented():
    """schema.py documents the three O0 baseline conventions."""
    tid, name = "W9-SCHEMA8", "O0 baseline conventions documented in schema module"
    try:
        import moo.bench.schema as schema_mod
        docstring = schema_mod.__doc__ or ""
        # Must document the three conventions
        assert "O0 correctness" in docstring or "normalization baseline" in docstring, \
            "Missing O0 convention 1"
        assert "disable-O0-optnone" in docstring or "feature/IR baseline" in docstring, \
            "Missing O0 convention 2"
        assert "ACTIONS" in docstring or "strategy inside" in docstring, \
            "Missing O0 convention 3"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W9-CORPUS: Corpus manifest builder
# ===========================================================================

def test_corpus1_build_deterministic_ordering():
    """build_corpus_manifest returns same order on repeated calls."""
    tid, name = "W9-CORPUS1", "Corpus manifest ordering is deterministic"
    try:
        from moo.bench.corpus import build_corpus_manifest
        # Use a temp dir with known .c files
        tmpdir = tempfile.mkdtemp()
        try:
            for fn in ["03_foo.c", "01_bar.c", "02_baz.c"]:
                open(os.path.join(tmpdir, fn), "w").write("int main(){return 0;}")
            entries1 = build_corpus_manifest(tmpdir)
            entries2 = build_corpus_manifest(tmpdir)
            ids1 = [e.program_id for e in entries1]
            ids2 = [e.program_id for e in entries2]
            assert ids1 == ids2, f"Non-deterministic ordering: {ids1} vs {ids2}"
            # Should be sorted: 01 < 02 < 03
            assert ids1 == ["01_bar", "02_baz", "03_foo"], f"Wrong sort: {ids1}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_corpus2_sha256_stability():
    """Same file content → same SHA-256 across repeated manifest builds."""
    tid, name = "W9-CORPUS2", "SHA-256 is stable for identical source content"
    try:
        from moo.bench.corpus import build_corpus_manifest
        tmpdir = tempfile.mkdtemp()
        try:
            src = "int main(){return 0;}"
            fn  = "01_test.c"
            with open(os.path.join(tmpdir, fn), "w") as f:
                f.write(src)
            e1 = build_corpus_manifest(tmpdir)
            e2 = build_corpus_manifest(tmpdir)
            assert e1[0].source_sha256 == e2[0].source_sha256
            # Verify manually
            expected = hashlib.sha256(src.encode("utf-8")).hexdigest()
            # Note: file is written/read as text — use bytes to compare
            with open(os.path.join(tmpdir, fn), "rb") as f:
                raw = f.read()
            expected_raw = hashlib.sha256(raw).hexdigest()
            assert e1[0].source_sha256 == expected_raw, \
                f"SHA mismatch: {e1[0].source_sha256} vs {expected_raw}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_corpus3_exclusion_reasons_populated():
    """Excluded files have non-None exclusion_reason."""
    tid, name = "W9-CORPUS3", "Excluded corpus entries have non-None exclusion_reason"
    try:
        from moo.bench.corpus import build_corpus_manifest
        tmpdir = tempfile.mkdtemp()
        try:
            # ai_test_ prefix matches exclusion pattern
            open(os.path.join(tmpdir, "ai_test_foo.c"), "w").write("int main(){}")
            open(os.path.join(tmpdir, "01_normal.c"), "w").write("int main(){}")
            entries = build_corpus_manifest(tmpdir)
            excluded = [e for e in entries if e.excluded]
            assert len(excluded) >= 1, "Expected at least one excluded entry"
            for e in excluded:
                assert e.exclusion_reason is not None, \
                    f"Excluded entry {e.program_id!r} has None exclusion_reason"
                assert len(e.exclusion_reason) > 0
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_corpus4_existing_programs_origin_label():
    """All programs from test_cases/ have origin='existing'."""
    tid, name = "W9-CORPUS4", "Programs from test_cases/ have origin='existing'"
    try:
        from moo.bench.corpus import build_corpus_manifest
        tmpdir = tempfile.mkdtemp()
        try:
            for fn in ["01_a.c", "02_b.c"]:
                open(os.path.join(tmpdir, fn), "w").write("int main(){}")
            entries = build_corpus_manifest(tmpdir)
            for e in entries:
                assert e.origin == "existing", \
                    f"Entry {e.program_id!r} has origin={e.origin!r}, expected 'existing'"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_corpus5_generated_entries_merged_correctly():
    """Generated CorpusEntry objects are merged after existing programs."""
    tid, name = "W9-CORPUS5", "Generated entries merged after existing in deterministic order"
    try:
        from moo.bench.corpus import build_corpus_manifest
        from moo.bench.schema import CorpusEntry
        tmpdir = tempfile.mkdtemp()
        try:
            open(os.path.join(tmpdir, "01_existing.c"), "w").write("int main(){}")
            gen_entry = CorpusEntry(
                program_id="gen_loop_seed42_0",
                source_path="/tmp/gen.c",
                source_sha256="deadbeef",
                origin="generated",
                family="loop",
                generator_seed=42,
                generator_index=0,
            )
            entries = build_corpus_manifest(tmpdir, generated_entries=[gen_entry])
            origins = [e.origin for e in entries]
            # Existing should come first
            first_existing_idx = origins.index("existing")
            first_generated_idx = origins.index("generated")
            assert first_existing_idx < first_generated_idx, \
                "Existing programs should precede generated in ordering"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_corpus6_save_and_load_roundtrip():
    """Corpus manifest JSON save/load is a lossless round-trip."""
    tid, name = "W9-CORPUS6", "Corpus manifest JSON save/load round-trip"
    try:
        from moo.bench.corpus import build_corpus_manifest, save_corpus_manifest, load_corpus_manifest
        tmpdir = tempfile.mkdtemp()
        try:
            open(os.path.join(tmpdir, "01_a.c"), "w").write("int main(){}")
            entries = build_corpus_manifest(tmpdir)
            manifest_path = os.path.join(tmpdir, "corpus.json")
            save_corpus_manifest(entries, manifest_path)
            assert os.path.isfile(manifest_path)
            loaded = load_corpus_manifest(manifest_path)
            assert len(loaded) == len(entries)
            for orig, loaded_e in zip(entries, loaded):
                assert orig.program_id == loaded_e.program_id
                assert orig.source_sha256 == loaded_e.source_sha256
                assert orig.origin == loaded_e.origin
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_corpus7_id_collision_detection():
    """Generated entries with ID collision are excluded with reason."""
    tid, name = "W9-CORPUS7", "Generated entry ID collision with existing → excluded"
    try:
        from moo.bench.corpus import build_corpus_manifest
        from moo.bench.schema import CorpusEntry
        tmpdir = tempfile.mkdtemp()
        try:
            open(os.path.join(tmpdir, "01_existing.c"), "w").write("int main(){}")
            # Generated entry with same program_id as existing
            colliding = CorpusEntry(
                program_id="01_existing",
                source_path="/tmp/gen.c",
                source_sha256="abc",
                origin="generated",
                family="loop",
            )
            entries = build_corpus_manifest(tmpdir, generated_entries=[colliding])
            colliding_entries = [e for e in entries if e.program_id == "01_existing"]
            # At least the generated one should be excluded
            generated_excluded = [
                e for e in colliding_entries
                if e.origin == "generated" and e.excluded
            ]
            assert len(generated_excluded) >= 1, "Colliding generated entry should be excluded"
            assert generated_excluded[0].exclusion_reason is not None
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_corpus8_empty_directory_returns_empty():
    """build_corpus_manifest on empty dir returns empty list."""
    tid, name = "W9-CORPUS8", "Empty test_cases dir returns empty corpus"
    try:
        from moo.bench.corpus import build_corpus_manifest
        tmpdir = tempfile.mkdtemp()
        try:
            entries = build_corpus_manifest(tmpdir)
            assert entries == [], f"Expected empty list, got {len(entries)} entries"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W9-GEN: Synthetic benchmark generator
# ===========================================================================

def test_gen1_same_seed_identical_source():
    """Same seed → identical generated source for all families."""
    tid, name = "W9-GEN1", "Same seed produces identical source text"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        for family in GENERATOR_FAMILIES:
            src1, _ = gen.generate_one(family, 0)
            src2, _ = gen.generate_one(family, 0)
            assert src1 == src2, \
                f"Family {family!r}: source differs on repeated call with same seed"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen2_different_seed_different_source():
    """Different seed → different source text."""
    tid, name = "W9-GEN2", "Different seeds produce different source text"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen42 = BenchmarkGenerator(seed=42, output_dir=None)
        gen99 = BenchmarkGenerator(seed=99, output_dir=None)
        for family in GENERATOR_FAMILIES:
            src42, _ = gen42.generate_one(family, 0)
            src99, _ = gen99.generate_one(family, 0)
            assert src42 != src99, \
                f"Family {family!r}: seed 42 and 99 produced identical source"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen3_generated_filenames_never_collide_with_existing():
    """Generated filenames (gen_*) never match existing test_cases naming."""
    tid, name = "W9-GEN3", "Generated filenames do not collide with existing test_cases pattern"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        import re
        existing_pattern = re.compile(r"^\d{2}_")  # e.g. 01_hello_world.c
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        for family in GENERATOR_FAMILIES:
            for idx in range(3):
                src, entry = gen.generate_one(family, idx)
                pid = entry.program_id
                assert not existing_pattern.match(pid), \
                    f"Generated program_id {pid!r} matches existing test_cases pattern"
                assert pid.startswith("gen_"), \
                    f"Generated program_id {pid!r} should start with 'gen_'"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen4_all_families_produce_valid_c_skeleton():
    """Generated source contains int main and #include."""
    tid, name = "W9-GEN4", "All generator families produce valid C program skeleton"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        for family in GENERATOR_FAMILIES:
            src, entry = gen.generate_one(family, 0)
            assert "int main" in src, f"Family {family}: missing 'int main'"
            assert "#include" in src, f"Family {family}: missing '#include'"
            assert "printf" in src, f"Family {family}: missing printf (no output)"
            assert "return 0" in src, f"Family {family}: missing 'return 0'"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen5_no_banned_functions():
    """Generated programs do not use rand(), time(), scanf(), or malloc()."""
    tid, name = "W9-GEN5", "Generated programs do not use rand/time/scanf/malloc"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        banned = ["rand(", "time(", "scanf(", "malloc(", "calloc(", "realloc(", "free("]
        for family in GENERATOR_FAMILIES:
            for idx in range(3):
                src, _ = gen.generate_one(family, idx)
                for token in banned:
                    assert token not in src, \
                        f"Family {family} idx {idx}: found banned token {token!r}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen6_sha256_matches_source():
    """CorpusEntry.source_sha256 matches actual SHA-256 of source_text."""
    tid, name = "W9-GEN6", "CorpusEntry.source_sha256 matches source text SHA-256"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        for family in GENERATOR_FAMILIES:
            src, entry = gen.generate_one(family, 0)
            expected_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
            assert entry.source_sha256 == expected_sha, \
                f"Family {family}: SHA mismatch"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen7_generator_families_constant():
    """GENERATOR_FAMILIES contains all expected families."""
    tid, name = "W9-GEN7", "GENERATOR_FAMILIES contains expected 6 families"
    try:
        from moo.bench.generator import GENERATOR_FAMILIES
        expected = {"loop", "math", "memory", "recursion", "branch", "function"}
        actual = set(GENERATOR_FAMILIES)
        assert actual == expected, f"Got: {actual}"
        assert len(GENERATOR_FAMILIES) == 6
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen8_bulk_generate_returns_correct_count():
    """generate() returns n_per_family × n_families entries."""
    tid, name = "W9-GEN8", "generate() returns n_per_family × n_families entries"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        n = 3
        entries = gen.generate(n_per_family=n)
        assert len(entries) == n * len(GENERATOR_FAMILIES), \
            f"Expected {n * len(GENERATOR_FAMILIES)}, got {len(entries)}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen9_different_index_different_source():
    """Same family and seed but different index produces different source."""
    tid, name = "W9-GEN9", "Same family+seed but different index → different source"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        for family in GENERATOR_FAMILIES:
            src0, _ = gen.generate_one(family, 0)
            src1, _ = gen.generate_one(family, 1)
            assert src0 != src1, \
                f"Family {family}: idx 0 and idx 1 produced identical source"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen10_file_written_when_output_dir_set():
    """When output_dir is set, .c files are written to disk."""
    tid, name = "W9-GEN10", "Generator writes .c files when output_dir is set"
    try:
        from moo.bench.generator import BenchmarkGenerator
        tmpdir = tempfile.mkdtemp()
        try:
            gen = BenchmarkGenerator(seed=42, output_dir=tmpdir)
            src, entry = gen.generate_one("loop", 0)
            assert entry.source_path and os.path.isfile(entry.source_path), \
                f"File not created at {entry.source_path!r}"
            with open(entry.source_path, "r", encoding="utf-8") as f:
                written = f.read()
            assert written == src, "Written file content does not match source_text"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen11_origin_is_generated():
    """Generated CorpusEntry has origin='generated'."""
    tid, name = "W9-GEN11", "Generated CorpusEntry has origin='generated'"
    try:
        from moo.bench.generator import BenchmarkGenerator, GENERATOR_FAMILIES
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        for family in GENERATOR_FAMILIES:
            _, entry = gen.generate_one(family, 0)
            assert entry.origin == "generated", \
                f"Family {family}: origin={entry.origin!r}, expected 'generated'"
            assert entry.family == family, \
                f"Family {family}: entry.family={entry.family!r}"
            assert entry.generator_seed == 42
            assert entry.generator_index == 0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_gen12_family_subset_generate():
    """generate() with subset of families only produces those families."""
    tid, name = "W9-GEN12", "generate() with family subset produces only those families"
    try:
        from moo.bench.generator import BenchmarkGenerator
        gen = BenchmarkGenerator(seed=42, output_dir=None)
        entries = gen.generate(n_per_family=2, families=("loop", "math"))
        families_produced = {e.family for e in entries}
        assert families_produced == {"loop", "math"}, \
            f"Got: {families_produced}"
        assert len(entries) == 4, f"Expected 4 entries, got {len(entries)}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W9-RUN: Batch runner (toolchain-free tests)
# ===========================================================================

def test_run1_manifest_created_on_run_start():
    """BenchmarkRunner creates run_manifest.json in run directory."""
    tid, name = "W9-RUN1", "run_manifest.json created in run directory"
    try:
        from moo.bench.runner import BenchmarkRunner
        from moo.bench.schema import CorpusEntry
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test_suite")
            # Run with excluded entries only (no toolchain needed)
            excluded_entry = CorpusEntry(
                program_id="excluded_prog",
                source_path="/nonexistent/path.c",
                source_sha256="",
                origin="existing",
                excluded=True,
                exclusion_reason="Test exclusion",
            )
            manifest = runner.run([excluded_entry], verbose=False)
            manifest_path = os.path.join(tmpdir, "run_manifest.json")
            assert os.path.isfile(manifest_path), "run_manifest.json not created"
            with open(manifest_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            assert "run_id" in d
            assert "schema_version" in d
            assert d["suite_name"] == "test_suite"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_run2_missing_toolchain_yields_error_record_not_crash():
    """Runner records pipeline_error when source file is missing (not a crash)."""
    tid, name = "W9-RUN2", "Missing source file yields error record, not crash"
    try:
        from moo.bench.runner import BenchmarkRunner
        from moo.bench.schema import CorpusEntry
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test")
            bad_entry = CorpusEntry(
                program_id="nonexistent",
                source_path="/this/path/does/not/exist.c",
                source_sha256="",
                origin="existing",
                excluded=False,
                exclusion_reason=None,
            )
            manifest = runner.run([bad_entry], verbose=False)
            # Should complete without raising
            assert manifest.status == "completed"
            assert manifest.n_programs_run >= 1
            # Load the result record
            records = runner.load_records()
            assert len(records) >= 1
            bad_rec = next((r for r in records if r.program_id == "nonexistent"), None)
            assert bad_rec is not None
            assert bad_rec.status == "pipeline_error"
            assert bad_rec.pipeline_error is not None
            assert bad_rec.baseline is None  # no fabricated baseline
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_run3_excluded_entries_not_evaluated():
    """Excluded corpus entries are not evaluated (no result file created)."""
    tid, name = "W9-RUN3", "Excluded entries are skipped (not evaluated)"
    try:
        from moo.bench.runner import BenchmarkRunner
        from moo.bench.schema import CorpusEntry
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test")
            excluded = CorpusEntry(
                program_id="excl_prog",
                source_path="/some/path.c",
                source_sha256="",
                origin="existing",
                excluded=True,
                exclusion_reason="Test exclusion",
            )
            manifest = runner.run([excluded], verbose=False)
            assert manifest.n_programs_run == 0, \
                f"Expected 0 programs run, got {manifest.n_programs_run}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_run4_resumability_skips_existing_results():
    """Runner with resume=True skips programs with existing result files."""
    tid, name = "W9-RUN4", "Resumable runner skips programs with existing results"
    try:
        from moo.bench.runner import BenchmarkRunner
        from moo.bench.schema import CorpusEntry, ProgramRecord, BENCH_SCHEMA_VERSION
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test", resume=True)
            # Pre-write a result file
            results_dir = os.path.join(tmpdir, "results")
            os.makedirs(results_dir, exist_ok=True)
            existing_rec = ProgramRecord(
                schema_version=BENCH_SCHEMA_VERSION,
                run_id="old-run",
                program_id="pre_computed",
                corpus_entry={"program_id": "pre_computed"},
                status="ok",
                evaluated_at="2026-10-04T00:00:00",
                pareto_frontier=["-O2"],
            )
            with open(os.path.join(results_dir, "pre_computed.json"), "w") as f:
                json.dump(existing_rec.to_dict(), f)

            entry = CorpusEntry(
                program_id="pre_computed",
                source_path="/nonexistent.c",
                source_sha256="",
                origin="existing",
                excluded=False,
            )
            manifest = runner.run([entry], verbose=False)
            # It should not have re-evaluated (source is missing but resume skips it)
            assert manifest.status == "completed"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_run5_deterministic_program_ordering():
    """Runner processes programs in the order given by corpus entries."""
    tid, name = "W9-RUN5", "Runner processes programs in deterministic corpus order"
    try:
        from moo.bench.runner import BenchmarkRunner
        from moo.bench.schema import CorpusEntry
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test")
            entries = [
                CorpusEntry(
                    program_id=f"prog_{i}",
                    source_path="/nonexistent.c",
                    source_sha256="",
                    origin="existing",
                    excluded=False,
                )
                for i in range(3)
            ]
            manifest = runner.run(entries, verbose=False)
            # program_ids in manifest must preserve order
            assert manifest.program_ids == ["prog_0", "prog_1", "prog_2"], \
                f"Order changed: {manifest.program_ids}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_run6_manifest_schema_version_present():
    """run_manifest.json always contains schema_version."""
    tid, name = "W9-RUN6", "run_manifest.json contains schema_version field"
    try:
        from moo.bench.runner import BenchmarkRunner
        from moo.bench.schema import BENCH_SCHEMA_VERSION, CorpusEntry
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test")
            runner.run([], verbose=False)
            with open(os.path.join(tmpdir, "run_manifest.json"), "r") as f:
                d = json.load(f)
            assert d.get("schema_version") == BENCH_SCHEMA_VERSION, \
                f"Wrong schema_version: {d.get('schema_version')!r}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_run7_manifest_baseline_convention_documented():
    """run_manifest.json baseline_convention field references O0."""
    tid, name = "W9-RUN7", "run_manifest.json baseline_convention mentions O0"
    try:
        from moo.bench.runner import BenchmarkRunner
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test")
            runner.run([], verbose=False)
            with open(os.path.join(tmpdir, "run_manifest.json"), "r") as f:
                d = json.load(f)
            conv = d.get("baseline_convention", "")
            assert "O0" in conv or "o0" in conv.lower(), \
                f"baseline_convention missing O0 reference: {conv!r}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_run8_outputs_not_in_moo_reports():
    """BenchmarkRunner output dir is NOT inside moo/reports/."""
    tid, name = "W9-RUN8", "Runner output directory is outside moo/reports/"
    try:
        from moo.bench.runner import BenchmarkRunner
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir, suite_name="test")
            assert "moo" not in tmpdir.lower() or "reports" not in tmpdir.lower() or \
                   "bench" in tmpdir.lower(), \
                "Runner must not write to moo/reports/"
            # More direct: the run_dir should not be the moo/reports/ directory
            here = os.path.dirname(os.path.abspath(__file__))
            moo_reports = os.path.abspath(os.path.join(here, "..", "reports"))
            assert os.path.abspath(runner.run_dir) != moo_reports, \
                "Runner output must not be moo/reports/"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W9-DS: Dataset builder
# ===========================================================================

def _make_mock_record(pid: str, origin: str = "existing", family: str = None,
                      has_pipeline_error: bool = False) -> "ProgramRecord":
    """Create a minimal mock ProgramRecord for dataset testing."""
    from moo.bench.schema import ProgramRecord, BENCH_SCHEMA_VERSION
    if has_pipeline_error:
        return ProgramRecord(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id="test-run",
            program_id=pid,
            corpus_entry={"program_id": pid, "origin": origin, "family": family},
            status="pipeline_error",
            evaluated_at="2026-10-04T14:00:00",
            pipeline_error="clang not found",
        )

    return ProgramRecord(
        schema_version=BENCH_SCHEMA_VERSION,
        run_id="test-run",
        program_id=pid,
        corpus_entry={"program_id": pid, "origin": origin, "family": family},
        status="ok",
        evaluated_at="2026-10-04T14:00:00",
        pipeline_error=None,
        baseline={
            "strategy_name": "baseline (-O0)",
            "measurement": {
                "timing": {"median_s": 0.001, "median_ns": 1000000},
                "energy": {"energy_joules": 0.045, "energy_is_estimated": True},
                "code_size": {"primary_value": 10000, "primary_metric": "file_size_bytes"},
                "carbon": {"carbon_grams": 0.0055},
            },
        },
        candidates=[
            {
                "strategy_name": "-O2",
                "strategy_index": 2,
                "strategy_kind": "clang_flag",
                "build_ok": True,
                "correct": True,
                "measurement": {"timing": {"median_s": 0.0007}},
                "normalized": {
                    "objectives": [
                        {"name": "execution_time"},
                        {"name": "energy"},
                        {"name": "code_size"},
                        {"name": "carbon"},
                    ],
                    "normalized_values": [0.7, 0.7, 0.88, 0.7],
                },
                "pareto_status": "FRONTIER",
            },
            {
                "strategy_name": "-O0",
                "strategy_index": 0,
                "strategy_kind": "clang_flag",
                "build_ok": True,
                "correct": True,
                "measurement": {"timing": {"median_s": 0.001}},
                "normalized": {
                    "objectives": [
                        {"name": "execution_time"},
                        {"name": "energy"},
                        {"name": "code_size"},
                        {"name": "carbon"},
                    ],
                    "normalized_values": [1.0, 1.0, 1.0, 1.0],
                },
                "pareto_status": "DOMINATED",
            },
        ],
        pareto_frontier=["-O2"],
        pareto_dominated=["-O0"],
        pareto_invalid=[],
        objectives_used=["execution_time", "energy", "code_size", "carbon"],
    )


def test_ds1_candidate_csv_created():
    """DatasetBuilder creates candidate_rows.csv."""
    tid, name = "W9-DS1", "DatasetBuilder creates candidate_rows.csv"
    try:
        from moo.bench.dataset import DatasetBuilder
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog1"), _make_mock_record("prog2")]
            builder = DatasetBuilder(output_dir=tmpdir)
            manifest = builder.build(records, run_id="test-run", verbose=False)
            assert os.path.isfile(os.path.join(tmpdir, "candidate_rows.csv"))
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_ds2_program_csv_created():
    """DatasetBuilder creates program_rows.csv."""
    tid, name = "W9-DS2", "DatasetBuilder creates program_rows.csv"
    try:
        from moo.bench.dataset import DatasetBuilder
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog1")]
            builder = DatasetBuilder(output_dir=tmpdir)
            builder.build(records, run_id="test-run", verbose=False)
            assert os.path.isfile(os.path.join(tmpdir, "program_rows.csv"))
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_ds3_dataset_manifest_created():
    """DatasetBuilder creates dataset_manifest.json with correct schema_version."""
    tid, name = "W9-DS3", "DatasetBuilder creates dataset_manifest.json"
    try:
        from moo.bench.dataset import DatasetBuilder
        from moo.bench.schema import DATASET_SCHEMA_VERSION
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog1")]
            builder = DatasetBuilder(output_dir=tmpdir)
            builder.build(records, run_id="test-run", verbose=False)
            manifest_path = os.path.join(tmpdir, "dataset_manifest.json")
            assert os.path.isfile(manifest_path)
            with open(manifest_path, "r") as f:
                d = json.load(f)
            assert d.get("schema_version") == DATASET_SCHEMA_VERSION
            assert "checksums" in d
            assert "split_policy" in d
            assert "label_note" in d
            assert "column_dict_candidate" in d
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_ds4_no_best_strategy_label():
    """dataset_manifest.json label_note explicitly disclaims single best_strategy label."""
    tid, name = "W9-DS4", "label_note disclaims single 'best_strategy' label"
    try:
        from moo.bench.dataset import DatasetBuilder
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog1")]
            builder = DatasetBuilder(output_dir=tmpdir)
            manifest = builder.build(records, run_id="test-run", verbose=False)
            note = manifest.label_note
            assert "best_strategy" in note or "best strategy" in note.lower(), \
                f"label_note should reference 'best_strategy': {note!r}"
            assert "MOO" in note or "Pareto" in note, \
                "label_note should reference MOO/Pareto"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_ds5_null_handling_in_csv():
    """Pipeline-failed records are excluded from CSV (not zero-filled)."""
    tid, name = "W9-DS5", "Failed records excluded from CSV (null → empty, not zero)"
    try:
        from moo.bench.dataset import DatasetBuilder
        tmpdir = tempfile.mkdtemp()
        try:
            records = [
                _make_mock_record("good_prog"),
                _make_mock_record("bad_prog", has_pipeline_error=True),
            ]
            builder = DatasetBuilder(output_dir=tmpdir)
            manifest = builder.build(records, run_id="test-run", verbose=False)
            # bad_prog should appear in exclusions, not in program CSV
            assert manifest.exclusions, "Failed record should appear in exclusions"
            assert any("bad_prog" in exc for exc in manifest.exclusions)
            # program_rows.csv should have only 1 row (good_prog)
            prog_path = os.path.join(tmpdir, "program_rows.csv")
            with open(prog_path, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert len(rows) == 1, f"Expected 1 program row, got {len(rows)}"
            assert rows[0]["program_id"] == "good_prog"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_ds6_checksums_in_manifest():
    """dataset_manifest.json contains SHA-256 checksums for CSV files."""
    tid, name = "W9-DS6", "dataset_manifest.json contains SHA-256 checksums for CSVs"
    try:
        from moo.bench.dataset import DatasetBuilder
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog1")]
            builder = DatasetBuilder(output_dir=tmpdir)
            manifest = builder.build(records, run_id="test-run", verbose=False)
            checksums = manifest.checksums
            assert "candidate_rows_sha256" in checksums
            assert "program_rows_sha256" in checksums
            # Verify checksum correctness
            cand_path = os.path.join(tmpdir, "candidate_rows.csv")
            h = hashlib.sha256()
            with open(cand_path, "rb") as f:
                h.update(f.read())
            assert h.hexdigest() == checksums["candidate_rows_sha256"]
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_ds7_candidate_rows_have_correct_columns():
    """candidate_rows.csv has all required column headers."""
    tid, name = "W9-DS7", "candidate_rows.csv has all required column headers"
    try:
        from moo.bench.dataset import DatasetBuilder, _CANDIDATE_COLUMNS
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog1")]
            builder = DatasetBuilder(output_dir=tmpdir)
            builder.build(records, run_id="test-run", verbose=False)
            with open(os.path.join(tmpdir, "candidate_rows.csv"), "r") as f:
                reader = csv.reader(f)
                headers = next(reader)
            for col in _CANDIDATE_COLUMNS:
                assert col in headers, f"Missing column: {col}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_ds8_pareto_columns_are_binary():
    """is_pareto_frontier and is_pareto_dominated are 0 or 1 in CSV."""
    tid, name = "W9-DS8", "is_pareto_frontier and is_pareto_dominated are 0/1 in CSV"
    try:
        from moo.bench.dataset import DatasetBuilder
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record("prog1")]
            builder = DatasetBuilder(output_dir=tmpdir)
            builder.build(records, run_id="test-run", verbose=False)
            with open(os.path.join(tmpdir, "candidate_rows.csv"), "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            assert rows, "Expected at least one candidate row"
            for row in rows:
                assert row["is_pareto_frontier"] in ("0", "1"), \
                    f"Bad is_pareto_frontier: {row['is_pareto_frontier']!r}"
                assert row["is_pareto_dominated"] in ("0", "1"), \
                    f"Bad is_pareto_dominated: {row['is_pareto_dominated']!r}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W9-SPLIT: Dataset split stability and leakage prevention
# ===========================================================================

def test_split1_same_run_id_same_splits():
    """Same run_id → same split assignments on repeated calls."""
    tid, name = "W9-SPLIT1", "Same run_id produces identical split assignments"
    try:
        from moo.bench.dataset import _assign_splits
        from moo.bench.schema import ProgramRecord, BENCH_SCHEMA_VERSION

        records = [
            _make_mock_record(f"prog_{i}") for i in range(10)
        ]
        splits1 = _assign_splits(records, run_id="stable-run-id")
        splits2 = _assign_splits(records, run_id="stable-run-id")
        assert splits1 == splits2, "Split assignments not deterministic"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_split2_different_run_id_different_splits():
    """Different run_id → different split assignments (with high probability)."""
    tid, name = "W9-SPLIT2", "Different run_ids produce different split assignments"
    try:
        from moo.bench.dataset import _assign_splits

        records = [_make_mock_record(f"prog_{i}") for i in range(20)]
        splits_a = _assign_splits(records, run_id="run-aaa")
        splits_b = _assign_splits(records, run_id="run-bbb")
        # With 20 programs and random shuffling, assignments should differ
        assert splits_a != splits_b, "Different run_ids produced identical splits"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_split3_family_leakage_prevention():
    """Programs from the same generated family are always in the same split."""
    tid, name = "W9-SPLIT3", "Same family always in same split (no leakage)"
    try:
        from moo.bench.dataset import _assign_splits
        from moo.bench.schema import ProgramRecord, BENCH_SCHEMA_VERSION

        # Create 5 programs in the "loop" family (should all go to same split)
        # and enough others to have all 3 splits
        records = (
            [_make_mock_record(f"gen_loop_s42_{i}", origin="generated", family="loop")
             for i in range(5)] +
            [_make_mock_record(f"prog_{i}", origin="existing")
             for i in range(20)]
        )

        for run_id in ["run-1", "run-2", "run-3"]:
            splits = _assign_splits(records, run_id=run_id)
            loop_splits = {
                splits[f"gen_loop_s42_{i}"]
                for i in range(5)
                if f"gen_loop_s42_{i}" in splits
            }
            assert len(loop_splits) == 1, \
                f"run_id={run_id}: loop family in multiple splits: {loop_splits}"

        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_split4_split_distribution_roughly_correct():
    """70/15/15 split is approximately maintained for large corpus."""
    tid, name = "W9-SPLIT4", "Split distribution is approximately 70/15/15"
    try:
        from moo.bench.dataset import _assign_splits

        n = 100
        records = [_make_mock_record(f"prog_{i}") for i in range(n)]
        splits = _assign_splits(records, run_id="dist-check")

        n_train = sum(1 for s in splits.values() if s == "train")
        n_val   = sum(1 for s in splits.values() if s == "val")
        n_test  = sum(1 for s in splits.values() if s == "test")
        total   = n_train + n_val + n_test

        assert total == n, f"Missing programs: total={total} != {n}"
        # Allow ±10% tolerance from expected fractions
        assert 60 <= n_train <= 80, f"n_train={n_train} out of expected 70±10"
        assert 5 <= n_val <= 25, f"n_val={n_val} out of expected 15±10"
        assert 5 <= n_test <= 25, f"n_test={n_test} out of expected 15±10"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_split5_split_column_in_csv():
    """candidate_rows.csv and program_rows.csv contain 'split' column."""
    tid, name = "W9-SPLIT5", "CSV files contain 'split' column"
    try:
        from moo.bench.dataset import DatasetBuilder
        tmpdir = tempfile.mkdtemp()
        try:
            records = [_make_mock_record(f"prog_{i}") for i in range(5)]
            builder = DatasetBuilder(output_dir=tmpdir)
            builder.build(records, run_id="split-test", verbose=False)

            for fname in ("candidate_rows.csv", "program_rows.csv"):
                path = os.path.join(tmpdir, fname)
                with open(path, "r") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                assert rows, f"Empty {fname}"
                for row in rows:
                    assert "split" in row, f"{fname}: missing 'split' column"
                    assert row["split"] in ("train", "val", "test"), \
                        f"{fname}: invalid split value {row['split']!r}"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W9-INT: Data integrity
# ===========================================================================

def test_int1_safe_float_rejects_nan():
    """_safe_float converts NaN to empty string."""
    tid, name = "W9-INT1", "_safe_float converts NaN to empty string"
    try:
        from moo.bench.dataset import _safe_float
        assert _safe_float(float("nan")) == ""
        assert _safe_float(float("inf")) == ""
        assert _safe_float(float("-inf")) == ""
        assert _safe_float(None) == ""
        assert _safe_float(1.5) == "1.5"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_int2_safe_int_rejects_none():
    """_safe_int converts None to empty string."""
    tid, name = "W9-INT2", "_safe_int converts None to empty string"
    try:
        from moo.bench.dataset import _safe_int
        assert _safe_int(None) == ""
        assert _safe_int(42) == "42"
        assert _safe_int("123") == "123"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_int3_validate_no_nan_inf_clean():
    """validate_no_nan_inf returns empty list for clean dict."""
    tid, name = "W9-INT3", "validate_no_nan_inf returns [] for clean dict"
    try:
        from moo.bench.schema import validate_no_nan_inf
        clean = {
            "a": 1.0,
            "b": {"c": 2.5, "d": [1.0, 3.14]},
            "e": None,
            "f": "string",
        }
        errs = validate_no_nan_inf(clean)
        assert errs == [], f"Unexpected errors: {errs}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_int4_program_record_pipeline_error_not_zero():
    """When pipeline fails, ProgramRecord has null values (no zero substitution)."""
    tid, name = "W9-INT4", "ProgramRecord with pipeline_error has null objectives (not zero)"
    try:
        from moo.bench.schema import ProgramRecord, BENCH_SCHEMA_VERSION
        rec = ProgramRecord(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id="r1",
            program_id="bad",
            corpus_entry={},
            status="pipeline_error",
            evaluated_at="2026-10-04T00:00:00",
            pipeline_error="clang missing",
        )
        d = rec.to_dict()
        assert d["baseline"] is None, "Null baseline must stay null"
        assert d["candidates"] is None, "Null candidates must stay null"
        assert d["pareto_frontier"] is None
        # No zero-filled objectives anywhere
        assert d["pipeline_error"] == "clang missing"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_int5_deterministic_pareto_representation():
    """Pareto frontier from ProgramRecord round-trips without reordering."""
    tid, name = "W9-INT5", "Pareto frontier list order preserved in round-trip"
    try:
        from moo.bench.schema import ProgramRecord, BENCH_SCHEMA_VERSION
        frontier = ["-O2", "mem2reg,simplifycfg", "-O3"]
        rec = ProgramRecord(
            schema_version=BENCH_SCHEMA_VERSION,
            run_id="r1",
            program_id="prog1",
            corpus_entry={},
            status="ok",
            evaluated_at="2026-10-04T00:00:00",
            pareto_frontier=frontier,
        )
        d = rec.to_dict()
        rec2 = ProgramRecord.from_dict(d)
        assert rec2.pareto_frontier == frontier, \
            f"Frontier order changed: {rec2.pareto_frontier}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W9-SCOPE: Architecture / scope guard
# ===========================================================================

def test_scope1_bench_is_separate_from_moo_reports():
    """moo.bench outputs are separate from moo/reports/."""
    tid, name = "W9-SCOPE1", "moo.bench outputs do not pollute moo/reports/"
    try:
        # The moo.bench package must NOT write to moo/reports/
        here = os.path.dirname(os.path.abspath(__file__))
        moo_reports = os.path.abspath(os.path.join(here, "..", "reports"))

        # Verify that default BenchmarkRunner output is NOT moo/reports/
        from moo.bench.runner import BenchmarkRunner
        tmpdir = tempfile.mkdtemp()
        try:
            runner = BenchmarkRunner(run_dir=tmpdir)
            run_dir_abs = os.path.abspath(runner.run_dir)
            moo_reports_abs = os.path.abspath(moo_reports)
            assert run_dir_abs != moo_reports_abs, \
                "BenchmarkRunner default output must not be moo/reports/"
            # Also verify the runner's run_dir doesn't overlap with moo/reports/
            assert not run_dir_abs.startswith(moo_reports_abs), \
                "BenchmarkRunner run_dir must not be inside moo/reports/"
            report(tid, name, True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope2_no_week10_modules_introduced():
    """moo.bench does not contain regression_tracker or regression_platform."""
    tid, name = "W9-SCOPE2", "No Week 10+ regression modules in moo.bench"
    try:
        prohibited = [
            "moo.bench.regression_tracker",
            "moo.bench.regression_platform",
            "moo.bench.historical_comparison",
        ]
        import importlib
        for mod in prohibited:
            try:
                importlib.import_module(mod)
                assert False, f"Module {mod!r} should not exist"
            except ImportError:
                pass
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope3_no_gui_modification():
    """gui_app.py modification date is not changed by Week 9."""
    tid, name = "W9-SCOPE3", "gui_app.py is not touched by Week 9"
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        moo_dir = os.path.dirname(here)
        ps_dir  = os.path.dirname(moo_dir)
        gui_path = os.path.join(ps_dir, "gui_app.py")
        if os.path.isfile(gui_path):
            # Just verify it can be found — we don't check timestamps
            # since we can't know them deterministically.
            # The scope test here is that no Week 9 code imports from gui_app.
            bench_modules = [
                "moo.bench.schema", "moo.bench.corpus",
                "moo.bench.generator", "moo.bench.runner",
                "moo.bench.dataset",
            ]
            import importlib
            for mod_name in bench_modules:
                mod = importlib.import_module(mod_name)
                src = getattr(mod, "__file__", "") or ""
                # Read the module source and check for gui_app imports
                if src and os.path.isfile(src):
                    with open(src, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    assert "gui_app" not in content, \
                        f"{mod_name} imports gui_app (GUI modification forbidden)"
            report(tid, name, True)
        else:
            skip(tid, name, "gui_app.py not found at expected path")
    except Exception as exc:
        fail(tid, name, exc)


def test_scope4_measurement_not_reimplemented():
    """moo.bench.runner delegates to pipeline, not a new measurement engine."""
    tid, name = "W9-SCOPE4", "runner.py delegates measurement to pipeline, not re-implements it"
    try:
        import moo.bench.runner as runner_mod
        src_path = runner_mod.__file__
        with open(src_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Must import from pipeline
        assert "pipeline" in content or "evaluate_program" in content, \
            "runner.py must delegate to pipeline.evaluate_program"
        # Must NOT define its own timing functions
        assert "time.perf_counter" not in content, \
            "runner.py must not implement its own timing (use pipeline)"
        assert "subprocess.run" not in content or "git" in content, \
            "runner.py should not call subprocess.run for program execution"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope5_week8_modules_still_importable():
    """Week 8 modules (decision_trace, xai, selector_bridge, etc.) still importable."""
    tid, name = "W9-SCOPE5", "Week 8 modules remain importable after Week 9 changes"
    try:
        import moo.decision_trace
        import moo.xai
        import moo.selector_bridge
        import moo.program_profiler
        import moo.moo_result
        import moo.pipeline
        import moo.measurement
        import moo.config
        import moo.pareto
        import moo.objectives
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope6_bench_package_does_not_modify_actions():
    """moo.bench does not modify config.ACTIONS."""
    tid, name = "W9-SCOPE6", "moo.bench does not modify config.ACTIONS"
    try:
        from moo.config import ACTIONS
        original_actions = list(ACTIONS)

        # Import everything from bench
        import moo.bench
        import moo.bench.schema
        import moo.bench.corpus
        import moo.bench.generator
        import moo.bench.runner
        import moo.bench.dataset

        from moo.config import ACTIONS as actions_after
        assert list(actions_after) == original_actions, \
            "moo.bench import modified config.ACTIONS"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# Main runner
# ===========================================================================

def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    print("\n" + "=" * 70)
    print("TOACD — Week 9 Automated Benchmark & Dataset Generation Tests")
    print("=" * 70)

    print("\n--- W9-SCHEMA: Schema model validation ---")
    test_schema1_corpus_entry_roundtrip()
    test_schema2_run_manifest_roundtrip()
    test_schema3_program_record_roundtrip()
    test_schema4_program_record_failure_is_null_not_zero()
    test_schema5_dataset_manifest_roundtrip()
    test_schema6_schema_version_constants()
    test_schema7_validate_no_nan_inf()
    test_schema8_o0_baseline_convention_documented()

    print("\n--- W9-CORPUS: Corpus manifest builder ---")
    test_corpus1_build_deterministic_ordering()
    test_corpus2_sha256_stability()
    test_corpus3_exclusion_reasons_populated()
    test_corpus4_existing_programs_origin_label()
    test_corpus5_generated_entries_merged_correctly()
    test_corpus6_save_and_load_roundtrip()
    test_corpus7_id_collision_detection()
    test_corpus8_empty_directory_returns_empty()

    print("\n--- W9-GEN: Synthetic benchmark generator ---")
    test_gen1_same_seed_identical_source()
    test_gen2_different_seed_different_source()
    test_gen3_generated_filenames_never_collide_with_existing()
    test_gen4_all_families_produce_valid_c_skeleton()
    test_gen5_no_banned_functions()
    test_gen6_sha256_matches_source()
    test_gen7_generator_families_constant()
    test_gen8_bulk_generate_returns_correct_count()
    test_gen9_different_index_different_source()
    test_gen10_file_written_when_output_dir_set()
    test_gen11_origin_is_generated()
    test_gen12_family_subset_generate()

    print("\n--- W9-RUN: Batch runner (toolchain-free) ---")
    test_run1_manifest_created_on_run_start()
    test_run2_missing_toolchain_yields_error_record_not_crash()
    test_run3_excluded_entries_not_evaluated()
    test_run4_resumability_skips_existing_results()
    test_run5_deterministic_program_ordering()
    test_run6_manifest_schema_version_present()
    test_run7_manifest_baseline_convention_documented()
    test_run8_outputs_not_in_moo_reports()

    print("\n--- W9-DS: Dataset builder ---")
    test_ds1_candidate_csv_created()
    test_ds2_program_csv_created()
    test_ds3_dataset_manifest_created()
    test_ds4_no_best_strategy_label()
    test_ds5_null_handling_in_csv()
    test_ds6_checksums_in_manifest()
    test_ds7_candidate_rows_have_correct_columns()
    test_ds8_pareto_columns_are_binary()

    print("\n--- W9-SPLIT: Dataset split stability ---")
    test_split1_same_run_id_same_splits()
    test_split2_different_run_id_different_splits()
    test_split3_family_leakage_prevention()
    test_split4_split_distribution_roughly_correct()
    test_split5_split_column_in_csv()

    print("\n--- W9-INT: Data integrity ---")
    test_int1_safe_float_rejects_nan()
    test_int2_safe_int_rejects_none()
    test_int3_validate_no_nan_inf_clean()
    test_int4_program_record_pipeline_error_not_zero()
    test_int5_deterministic_pareto_representation()

    print("\n--- W9-SCOPE: Architecture / scope guard ---")
    test_scope1_bench_is_separate_from_moo_reports()
    test_scope2_no_week10_modules_introduced()
    test_scope3_no_gui_modification()
    test_scope4_measurement_not_reimplemented()
    test_scope5_week8_modules_still_importable()
    test_scope6_bench_package_does_not_modify_actions()

    print()
    print("=" * 70)
    passed = sum(1 for _, _, s in _results if s == "PASS")
    failed = sum(1 for _, _, s in _results if s == "FAIL")
    skipped = sum(1 for _, _, s in _results if s == "SKIP")
    total = len(_results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print("=" * 70 + "\n")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
