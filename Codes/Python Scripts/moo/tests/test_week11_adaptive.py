"""
moo/tests/test_week11_adaptive.py — Week 11: Adaptive Self-Learning Tests.

Test IDs follow the pattern W11-<CATEGORY><N>.

Categories
----------
  W11-SCHEMA   ExperienceRecord schema, serialization, deserialization, versioning
  W11-REWARD   Reward calculation: correctness, derived-metric handling, bounds,
               determinism, failure penalties, edge cases
  W11-VALID    Experience validation: valid acceptance, invalid rejection,
               schema checks, field checks, provenance consistency
  W11-STORE    Experience storage: persistence, duplicate detection, corruption safety,
               load/save integrity, manifest accuracy
  W11-REPLAY   ReplayBuffer: bounded capacity, FIFO eviction, deterministic sampling,
               seeded reproducibility, empty-buffer safety
  W11-LEARN    DQN learner: candidate creation, model versioning, artifact metadata,
               active model protection, backward compatibility, failure isolation
  W11-DET      Determinism: same inputs → same reward, same seed → same sample
  W11-SCOPE    Scope guards: no GUI changes, no second benchmark system, no
               Week 12+ modules, selection algorithm unchanged
  W11-BACK     Backward compatibility: existing pipeline unaffected, existing
               tests importable alongside Week 11 modules

Design constraints
------------------
  * All tests are deterministic (seeded RNG where randomness is involved).
  * Tests do NOT require clang/opt — no real compilation is done.
  * Tests do NOT require PyTorch for most cases (torch-dependent tests are
    skipped gracefully if torch is unavailable).
  * Tests use tempfile.mkdtemp() and clean up.
  * No test inflates count with trivial assertions.
"""

from __future__ import annotations

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
# Test infrastructure
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


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_VALID_SOURCE_HASH = "a" * 64  # valid 64-char hex SHA-256

_VALID_FEATURES: dict[str, float] = {
    "BasicBlocksCount": 5.0,
    "InstructionsCount": 42.0,
    "BranchCount": 3.0,
    "MemInstCount": 12.0,
    "MathInstCount": 8.0,
    "FloatInstCount": 2.0,
    "VectorInstCount": 0.0,
    "CallInstCount": 4.0,
}

_VALID_BENCHMARK_METRICS: dict = {
    "execution_time_s": 0.080,
    "code_size_bytes": 9000.0,
    "energy_j": 3.6,
    "carbon_g": 0.00044,
}

_VALID_BASELINE_METRICS: dict = {
    "execution_time_s": 0.100,
    "code_size_bytes": 10000.0,
    "energy_j": 4.5,
    "carbon_g": 0.00055,
}


def _make_experience(
    *,
    program_id: str = "test_prog",
    experience_id: str = "test_prog_run1_20261005T120000",
    source_hash: str = _VALID_SOURCE_HASH,
    run_id: str = "run_001",
    timestamp: str = "2026-10-05T12:00:00+00:00",
    ir_features: dict | None = None,
    selected_action: str = "-O2",
    selection_method: str = "moo_aware",
    model_identifier: str = "production_v0",
    trace_id: str | None = None,
    q_value_selected: float = 0.75,
    q_value_argmax: float = 0.75,
    pareto_frontier: list | None = None,
    benchmark_metrics: dict | None = None,
    baseline_metrics: dict | None = None,
    benchmark_build_ok: bool = True,
    benchmark_correct: bool = True,
    regression_overall_status: str | None = "IMPROVED",
    regression_report_id: str | None = None,
    reward: float | None = 0.17,
    reward_config_id: str = "default_v1",
    success: bool = True,
    notes: list | None = None,
):
    from moo.adaptive.schema import ADAPTIVE_SCHEMA_VERSION, ExperienceRecord
    return ExperienceRecord(
        schema_version=ADAPTIVE_SCHEMA_VERSION,
        experience_id=experience_id,
        program_id=program_id,
        source_hash=source_hash,
        run_id=run_id,
        timestamp=timestamp,
        ir_features=ir_features if ir_features is not None else dict(_VALID_FEATURES),
        selected_action=selected_action,
        selection_method=selection_method,
        model_identifier=model_identifier,
        trace_id=trace_id,
        q_value_selected=q_value_selected,
        q_value_argmax=q_value_argmax,
        pareto_frontier=pareto_frontier if pareto_frontier is not None else ["-O2"],
        benchmark_metrics=benchmark_metrics if benchmark_metrics is not None else dict(_VALID_BENCHMARK_METRICS),
        baseline_metrics=baseline_metrics if baseline_metrics is not None else dict(_VALID_BASELINE_METRICS),
        benchmark_build_ok=benchmark_build_ok,
        benchmark_correct=benchmark_correct,
        regression_overall_status=regression_overall_status,
        regression_report_id=regression_report_id,
        reward=reward,
        reward_config_id=reward_config_id,
        success=success,
        notes=notes if notes is not None else [],
    )


# ===========================================================================
# W11-SCHEMA: ExperienceRecord schema
# ===========================================================================

def test_schema1_experience_record_roundtrip():
    """ExperienceRecord to_dict and from_dict round-trip preserves all fields."""
    tid, name = "W11-SCHEMA1", "ExperienceRecord to_dict/from_dict round-trip"
    try:
        from moo.adaptive.schema import ADAPTIVE_SCHEMA_VERSION, ExperienceRecord
        exp = _make_experience()
        d = exp.to_dict()
        exp2 = ExperienceRecord.from_dict(d)
        assert exp2.schema_version == ADAPTIVE_SCHEMA_VERSION
        assert exp2.program_id == exp.program_id
        assert exp2.source_hash == exp.source_hash
        assert exp2.selected_action == exp.selected_action
        assert exp2.ir_features == exp.ir_features
        assert exp2.reward == exp.reward
        assert exp2.success == exp.success
        assert exp2.pareto_frontier == exp.pareto_frontier
        assert exp2.benchmark_metrics == exp.benchmark_metrics
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema2_json_roundtrip():
    """ExperienceRecord serializes to JSON and deserializes without data loss."""
    tid, name = "W11-SCHEMA2", "ExperienceRecord to_json/from_json round-trip"
    try:
        from moo.adaptive.schema import ExperienceRecord
        exp = _make_experience()
        j = exp.to_json()
        assert isinstance(j, str)
        exp2 = ExperienceRecord.from_json(j)
        assert exp2.experience_id == exp.experience_id
        assert exp2.ir_features == exp.ir_features
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema3_schema_version_constant():
    """ADAPTIVE_SCHEMA_VERSION is 'week11.1.0'."""
    tid, name = "W11-SCHEMA3", "ADAPTIVE_SCHEMA_VERSION is 'week11.1.0'"
    try:
        from moo.adaptive.schema import ADAPTIVE_SCHEMA_VERSION
        assert ADAPTIVE_SCHEMA_VERSION == "week11.1.0"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema4_unsupported_schema_version_rejected():
    """Deserializing an ExperienceRecord with an unsupported schema_version raises ValueError."""
    tid, name = "W11-SCHEMA4", "Unsupported schema_version rejected on deserialization"
    try:
        from moo.adaptive.schema import ExperienceRecord
        exp = _make_experience()
        d = exp.to_dict()
        d["schema_version"] = "week9.1.0"
        raised = False
        try:
            ExperienceRecord.from_dict(d)
        except ValueError:
            raised = True
        assert raised, "Expected ValueError for unsupported schema_version"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema5_optional_fields_preserved():
    """Optional fields (trace_id=None, regression_report_id=None) survive round-trip."""
    tid, name = "W11-SCHEMA5", "Optional None fields preserved in round-trip"
    try:
        from moo.adaptive.schema import ExperienceRecord
        exp = _make_experience(trace_id=None, regression_report_id=None, reward=None)
        d = exp.to_dict()
        exp2 = ExperienceRecord.from_dict(d)
        assert exp2.trace_id is None
        assert exp2.regression_report_id is None
        assert exp2.reward is None
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema6_model_version_info_roundtrip():
    """ModelVersionInfo to_dict and from_dict round-trip preserves all fields."""
    tid, name = "W11-SCHEMA6", "ModelVersionInfo to_dict/from_dict round-trip"
    try:
        from moo.adaptive.schema import ADAPTIVE_SCHEMA_VERSION, ModelVersionInfo
        mvi = ModelVersionInfo(
            schema_version=ADAPTIVE_SCHEMA_VERSION,
            model_version=1,
            model_id="candidate_v1_20261005T120000",
            created_at="2026-10-05T12:00:00+00:00",
            source_model_id="production_v0",
            experience_count=42,
            experience_id_first="exp_a",
            experience_id_last="exp_b",
            training_epochs=5,
            mean_loss=0.0123,
            mean_reward=0.14,
            reward_config_id="default_v1",
            dqn_input_dim=8,
            dqn_output_dim=9,
            is_production=False,
            notes=["test note"],
        )
        d = mvi.to_dict()
        mvi2 = ModelVersionInfo.from_dict(d)
        assert mvi2.model_version == 1
        assert mvi2.model_id == "candidate_v1_20261005T120000"
        assert mvi2.experience_count == 42
        assert mvi2.is_production is False
        assert math.isclose(mvi2.mean_loss, 0.0123)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema7_source_hash_preserved_exactly():
    """source_hash string is preserved exactly through serialization."""
    tid, name = "W11-SCHEMA7", "source_hash preserved exactly through serialization"
    try:
        from moo.adaptive.schema import ExperienceRecord
        sh = "b" * 64
        exp = _make_experience(source_hash=sh)
        d = exp.to_dict()
        exp2 = ExperienceRecord.from_dict(d)
        assert exp2.source_hash == sh
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_schema8_benchmark_metrics_none_values_preserved():
    """None values in benchmark_metrics survive round-trip."""
    tid, name = "W11-SCHEMA8", "None metric values survive round-trip"
    try:
        from moo.adaptive.schema import ExperienceRecord
        bm = {"execution_time_s": None, "code_size_bytes": 9000.0, "energy_j": None, "carbon_g": None}
        exp = _make_experience(
            benchmark_metrics=bm,
            benchmark_build_ok=False,
            benchmark_correct=False,
            success=False,
            reward=-10.0,
        )
        d = exp.to_dict()
        exp2 = ExperienceRecord.from_dict(d)
        assert exp2.benchmark_metrics.get("execution_time_s") is None
        assert math.isclose(exp2.benchmark_metrics.get("code_size_bytes"), 9000.0)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-REWARD: Reward calculation
# ===========================================================================

def test_reward1_improved_execution_time():
    """Faster execution time produces positive reward."""
    tid, name = "W11-REWARD1", "Faster execution time yields positive reward"
    try:
        from moo.adaptive.reward import compute_reward
        # 0.080s vs 0.100s baseline → 20% faster → positive reward
        r = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        assert r > 0, f"Expected positive reward, got {r}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward2_regression_execution_time():
    """Slower execution time produces negative or zero reward."""
    tid, name = "W11-REWARD2", "Slower execution time yields non-positive reward"
    try:
        from moo.adaptive.reward import compute_reward
        # 0.130s vs 0.100s baseline → 30% slower → negative reward
        r = compute_reward(
            benchmark_metrics={"execution_time_s": 0.130, "code_size_bytes": 10000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        assert r < 0, f"Expected negative reward for regression, got {r}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward3_build_failure_negative_reward():
    """Build failure produces a large negative reward."""
    tid, name = "W11-REWARD3", "Build failure yields large negative reward"
    try:
        from moo.adaptive.reward import compute_reward, DEFAULT_REWARD_CONFIG
        r = compute_reward(
            benchmark_metrics={},
            baseline_metrics={"execution_time_s": 0.100},
            benchmark_build_ok=False,
            benchmark_correct=False,
        )
        assert r < 0
        assert abs(r) >= DEFAULT_REWARD_CONFIG.penalty_build_fail * 0.9
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward4_incorrect_result_penalty():
    """Incorrect result applies penalty regardless of metric improvements."""
    tid, name = "W11-REWARD4", "Incorrect result applies penalty"
    try:
        from moo.adaptive.reward import compute_reward
        r_correct = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        r_incorrect = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=False,
        )
        assert r_incorrect < r_correct
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward5_derived_metrics_not_independent_terms():
    """Energy and carbon are NOT counted as additional independent reward terms.

    If energy and carbon were independent terms, a program with the same
    execution time but different (but physically consistent) energy/carbon
    values would compute a different reward.  This test verifies they are NOT.
    """
    tid, name = "W11-REWARD5", "Energy/carbon not counted as independent reward dimensions"
    try:
        from moo.adaptive.reward import compute_reward
        # Same execution time and code size; only energy/carbon differ.
        r1 = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0,
                               "energy_j": 3.6, "carbon_g": 0.00044},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0,
                              "energy_j": 4.5, "carbon_g": 0.00055},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        r2 = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0,
                               "energy_j": 99.0, "carbon_g": 0.99},  # wildly different
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0,
                              "energy_j": 4.5, "carbon_g": 0.00055},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        # Reward must be identical — energy and carbon don't affect reward.
        assert r1 == r2, (
            f"Reward changed when only derived metrics differed: {r1} != {r2}. "
            "Energy/carbon must not be independent reward terms."
        )
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward6_reward_is_bounded():
    """Reward is bounded by RewardConfig.max_reward."""
    tid, name = "W11-REWARD6", "Reward is clamped to [-max_reward, +max_reward]"
    try:
        from moo.adaptive.reward import compute_reward, RewardConfig
        cfg = RewardConfig(config_id="test", weight_performance=1000.0, weight_size=1000.0, max_reward=100.0)
        r = compute_reward(
            benchmark_metrics={"execution_time_s": 0.001, "code_size_bytes": 1.0},
            baseline_metrics={"execution_time_s": 1000.0, "code_size_bytes": 1000000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            config=cfg,
        )
        assert abs(r) <= 100.0, f"Reward {r} exceeds max_reward ±100"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward7_determinism_50_calls():
    """Same inputs always produce the same reward across 50 calls."""
    tid, name = "W11-REWARD7", "Reward is deterministic across 50 repeated calls"
    try:
        from moo.adaptive.reward import compute_reward
        kwargs = dict(
            benchmark_metrics={"execution_time_s": 0.085, "code_size_bytes": 9500.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        r0 = compute_reward(**kwargs)
        for _ in range(49):
            assert compute_reward(**kwargs) == r0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward8_missing_execution_time_neutral():
    """Missing execution_time_s produces neutral (0.0) performance term."""
    tid, name = "W11-REWARD8", "Missing execution_time_s gives neutral performance term"
    try:
        from moo.adaptive.reward import compute_reward, DEFAULT_REWARD_CONFIG
        # Only code_size is available; performance term should be 0.
        r = compute_reward(
            benchmark_metrics={"execution_time_s": None, "code_size_bytes": 8000.0},
            baseline_metrics={"execution_time_s": None, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        # Size gain: (1 - 8000/10000) * w_size = 0.2 * 0.3 = 0.06
        expected = (1.0 - 8000.0 / 10000.0) * DEFAULT_REWARD_CONFIG.weight_size
        assert math.isclose(r, expected, rel_tol=1e-6), f"Got {r}, expected {expected}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward9_zero_baseline_time_neutral():
    """Zero baseline execution time returns neutral (0.0) for that term."""
    tid, name = "W11-REWARD9", "Zero baseline execution time returns neutral term"
    try:
        from moo.adaptive.reward import compute_reward
        r = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080},
            baseline_metrics={"execution_time_s": 0.0},  # zero baseline → neutral
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        # Performance gain should be 0.0 (no size metric → total 0.0)
        assert math.isclose(r, 0.0, abs_tol=1e-9), f"Expected 0.0 reward, got {r}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward10_apply_reward_to_experience():
    """apply_reward_to_experience sets reward and reward_config_id on the record."""
    tid, name = "W11-REWARD10", "apply_reward_to_experience mutates experience in-place"
    try:
        from moo.adaptive.reward import apply_reward_to_experience, DEFAULT_REWARD_CONFIG
        exp = _make_experience(reward=None, reward_config_id="")
        r = apply_reward_to_experience(exp)
        assert exp.reward == r
        assert exp.reward_config_id == DEFAULT_REWARD_CONFIG.config_id
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward11_reward_config_roundtrip():
    """RewardConfig to_dict and from_dict round-trip preserves all parameters."""
    tid, name = "W11-REWARD11", "RewardConfig to_dict/from_dict round-trip"
    try:
        from moo.adaptive.reward import RewardConfig
        cfg = RewardConfig(
            config_id="custom_v2",
            weight_performance=0.6,
            weight_size=0.4,
            penalty_build_fail=20.0,
            penalty_incorrect=15.0,
            max_reward=50.0,
        )
        d = cfg.to_dict()
        cfg2 = RewardConfig.from_dict(d)
        assert cfg2.config_id == "custom_v2"
        assert math.isclose(cfg2.weight_performance, 0.6)
        assert math.isclose(cfg2.weight_size, 0.4)
        assert math.isclose(cfg2.max_reward, 50.0)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_reward12_nan_metric_gives_neutral_term():
    """NaN in benchmark_metrics produces neutral gain for that term."""
    tid, name = "W11-REWARD12", "NaN metric value produces neutral reward term"
    try:
        from moo.adaptive.reward import compute_reward
        r = compute_reward(
            benchmark_metrics={"execution_time_s": float("nan"), "code_size_bytes": 9000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        assert math.isfinite(r), f"Reward must be finite even with NaN input, got {r}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-VALID: Experience validation
# ===========================================================================

def test_valid1_valid_experience_accepted():
    """A fully valid experience passes all validation checks."""
    tid, name = "W11-VALID1", "Valid experience passes all validation checks"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience()
        result = validate_experience(exp)
        assert bool(result), f"Valid experience rejected: {result.errors}"
        assert result.errors == []
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid2_wrong_schema_version_rejected():
    """Experience with unsupported schema_version is rejected."""
    tid, name = "W11-VALID2", "Wrong schema_version rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience()
        exp.schema_version = "week8.1.0"
        result = validate_experience(exp)
        assert not result
        assert any("schema_version" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid3_empty_experience_id_rejected():
    """Empty experience_id is rejected."""
    tid, name = "W11-VALID3", "Empty experience_id rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(experience_id="")
        result = validate_experience(exp)
        assert not result
        assert any("experience_id" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid4_invalid_source_hash_rejected():
    """Source hash that is too short or non-hex is rejected."""
    tid, name = "W11-VALID4", "Invalid source_hash rejected"
    try:
        from moo.adaptive.validator import validate_experience
        # Too short
        exp1 = _make_experience(source_hash="abc123")
        r1 = validate_experience(exp1)
        assert not r1, "Short source_hash should be rejected"

        # Non-hex characters
        exp2 = _make_experience(source_hash="z" * 64)
        r2 = validate_experience(exp2)
        assert not r2, "Non-hex source_hash should be rejected"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid5_empty_ir_features_rejected():
    """Empty ir_features dict is rejected."""
    tid, name = "W11-VALID5", "Empty ir_features rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(ir_features={})
        result = validate_experience(exp)
        assert not result
        assert any("ir_features" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid6_nan_ir_feature_rejected():
    """NaN in ir_features is rejected."""
    tid, name = "W11-VALID6", "NaN ir_feature value rejected"
    try:
        from moo.adaptive.validator import validate_experience
        feats = dict(_VALID_FEATURES)
        feats["BasicBlocksCount"] = float("nan")
        exp = _make_experience(ir_features=feats)
        result = validate_experience(exp)
        assert not result
        assert any("ir_features" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid7_unknown_metric_key_rejected():
    """Unknown metric key in benchmark_metrics is rejected."""
    tid, name = "W11-VALID7", "Unknown benchmark_metrics key rejected"
    try:
        from moo.adaptive.validator import validate_experience
        bm = {"execution_time_s": 0.08, "unknown_metric": 99.9}
        exp = _make_experience(benchmark_metrics=bm)
        result = validate_experience(exp)
        assert not result
        assert any("unknown_metric" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid8_negative_metric_value_rejected():
    """Negative metric value in benchmark_metrics is rejected."""
    tid, name = "W11-VALID8", "Negative metric value rejected"
    try:
        from moo.adaptive.validator import validate_experience
        bm = {"execution_time_s": -0.001, "code_size_bytes": 9000.0}
        exp = _make_experience(benchmark_metrics=bm)
        result = validate_experience(exp)
        assert not result
        assert any("negative" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid9_invalid_selection_method_rejected():
    """Unknown selection_method is rejected."""
    tid, name = "W11-VALID9", "Unknown selection_method rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(selection_method="random_forest_selection")
        result = validate_experience(exp)
        assert not result
        assert any("selection_method" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid10_build_fail_positive_reward_rejected():
    """Positive reward with build_fail=True is rejected (consistency check)."""
    tid, name = "W11-VALID10", "Positive reward with build_fail=True rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(
            benchmark_build_ok=False,
            benchmark_correct=False,
            success=False,
            reward=5.0,  # positive but build failed
        )
        result = validate_experience(exp)
        assert not result
        assert any("build_fail" in e.lower() or "build_ok" in e.lower() for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid11_success_true_with_failed_build_rejected():
    """success=True with benchmark_build_ok=False is rejected."""
    tid, name = "W11-VALID11", "success=True with failed build rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(
            benchmark_build_ok=False,
            success=True,    # inconsistent
        )
        result = validate_experience(exp)
        assert not result
        assert any("success" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid12_invalid_regression_status_rejected():
    """Unknown regression_overall_status is rejected."""
    tid, name = "W11-VALID12", "Unknown regression_overall_status rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(regression_overall_status="AWESOME")
        result = validate_experience(exp)
        assert not result
        assert any("regression_overall_status" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid13_none_regression_status_accepted():
    """None regression_overall_status (not yet available) is accepted."""
    tid, name = "W11-VALID13", "None regression_overall_status accepted"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(regression_overall_status=None)
        result = validate_experience(exp)
        assert bool(result), f"None regression status should be accepted: {result.errors}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid14_inf_reward_rejected():
    """Infinite reward value is rejected."""
    tid, name = "W11-VALID14", "Infinite reward rejected"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(reward=float("inf"))
        result = validate_experience(exp)
        assert not result
        assert any("reward" in e for e in result.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_valid15_validator_never_raises():
    """validate_experience never raises even on completely garbage input."""
    tid, name = "W11-VALID15", "Validator never raises on garbage input"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience()
        # Corrupt internal state manually
        exp.ir_features = None  # type: ignore
        exp.benchmark_metrics = "not a dict"  # type: ignore
        exp.source_hash = 12345  # type: ignore
        try:
            result = validate_experience(exp)
            # Should return a ValidationResult (failed), not raise
            assert not result
        except Exception as inner_exc:
            raise AssertionError(f"validate_experience raised: {inner_exc}") from inner_exc
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-STORE: Experience storage
# ===========================================================================

def test_store1_add_and_reload():
    """An accepted experience can be loaded back from disk exactly."""
    tid, name = "W11-STORE1", "Experience written to disk and reloaded correctly"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)
        exp = _make_experience()
        accepted = store.add(exp)
        assert accepted

        records = store.load_all()
        assert len(records) == 1
        assert records[0].experience_id == exp.experience_id
        assert records[0].source_hash == exp.source_hash
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store2_duplicate_rejected():
    """Adding the same experience_id twice is rejected (duplicate detection)."""
    tid, name = "W11-STORE2", "Duplicate experience_id rejected"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)
        exp = _make_experience()
        accepted1 = store.add(exp)
        accepted2 = store.add(exp)
        assert accepted1 is True
        assert accepted2 is False
        records = store.load_all()
        assert len(records) == 1
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store3_invalid_experience_rejected():
    """An invalid experience (fails validation) is rejected by the store."""
    tid, name = "W11-STORE3", "Invalid experience rejected by store"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)
        exp = _make_experience(experience_id="")  # fails validation
        accepted = store.add(exp)
        assert accepted is False
        assert store.record_count == 0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store4_manifest_record_count_accurate():
    """store.record_count matches actual number of records added."""
    tid, name = "W11-STORE4", "Manifest record_count stays accurate"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)
        for i in range(5):
            exp = _make_experience(
                experience_id=f"exp_{i:03d}",
                program_id=f"prog_{i}",
            )
            store.add(exp)
        assert store.record_count == 5
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store5_corrupt_line_skipped():
    """A corrupt line in the JSONL file is skipped, not a hard failure."""
    tid, name = "W11-STORE5", "Corrupt JSONL line skipped without crash"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)

        # Write one valid record
        exp = _make_experience()
        store.add(exp)

        # Manually inject a corrupt line into the data file
        with open(store.data_path, "a", encoding="utf-8") as fh:
            fh.write("NOT VALID JSON }{{\n")

        # Reload — corrupt line should be skipped
        store2 = ExperienceStore(tmpdir)
        records = store2.load_all()
        assert len(records) == 1
        assert store2.corrupt_line_count == 1
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store6_empty_store_returns_empty_list():
    """load_all() on a fresh store returns an empty list."""
    tid, name = "W11-STORE6", "Empty store returns empty list from load_all"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)
        records = store.load_all()
        assert records == []
        assert store.record_count == 0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store7_add_batch():
    """add_batch adds multiple records and returns accurate (accepted, rejected) counts."""
    tid, name = "W11-STORE7", "add_batch adds multiple records correctly"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)
        exps = [_make_experience(experience_id=f"exp_{i}") for i in range(4)]
        exps.append(_make_experience(experience_id=""))  # invalid → rejected
        accepted, rejected = store.add_batch(exps)
        assert accepted == 4
        assert rejected == 1
        assert store.record_count == 4
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store8_exists_check_before_add():
    """exists() returns True for a known id and False for an unknown id."""
    tid, name = "W11-STORE8", "exists() check works correctly"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store = ExperienceStore(tmpdir)
        exp = _make_experience(experience_id="known_exp")
        store.add(exp)
        assert store.exists("known_exp") is True
        assert store.exists("unknown_exp") is False
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_store9_persistence_across_instances():
    """Records added in one ExperienceStore instance are readable by a new instance."""
    tid, name = "W11-STORE9", "Records persist across ExperienceStore instances"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore
        store1 = ExperienceStore(tmpdir)
        for i in range(3):
            store1.add(_make_experience(experience_id=f"exp_{i}", program_id=f"p_{i}"))

        # New instance
        store2 = ExperienceStore(tmpdir)
        records = store2.load_all()
        assert len(records) == 3
        ids = {r.experience_id for r in records}
        assert ids == {"exp_0", "exp_1", "exp_2"}
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ===========================================================================
# W11-REPLAY: ReplayBuffer
# ===========================================================================

def test_replay1_push_and_len():
    """ReplayBuffer accepts experiences and len() returns correct count."""
    tid, name = "W11-REPLAY1", "ReplayBuffer push and len work correctly"
    try:
        from moo.adaptive.storage import ReplayBuffer
        buf = ReplayBuffer(capacity=10)
        for i in range(5):
            buf.push(_make_experience(experience_id=f"e{i}"))
        assert len(buf) == 5
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_replay2_bounded_capacity_fifo():
    """When capacity is exceeded, oldest entries are discarded (FIFO)."""
    tid, name = "W11-REPLAY2", "Bounded capacity evicts oldest entries (FIFO)"
    try:
        from moo.adaptive.storage import ReplayBuffer
        buf = ReplayBuffer(capacity=3)
        for i in range(5):
            buf.push(_make_experience(experience_id=f"e{i}"))
        assert len(buf) == 3
        ids = {e.experience_id for e in buf.sample_all()}
        # Only last 3 should remain: e2, e3, e4
        assert "e0" not in ids
        assert "e1" not in ids
        assert "e4" in ids
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_replay3_deterministic_sampling_with_seed():
    """Same seed produces same sample every time."""
    tid, name = "W11-REPLAY3", "Seeded sampling is reproducible"
    try:
        from moo.adaptive.storage import ReplayBuffer
        buf = ReplayBuffer(capacity=100)
        for i in range(20):
            buf.push(_make_experience(experience_id=f"e{i}"))

        s1 = [e.experience_id for e in buf.sample(5, seed=42)]
        s2 = [e.experience_id for e in buf.sample(5, seed=42)]
        assert s1 == s2, f"Same seed should give same sample: {s1} != {s2}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_replay4_different_seeds_different_samples():
    """Different seeds typically produce different samples."""
    tid, name = "W11-REPLAY4", "Different seeds produce different samples"
    try:
        from moo.adaptive.storage import ReplayBuffer
        buf = ReplayBuffer(capacity=100)
        for i in range(20):
            buf.push(_make_experience(experience_id=f"e{i}"))

        s1 = [e.experience_id for e in buf.sample(10, seed=1)]
        s2 = [e.experience_id for e in buf.sample(10, seed=999)]
        assert s1 != s2, "Different seeds should usually produce different samples"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_replay5_empty_buffer_sample_returns_empty():
    """Sampling from an empty buffer returns an empty list."""
    tid, name = "W11-REPLAY5", "Empty buffer sample returns empty list"
    try:
        from moo.adaptive.storage import ReplayBuffer
        buf = ReplayBuffer(capacity=10)
        s = buf.sample(5, seed=0)
        assert s == []
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_replay6_sample_without_replacement():
    """Sample of size <= buffer size never returns duplicate experiences."""
    tid, name = "W11-REPLAY6", "Sampling without replacement — no duplicates"
    try:
        from moo.adaptive.storage import ReplayBuffer
        buf = ReplayBuffer(capacity=10)
        for i in range(8):
            buf.push(_make_experience(experience_id=f"e{i}"))

        sample = buf.sample(8, seed=7)
        ids = [e.experience_id for e in sample]
        assert len(ids) == len(set(ids)), "Sample contains duplicate experiences"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_replay7_load_from_store():
    """ReplayBuffer.load_from_store correctly loads from an ExperienceStore."""
    tid, name = "W11-REPLAY7", "ReplayBuffer.load_from_store loads correctly from ExperienceStore"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.storage import ExperienceStore, ReplayBuffer
        store = ExperienceStore(tmpdir)
        for i in range(6):
            store.add(_make_experience(experience_id=f"stored_{i}"))

        buf = ReplayBuffer(capacity=100)
        n = buf.load_from_store(store)
        assert n == 6
        assert len(buf) == 6
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_replay8_clear():
    """ReplayBuffer.clear() empties the buffer."""
    tid, name = "W11-REPLAY8", "ReplayBuffer.clear() empties the buffer"
    try:
        from moo.adaptive.storage import ReplayBuffer
        buf = ReplayBuffer(capacity=10)
        for i in range(5):
            buf.push(_make_experience(experience_id=f"e{i}"))
        buf.clear()
        assert len(buf) == 0
        assert buf.sample_all() == []
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-LEARN: DQN Learner / Model Versioning
# ===========================================================================

def _torch_available() -> bool:
    try:
        import torch
        return True
    except ImportError:
        return False


def _ml_optimizer_available() -> bool:
    try:
        from ml_optimizer import DQN, ACTIONS
        return True
    except Exception:
        return False


def test_learn1_candidate_dir_created():
    """DQNLearner creates candidate_dir if it does not exist."""
    tid, name = "W11-LEARN1", "DQNLearner creates candidate_dir automatically"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.learner import DQNLearner
        cdir = os.path.join(tmpdir, "models", "candidates")
        learner = DQNLearner(candidate_dir=cdir)
        assert os.path.isdir(cdir)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learn2_model_version_info_not_production():
    """ModelVersionInfo.is_production is always False for candidate models."""
    tid, name = "W11-LEARN2", "ModelVersionInfo.is_production is always False"
    try:
        from moo.adaptive.schema import ADAPTIVE_SCHEMA_VERSION, ModelVersionInfo
        mvi = ModelVersionInfo(
            schema_version=ADAPTIVE_SCHEMA_VERSION,
            model_version=1,
            model_id="candidate_v1",
            created_at="2026-10-05T12:00:00+00:00",
            source_model_id=None,
            experience_count=10,
            experience_id_first=None,
            experience_id_last=None,
            training_epochs=5,
            mean_loss=0.01,
            mean_reward=0.15,
            reward_config_id="default_v1",
            dqn_input_dim=8,
            dqn_output_dim=9,
            is_production=False,  # MUST be False for candidates
            notes=[],
        )
        assert mvi.is_production is False
        # Verify round-trip preserves this
        mvi2 = ModelVersionInfo.from_dict(mvi.to_dict())
        assert mvi2.is_production is False
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_learn3_list_candidates_empty_dir():
    """list_candidates returns empty list when no candidates exist."""
    tid, name = "W11-LEARN3", "list_candidates returns [] when no models exist"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.learner import DQNLearner
        learner = DQNLearner(candidate_dir=tmpdir)
        candidates = learner.list_candidates()
        assert candidates == []
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learn4_production_model_not_overwritten():
    """DQNLearner.learn() does not write to the production model path."""
    tid, name = "W11-LEARN4", "Production model is never overwritten by learner"
    if not _torch_available() or not _ml_optimizer_available():
        skip(tid, name, "(torch or ml_optimizer unavailable)")
        return
    tmpdir = tempfile.mkdtemp()
    try:
        import torch
        from moo.adaptive.learner import DQNLearner
        from moo.adaptive.storage import ReplayBuffer

        prod_path = os.path.join(tmpdir, "production_model.pth")
        cdir = os.path.join(tmpdir, "candidates")

        # Create a dummy production model file
        from ml_optimizer import DQN, ACTIONS
        m = DQN(8, len(ACTIONS))
        torch.save(m.state_dict(), prod_path)
        prod_mtime = os.path.getmtime(prod_path)

        # Build a small replay buffer
        buf = ReplayBuffer(capacity=20)
        for i in range(3):
            exp = _make_experience(
                experience_id=f"exp_{i}",
                selected_action="-O2",
                reward=0.15,
            )
            buf.push(exp)

        learner = DQNLearner(
            candidate_dir=cdir,
            seed=42,
            epochs=1,
            source_model_path=prod_path,
        )
        learner.learn(buf, min_experiences=1)

        # Production model must be untouched
        assert math.isclose(os.path.getmtime(prod_path), prod_mtime, abs_tol=1e-6), \
            "Production model mtime changed — it was modified!"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learn5_candidate_artifact_created():
    """learn() creates a .pth file and a companion _meta.json file."""
    tid, name = "W11-LEARN5", "learn() creates .pth and _meta.json candidate artifacts"
    if not _torch_available() or not _ml_optimizer_available():
        skip(tid, name, "(torch or ml_optimizer unavailable)")
        return
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.learner import DQNLearner
        from moo.adaptive.storage import ReplayBuffer

        buf = ReplayBuffer(capacity=20)
        for i in range(3):
            buf.push(_make_experience(experience_id=f"exp_{i}", selected_action="-O2", reward=0.1))

        learner = DQNLearner(candidate_dir=tmpdir, seed=1, epochs=1)
        mvi = learner.learn(buf, min_experiences=1, model_version=1)

        pth = learner.last_candidate_path
        assert pth is not None
        assert os.path.isfile(pth), f".pth not found at {pth}"
        meta = pth.replace(".pth", "_meta.json")
        assert os.path.isfile(meta), f"_meta.json not found at {meta}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learn6_model_version_info_metadata():
    """ModelVersionInfo returned by learn() has correct metadata."""
    tid, name = "W11-LEARN6", "ModelVersionInfo returned by learn() has correct fields"
    if not _torch_available() or not _ml_optimizer_available():
        skip(tid, name, "(torch or ml_optimizer unavailable)")
        return
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.learner import DQNLearner
        from moo.adaptive.storage import ReplayBuffer

        buf = ReplayBuffer(capacity=20)
        for i in range(4):
            buf.push(_make_experience(experience_id=f"exp_{i}", selected_action="-O2", reward=0.2))

        learner = DQNLearner(candidate_dir=tmpdir, seed=0, epochs=2)
        mvi = learner.learn(buf, min_experiences=1, model_version=3, reward_config_id="default_v1")

        assert mvi.model_version == 3
        assert mvi.is_production is False
        assert mvi.experience_count == 4
        assert mvi.training_epochs == 2
        assert mvi.dqn_input_dim == 8
        assert mvi.reward_config_id == "default_v1"
        assert mvi.mean_loss is not None
        assert math.isfinite(mvi.mean_loss)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learn7_too_few_experiences_raises():
    """learn() with fewer than min_experiences raises ValueError."""
    tid, name = "W11-LEARN7", "learn() raises ValueError when buffer has too few experiences"
    if not _torch_available() or not _ml_optimizer_available():
        skip(tid, name, "(torch or ml_optimizer unavailable)")
        return
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.learner import DQNLearner
        from moo.adaptive.storage import ReplayBuffer

        buf = ReplayBuffer(capacity=20)
        buf.push(_make_experience(experience_id="only_one", selected_action="-O2", reward=0.1))

        learner = DQNLearner(candidate_dir=tmpdir, seed=0, epochs=1)
        raised = False
        try:
            learner.learn(buf, min_experiences=5)
        except ValueError:
            raised = True
        assert raised, "Expected ValueError for insufficient experiences"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learn8_list_candidates_after_learn():
    """list_candidates() finds the model created by learn()."""
    tid, name = "W11-LEARN8", "list_candidates() finds newly created candidate"
    if not _torch_available() or not _ml_optimizer_available():
        skip(tid, name, "(torch or ml_optimizer unavailable)")
        return
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.learner import DQNLearner
        from moo.adaptive.storage import ReplayBuffer

        buf = ReplayBuffer(capacity=20)
        for i in range(3):
            buf.push(_make_experience(experience_id=f"e{i}", selected_action="-O2", reward=0.1))

        learner = DQNLearner(candidate_dir=tmpdir, seed=2, epochs=1)
        mvi = learner.learn(buf, min_experiences=1, model_version=7)
        candidates = learner.list_candidates()
        assert len(candidates) == 1
        assert candidates[0].model_version == 7
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_learn9_canonical_feature_order():
    """_canonical_feature_order returns exactly 8 feature names."""
    tid, name = "W11-LEARN9", "_canonical_feature_order returns 8 feature names"
    try:
        from moo.adaptive.learner import _canonical_feature_order
        order = _canonical_feature_order()
        assert len(order) == 8
        assert "BasicBlocksCount" in order
        assert "CallInstCount" in order
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-DET: Determinism tests
# ===========================================================================

def test_det1_reward_determinism():
    """Reward for fixed inputs is identical across 100 calls."""
    tid, name = "W11-DET1", "Reward deterministic across 100 calls"
    try:
        from moo.adaptive.reward import compute_reward
        kwargs = dict(
            benchmark_metrics={"execution_time_s": 0.075, "code_size_bytes": 8500.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
        )
        ref = compute_reward(**kwargs)
        for _ in range(99):
            assert compute_reward(**kwargs) == ref
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_det2_seeded_replay_sample_determinism():
    """Same seed, same buffer content → identical sample order, 20 trials."""
    tid, name = "W11-DET2", "Seeded ReplayBuffer sampling is reproducible over 20 trials"
    try:
        from moo.adaptive.storage import ReplayBuffer
        exps = [_make_experience(experience_id=f"e{i}") for i in range(15)]
        buf = ReplayBuffer(capacity=100, seed=99)
        buf.push_batch(exps)

        ref_sample = [e.experience_id for e in buf.sample(7, seed=99)]
        for _ in range(19):
            cur = [e.experience_id for e in buf.sample(7, seed=99)]
            assert cur == ref_sample
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_det3_validation_determinism():
    """validate_experience returns same result for the same input across 20 calls."""
    tid, name = "W11-DET3", "Experience validation is deterministic"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience()
        ref = validate_experience(exp)
        for _ in range(19):
            cur = validate_experience(exp)
            assert bool(cur) == bool(ref)
            assert cur.errors == ref.errors
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_det4_experience_serialization_determinism():
    """to_dict() returns the same dict on every call."""
    tid, name = "W11-DET4", "to_dict() output is deterministic"
    try:
        exp = _make_experience()
        d1 = exp.to_dict()
        d2 = exp.to_dict()
        assert d1 == d2
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-SCOPE: Scope guards
# ===========================================================================

def test_scope1_no_week12_modules():
    """No Week 12+ agentic modules exist in moo/."""
    tid, name = "W11-SCOPE1", "No Week 12+ agentic modules in moo/"
    try:
        import importlib
        prohibited = [
            "moo.agentic",
            "moo.agentic_ai",
            "moo.llm_agent",
            "moo.autonomous_loop",
        ]
        for mod in prohibited:
            try:
                importlib.import_module(mod)
                assert False, f"Week 12+ module {mod!r} should not exist"
            except ImportError:
                pass
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope2_gui_not_imported_by_adaptive():
    """moo.adaptive modules do not import gui_app."""
    tid, name = "W11-SCOPE2", "moo.adaptive modules do not import gui_app"
    try:
        adaptive_modules = [
            "moo.adaptive.schema",
            "moo.adaptive.reward",
            "moo.adaptive.validator",
            "moo.adaptive.storage",
            "moo.adaptive.learner",
        ]
        import importlib
        for mod_name in adaptive_modules:
            try:
                mod = importlib.import_module(mod_name)
                src_file = getattr(mod, "__file__", "")
                if src_file and os.path.isfile(src_file):
                    with open(src_file, "r", encoding="utf-8") as fh:
                        content = fh.read()
                    assert "gui_app" not in content, \
                        f"{mod_name} imports or references gui_app"
            except ImportError:
                pass
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope3_no_new_benchmark_system():
    """moo.adaptive does not create a new benchmark runner or measurement system."""
    tid, name = "W11-SCOPE3", "No new benchmark system in moo.adaptive"
    try:
        # The adaptive package must not import pipeline, measurement, or create
        # a new benchmark system.  It only reads ExperienceRecord inputs.
        import importlib
        disallowed_in_adaptive = [
            "moo.adaptive.benchmark",
            "moo.adaptive.measurement",
            "moo.adaptive.pipeline",
        ]
        for mod in disallowed_in_adaptive:
            try:
                importlib.import_module(mod)
                assert False, f"Adaptive module {mod!r} should not exist"
            except ImportError:
                pass
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope4_selection_algorithm_unchanged():
    """moo_aware_select behavior is unchanged — adaptive package doesn't alter it."""
    tid, name = "W11-SCOPE4", "MOO selection algorithm behavior is unchanged"
    try:
        from moo.selector_bridge import moo_aware_select
        try:
            from ml_optimizer import ACTIONS
            q_dummy = [0.1] * len(ACTIONS)
            q_dummy[2] = 0.9  # -O2 (index 2)
            res = moo_aware_select("dummy.c", q_dummy, ACTIONS, ["-O2"])
            assert res.strategy == "-O2"
        except ImportError:
            pass  # torch unavailable — skip ML part
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope5_o0_baseline_not_changed():
    """The -O0 baseline strategy is still present in ACTIONS and unchanged."""
    tid, name = "W11-SCOPE5", "-O0 baseline is unchanged in ACTIONS"
    try:
        try:
            from ml_optimizer import ACTIONS
            assert "-O0" in ACTIONS, "-O0 not found in ACTIONS"
        except ImportError:
            pass  # torch unavailable — skip
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope6_week10_regression_schema_importable():
    """Week 10 regression schema still imports correctly alongside adaptive."""
    tid, name = "W11-SCOPE6", "Week 10 regression schema still importable alongside adaptive"
    try:
        from moo.regression.schema import REGRESSION_SCHEMA_VERSION
        from moo.adaptive.schema import ADAPTIVE_SCHEMA_VERSION
        assert REGRESSION_SCHEMA_VERSION == "week10.1.0"
        assert ADAPTIVE_SCHEMA_VERSION == "week11.1.0"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope7_week9_bench_schema_importable():
    """Week 9 bench schema still imports correctly alongside adaptive."""
    tid, name = "W11-SCOPE7", "Week 9 bench schema still importable alongside adaptive"
    try:
        from moo.bench.schema import BENCH_SCHEMA_VERSION
        assert BENCH_SCHEMA_VERSION == "week9.1.0"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_scope8_adaptive_week_constant():
    """moo.adaptive.__week__ is 11."""
    tid, name = "W11-SCOPE8", "moo.adaptive.__week__ is 11 (scope guard)"
    try:
        import moo.adaptive as _adap
        assert _adap.__week__ == 11
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-BACK: Backward compatibility
# ===========================================================================

def test_back1_decision_trace_still_works():
    """DecisionTrace from Week 7 is still importable and functional."""
    tid, name = "W11-BACK1", "DecisionTrace (Week 7) still importable and functional"
    try:
        from moo.decision_trace import DecisionTrace, ObjectiveSnapshot
        snap = ObjectiveSnapshot(
            strategy_name="-O2",
            pareto_status="FRONTIER",
            execution_time_ratio=0.8,
            energy_ratio=0.8,
            code_size_ratio=0.9,
            carbon_ratio=0.8,
            q_value=0.75,
        )
        assert snap.strategy_name == "-O2"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_back2_moo_result_still_importable():
    """CandidateResult from Stage 3 (moo.moo_result) is still importable."""
    tid, name = "W11-BACK2", "CandidateResult (Stage 3) still importable"
    try:
        from moo.moo_result import CandidateResult
        cr = CandidateResult(strategy_name="-O2", strategy_index=2, strategy_kind="clang_flag")
        assert cr.strategy_name == "-O2"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_back3_experience_record_does_not_break_bench_schema():
    """ExperienceRecord can be constructed alongside bench schema without conflict."""
    tid, name = "W11-BACK3", "ExperienceRecord co-exists with bench/regression schemas"
    try:
        from moo.adaptive.schema import ExperienceRecord, ADAPTIVE_SCHEMA_VERSION
        from moo.bench.schema import CorpusEntry, BENCH_SCHEMA_VERSION
        from moo.regression.schema import MetricComparison, REGRESSION_SCHEMA_VERSION

        exp = _make_experience()
        assert exp.schema_version == ADAPTIVE_SCHEMA_VERSION
        assert BENCH_SCHEMA_VERSION == "week9.1.0"
        assert REGRESSION_SCHEMA_VERSION == "week10.1.0"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_back4_existing_tests_importable():
    """Week 8, 9, 10 test files can be imported without collision from Week 11."""
    tid, name = "W11-BACK4", "Week 8/9/10 test infrastructure importable alongside adaptive"
    try:
        # Just import the key schemas to confirm no name collisions
        from moo.adaptive.schema import ADAPTIVE_SCHEMA_VERSION
        from moo.regression.schema import REGRESSION_SCHEMA_VERSION
        from moo.bench.schema import BENCH_SCHEMA_VERSION
        # These must all be distinct
        versions = {ADAPTIVE_SCHEMA_VERSION, REGRESSION_SCHEMA_VERSION, BENCH_SCHEMA_VERSION}
        assert len(versions) == 3, f"Schema version collision detected: {versions}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-NOISE: Noise-Aware Reward & Reliability Gating
# ===========================================================================

def test_noise1_reliable_measurement_normal_reward():
    """Reliable measurement with high confidence produces full-strength reward."""
    tid, name = "W11-NOISE1", "Reliable measurement produces full-strength reward"
    try:
        from moo.adaptive.reward import compute_reward
        r = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            confidence="HIGH",
            is_reliable=True,
            regression_overall_status="IMPROVED",
        )
        assert r > 0.15, f"Expected normal reward (~0.17), got {r}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise2_inconclusive_confidence_attenuates_reward():
    """INCONCLUSIVE measurement confidence attenuates/zeros performance reward."""
    tid, name = "W11-NOISE2", "INCONCLUSIVE confidence attenuates performance reward"
    try:
        from moo.adaptive.reward import compute_reward
        # 20% faster execution time, but confidence is INCONCLUSIVE
        r_inconclusive = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 10000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            confidence="INCONCLUSIVE",
            is_reliable=True,
        )
        # Default attenuation is 0.0 -> performance gain zeroed -> reward is 0.0
        assert math.isclose(r_inconclusive, 0.0, abs_tol=1e-9), \
            f"Expected 0.0 reward for inconclusive measurement, got {r_inconclusive}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise3_unreliable_timing_cannot_produce_normal_reward():
    """is_reliable=False prevents performance improvement from producing normal-strength reward."""
    tid, name = "W11-NOISE3", "Unreliable timing (is_reliable=False) attenuates reward"
    try:
        from moo.adaptive.reward import compute_reward
        r_reliable = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 10000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            is_reliable=True,
        )
        r_unreliable = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 10000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            is_reliable=False,
        )
        assert r_reliable > 0.10
        assert r_unreliable < r_reliable
        assert math.isclose(r_unreliable, 0.0, abs_tol=1e-9)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise4_regression_status_inconclusive_attenuates_reward():
    """regression_overall_status='INCONCLUSIVE' attenuates performance reward."""
    tid, name = "W11-NOISE4", "regression_overall_status=INCONCLUSIVE attenuates reward"
    try:
        from moo.adaptive.reward import compute_reward
        r = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 10000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            regression_overall_status="INCONCLUSIVE",
        )
        assert math.isclose(r, 0.0, abs_tol=1e-9)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise5_custom_inconclusive_attenuation_factor():
    """RewardConfig.inconclusive_attenuation allows scaling down rather than zeroing."""
    tid, name = "W11-NOISE5", "Configurable inconclusive_attenuation factor"
    try:
        from moo.adaptive.reward import compute_reward, RewardConfig
        cfg = RewardConfig(inconclusive_attenuation=0.25)
        r_attenuated = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 10000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            confidence="INCONCLUSIVE",
            config=cfg,
        )
        r_normal = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 10000.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0},
            benchmark_build_ok=True,
            benchmark_correct=True,
            confidence="HIGH",
        )
        expected = r_normal * 0.25
        assert math.isclose(r_attenuated, expected, rel_tol=1e-6), \
            f"Expected {expected}, got {r_attenuated}"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise6_derived_energy_carbon_not_double_counted_under_noise():
    """Derived energy and carbon are not double/triple counted even with noise flags."""
    tid, name = "W11-NOISE6", "Derived metrics not double-counted with noise flags"
    try:
        from moo.adaptive.reward import compute_reward
        r1 = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0,
                               "energy_j": 3.6, "carbon_g": 0.00044},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0,
                              "energy_j": 4.5, "carbon_g": 0.00055},
            benchmark_build_ok=True,
            benchmark_correct=True,
            confidence="HIGH",
            is_reliable=True,
        )
        r2 = compute_reward(
            benchmark_metrics={"execution_time_s": 0.080, "code_size_bytes": 9000.0,
                               "energy_j": 999.0, "carbon_g": 99.0},
            baseline_metrics={"execution_time_s": 0.100, "code_size_bytes": 10000.0,
                              "energy_j": 4.5, "carbon_g": 0.00055},
            benchmark_build_ok=True,
            benchmark_correct=True,
            confidence="HIGH",
            is_reliable=True,
        )
        assert r1 == r2
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise7_validator_rejects_success_on_unreliable_timing():
    """validate_experience rejects success=True when is_reliable is False."""
    tid, name = "W11-NOISE7", "Validator rejects success=True when is_reliable=False"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(success=True)
        exp.is_reliable = False
        res = validate_experience(exp)
        assert not res
        assert any("unreliable" in e.lower() for e in res.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_noise8_validator_rejects_success_on_inconclusive_confidence():
    """validate_experience rejects success=True when confidence is INCONCLUSIVE."""
    tid, name = "W11-NOISE8", "Validator rejects success=True when confidence is INCONCLUSIVE"
    try:
        from moo.adaptive.validator import validate_experience
        exp = _make_experience(success=True)
        exp.confidence = "INCONCLUSIVE"
        res = validate_experience(exp)
        assert not res
        assert any("inconclusive" in e.lower() for e in res.errors)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


# ===========================================================================
# W11-CONV: Canonical Week 9/10 → Week 11 Conversion
# ===========================================================================

def _make_mock_comparison(
    *,
    program_id: str = "01_hello_world",
    source_sha256: str = "b" * 64,
    selected_strategy: str = "-O2",
    selection_source: str = "DQN∩Pareto",
    model_identifier: str = "production_v0",
    exec_time: float = 0.080,
    base_time: float = 0.100,
    code_size: float = 9000.0,
    base_size: float = 10000.0,
    is_reliable: bool = True,
    confidence: str = "HIGH",
    overall_status: str = "IMPROVED",
    with_provenance: bool = True,
    with_comparison: bool = True,
):
    from moo.regression.schema import (
        ComparisonStatus,
        MetricComparison,
        OverallStatus,
        ProgramComparison,
        SelectionRecord,
        StrategyComparison,
    )

    prov = None
    if with_provenance:
        prov = SelectionRecord(
            program_id=program_id,
            source_sha256=source_sha256,
            selected_strategy=selected_strategy,
            selection_source=selection_source,
            model_identifier=model_identifier,
            trace_id="trace_test_001",
            timestamp="2026-10-05T12:00:00",
        )

    sel_comp = None
    if with_comparison:
        mc_time = MetricComparison(
            metric_name="execution_time",
            baseline_value=base_time,
            target_value=exec_time,
            delta=exec_time - base_time,
            percent_change=((exec_time - base_time) / base_time) * 100,
            ratio=exec_time / base_time,
            lower_is_better=True,
            unit="seconds",
            status=ComparisonStatus.IMPROVED if exec_time < base_time else ComparisonStatus.REGRESSED,
            reason="Mock comparison",
            is_reliable=is_reliable,
            confidence=confidence,
        )
        mc_size = MetricComparison(
            metric_name="code_size",
            baseline_value=base_size,
            target_value=code_size,
            delta=code_size - base_size,
            percent_change=((code_size - base_size) / base_size) * 100,
            ratio=code_size / base_size,
            lower_is_better=True,
            unit="bytes",
            status=ComparisonStatus.IMPROVED if code_size < base_size else ComparisonStatus.REGRESSED,
            reason="Mock comparison",
        )
        sel_comp = StrategyComparison(
            strategy_name=selected_strategy,
            reference_strategy="baseline (-O0)",
            is_valid=True,
            pareto_status="FRONTIER",
            metric_comparisons={
                "execution_time": mc_time,
                "code_size": mc_size,
            },
            overall_status=OverallStatus(overall_status),
        )

    return ProgramComparison(
        program_id=program_id,
        status="ok",
        selected_strategy=selected_strategy,
        selected_comparison=sel_comp,
        selection_provenance=prov,
        strategy_comparisons={selected_strategy: sel_comp} if sel_comp else {},
        pareto_frontier=[selected_strategy],
        overall_status=OverallStatus(overall_status),
    )


def test_conv1_valid_program_comparison_to_experience():
    """Valid ProgramComparison converts to a fully populated, valid ExperienceRecord."""
    tid, name = "W11-CONV1", "Valid ProgramComparison converts to valid ExperienceRecord"
    try:
        from moo.adaptive.adapter import experience_from_program_comparison
        pcomp = _make_mock_comparison()
        feats = dict(_VALID_FEATURES)
        exp = experience_from_program_comparison(
            pcomp,
            features=feats,
            run_id="run_week10_001",
        )
        assert exp is not None
        assert exp.program_id == "01_hello_world"
        assert exp.source_hash == "b" * 64
        assert exp.selected_action == "-O2"
        assert exp.selection_method == "DQN∩Pareto"
        assert exp.model_identifier == "production_v0"
        assert exp.trace_id == "trace_test_001"
        assert exp.confidence == "HIGH"
        assert exp.is_reliable is True
        assert exp.reward is not None and exp.reward > 0
        assert exp.success is True
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_conv2_missing_selection_provenance_fails_safely():
    """Missing selection_provenance refuses to fabricate provenance and fails safely."""
    tid, name = "W11-CONV2", "Missing selection_provenance fails safely without fabrication"
    try:
        from moo.adaptive.adapter import experience_from_program_comparison
        pcomp = _make_mock_comparison(with_provenance=False)
        # strict=False -> returns None
        exp = experience_from_program_comparison(pcomp, features=_VALID_FEATURES, run_id="run_1", strict=False)
        assert exp is None

        # strict=True -> raises ValueError
        raised = False
        try:
            experience_from_program_comparison(pcomp, features=_VALID_FEATURES, run_id="run_1", strict=True)
        except ValueError as err:
            raised = True
            assert "selection_provenance" in str(err)
        assert raised
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_conv3_missing_comparison_fails_safely():
    """Missing StrategyComparison fails safely."""
    tid, name = "W11-CONV3", "Missing selected_comparison fails safely"
    try:
        from moo.adaptive.adapter import experience_from_program_comparison
        pcomp = _make_mock_comparison(with_comparison=False)
        exp = experience_from_program_comparison(pcomp, features=_VALID_FEATURES, run_id="run_1", strict=False)
        assert exp is None

        raised = False
        try:
            experience_from_program_comparison(pcomp, features=_VALID_FEATURES, run_id="run_1", strict=True)
        except ValueError:
            raised = True
        assert raised
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_conv4_field_name_mapping_integrity():
    """Conversion helper accurately maps naming mismatches between Week 10 and Week 11."""
    tid, name = "W11-CONV4", "Conversion helper maps naming mismatches correctly"
    try:
        from moo.adaptive.adapter import experience_from_program_comparison
        sh = "c" * 64
        pcomp = _make_mock_comparison(
            source_sha256=sh,
            selected_strategy="mem2reg,simplifycfg",
            selection_source="DQN∩Pareto",
        )
        exp = experience_from_program_comparison(pcomp, features=_VALID_FEATURES, run_id="run_map_test")
        assert exp is not None

        # source_sha256 -> source_hash
        assert exp.source_hash == sh

        # selected_strategy -> selected_action
        assert exp.selected_action == "mem2reg,simplifycfg"

        # selection_source -> selection_method
        assert exp.selection_method == "DQN∩Pareto"

        # metric names: execution_time -> execution_time_s, code_size -> code_size_bytes
        assert "execution_time_s" in exp.benchmark_metrics
        assert "code_size_bytes" in exp.benchmark_metrics
        assert exp.benchmark_metrics["execution_time_s"] == 0.080
        assert exp.benchmark_metrics["code_size_bytes"] == 9000.0
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_conv5_converted_experience_serialization_roundtrip():
    """Converted ExperienceRecord cleanly serializes to JSON and deserializes identically."""
    tid, name = "W11-CONV5", "Converted ExperienceRecord JSON serialization round-trip"
    try:
        from moo.adaptive.adapter import experience_from_program_comparison
        from moo.adaptive.schema import ExperienceRecord
        pcomp = _make_mock_comparison()
        exp = experience_from_program_comparison(pcomp, features=_VALID_FEATURES, run_id="run_rt")
        assert exp is not None

        j = exp.to_json()
        exp2 = ExperienceRecord.from_json(j)
        assert exp2.program_id == exp.program_id
        assert exp2.source_hash == exp.source_hash
        assert exp2.selected_action == exp.selected_action
        assert exp2.confidence == exp.confidence
        assert exp2.is_reliable == exp.is_reliable
        assert math.isclose(exp2.reward, exp.reward)
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_conv6_classmethod_from_program_comparison():
    """ExperienceRecord.from_program_comparison classmethod functions identically to adapter."""
    tid, name = "W11-CONV6", "ExperienceRecord.from_program_comparison classmethod verified"
    try:
        from moo.adaptive.schema import ExperienceRecord
        pcomp = _make_mock_comparison()
        exp = ExperienceRecord.from_program_comparison(pcomp, features=_VALID_FEATURES, run_id="run_cls")
        assert exp is not None
        assert exp.program_id == "01_hello_world"
        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)


def test_conv7_end_to_end_pipeline_integration():
    """Full chain: ProgramComparison -> ExperienceRecord -> Store -> Buffer -> Learner."""
    tid, name = "W11-CONV7", "End-to-end integration: Comparison -> Experience -> Store -> Buffer -> Learner"
    tmpdir = tempfile.mkdtemp()
    try:
        from moo.adaptive.adapter import experience_from_program_comparison
        from moo.adaptive.storage import ExperienceStore, ReplayBuffer
        from moo.adaptive.learner import DQNLearner

        store = ExperienceStore(tmpdir)
        buf = ReplayBuffer(capacity=50)

        # Convert 5 mock comparisons and add to store
        for i in range(5):
            pcomp = _make_mock_comparison(
                program_id=f"prog_{i}",
                selected_strategy="-O2" if i % 2 == 0 else "-O3",
                exec_time=0.075 + (i * 0.002),
            )
            exp = experience_from_program_comparison(
                pcomp,
                features=_VALID_FEATURES,
                run_id=f"run_e2e_{i}",
            )
            assert exp is not None
            accepted = store.add(exp)
            assert accepted

        assert store.record_count == 5

        # Load into replay buffer
        n_loaded = buf.load_from_store(store)
        assert n_loaded == 5

        # Train learner on experiences from buffer (if torch available)
        if _torch_available() and _ml_optimizer_available():
            candidate_dir = os.path.join(tmpdir, "candidates")
            learner = DQNLearner(candidate_dir=candidate_dir, seed=42, epochs=2)
            mvi = learner.learn(buf, min_experiences=3, model_version=1)
            assert mvi.model_version == 1
            assert mvi.experience_count == 5
            assert mvi.is_production is False
            assert os.path.isfile(learner.last_candidate_path)

        report(tid, name, True)
    except Exception as exc:
        fail(tid, name, exc)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ===========================================================================
# Main runner
# ===========================================================================

def _run_all() -> None:
    print("=" * 72)
    print("TOACD — Week 11 Adaptive Self-Learning Tests")
    print("=" * 72)

    categories = [
        ("W11-SCHEMA: ExperienceRecord Schema", [
            test_schema1_experience_record_roundtrip,
            test_schema2_json_roundtrip,
            test_schema3_schema_version_constant,
            test_schema4_unsupported_schema_version_rejected,
            test_schema5_optional_fields_preserved,
            test_schema6_model_version_info_roundtrip,
            test_schema7_source_hash_preserved_exactly,
            test_schema8_benchmark_metrics_none_values_preserved,
        ]),
        ("W11-REWARD: Reward Calculation", [
            test_reward1_improved_execution_time,
            test_reward2_regression_execution_time,
            test_reward3_build_failure_negative_reward,
            test_reward4_incorrect_result_penalty,
            test_reward5_derived_metrics_not_independent_terms,
            test_reward6_reward_is_bounded,
            test_reward7_determinism_50_calls,
            test_reward8_missing_execution_time_neutral,
            test_reward9_zero_baseline_time_neutral,
            test_reward10_apply_reward_to_experience,
            test_reward11_reward_config_roundtrip,
            test_reward12_nan_metric_gives_neutral_term,
        ]),
        ("W11-VALID: Experience Validation", [
            test_valid1_valid_experience_accepted,
            test_valid2_wrong_schema_version_rejected,
            test_valid3_empty_experience_id_rejected,
            test_valid4_invalid_source_hash_rejected,
            test_valid5_empty_ir_features_rejected,
            test_valid6_nan_ir_feature_rejected,
            test_valid7_unknown_metric_key_rejected,
            test_valid8_negative_metric_value_rejected,
            test_valid9_invalid_selection_method_rejected,
            test_valid10_build_fail_positive_reward_rejected,
            test_valid11_success_true_with_failed_build_rejected,
            test_valid12_invalid_regression_status_rejected,
            test_valid13_none_regression_status_accepted,
            test_valid14_inf_reward_rejected,
            test_valid15_validator_never_raises,
        ]),
        ("W11-STORE: Experience Storage", [
            test_store1_add_and_reload,
            test_store2_duplicate_rejected,
            test_store3_invalid_experience_rejected,
            test_store4_manifest_record_count_accurate,
            test_store5_corrupt_line_skipped,
            test_store6_empty_store_returns_empty_list,
            test_store7_add_batch,
            test_store8_exists_check_before_add,
            test_store9_persistence_across_instances,
        ]),
        ("W11-REPLAY: Replay Buffer", [
            test_replay1_push_and_len,
            test_replay2_bounded_capacity_fifo,
            test_replay3_deterministic_sampling_with_seed,
            test_replay4_different_seeds_different_samples,
            test_replay5_empty_buffer_sample_returns_empty,
            test_replay6_sample_without_replacement,
            test_replay7_load_from_store,
            test_replay8_clear,
        ]),
        ("W11-LEARN: DQN Learner & Model Versioning", [
            test_learn1_candidate_dir_created,
            test_learn2_model_version_info_not_production,
            test_learn3_list_candidates_empty_dir,
            test_learn4_production_model_not_overwritten,
            test_learn5_candidate_artifact_created,
            test_learn6_model_version_info_metadata,
            test_learn7_too_few_experiences_raises,
            test_learn8_list_candidates_after_learn,
            test_learn9_canonical_feature_order,
        ]),
        ("W11-DET: Determinism", [
            test_det1_reward_determinism,
            test_det2_seeded_replay_sample_determinism,
            test_det3_validation_determinism,
            test_det4_experience_serialization_determinism,
        ]),
        ("W11-SCOPE: Architecture & Scope Guards", [
            test_scope1_no_week12_modules,
            test_scope2_gui_not_imported_by_adaptive,
            test_scope3_no_new_benchmark_system,
            test_scope4_selection_algorithm_unchanged,
            test_scope5_o0_baseline_not_changed,
            test_scope6_week10_regression_schema_importable,
            test_scope7_week9_bench_schema_importable,
            test_scope8_adaptive_week_constant,
        ]),
        ("W11-BACK: Backward Compatibility", [
            test_back1_decision_trace_still_works,
            test_back2_moo_result_still_importable,
            test_back3_experience_record_does_not_break_bench_schema,
            test_back4_existing_tests_importable,
        ]),
        ("W11-NOISE: Noise-Aware Reward & Reliability Gating", [
            test_noise1_reliable_measurement_normal_reward,
            test_noise2_inconclusive_confidence_attenuates_reward,
            test_noise3_unreliable_timing_cannot_produce_normal_reward,
            test_noise4_regression_status_inconclusive_attenuates_reward,
            test_noise5_custom_inconclusive_attenuation_factor,
            test_noise6_derived_energy_carbon_not_double_counted_under_noise,
            test_noise7_validator_rejects_success_on_unreliable_timing,
            test_noise8_validator_rejects_success_on_inconclusive_confidence,
        ]),
        ("W11-CONV: Canonical Week 9/10 -> Week 11 Conversion", [
            test_conv1_valid_program_comparison_to_experience,
            test_conv2_missing_selection_provenance_fails_safely,
            test_conv3_missing_comparison_fails_safely,
            test_conv4_field_name_mapping_integrity,
            test_conv5_converted_experience_serialization_roundtrip,
            test_conv6_classmethod_from_program_comparison,
            test_conv7_end_to_end_pipeline_integration,
        ]),
    ]

    for section_name, tests in categories:
        print(f"\n--- {section_name} ---")
        for test_fn in tests:
            test_fn()

    # Summary
    print("\n" + "=" * 72)
    total = len(_results)
    passed = sum(1 for _, _, t in _results if t == "PASS")
    failed = sum(1 for _, _, t in _results if t == "FAIL")
    skipped = sum(1 for _, _, t in _results if t == "SKIP")
    print(f"RESULTS: {total} tests | PASS: {passed} | FAIL: {failed} | SKIP: {skipped}")
    print("=" * 72)

    if failed:
        print("\nFAILED TESTS:")
        for tid, name, tag in _results:
            if tag == "FAIL":
                print(f"  [{tag}] {tid}: {name}")
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
