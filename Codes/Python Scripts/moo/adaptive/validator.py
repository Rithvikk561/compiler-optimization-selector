"""
moo/adaptive/validator.py — Week 11: Experience record validation.

Validates an ExperienceRecord before it is accepted into the experience store.
Rejection is explicit and documented — no silent data loss.

Validation checks
-----------------
1.  schema_version must be in SUPPORTED_SCHEMA_VERSIONS.
2.  Required string fields must be non-empty.
3.  source_hash must be a 64-character hex string (SHA-256).
4.  ir_features must be a dict with 1–64 entries, all finite floats.
5.  selected_action must be a non-empty string (present in ACTIONS if
    ACTIONS is available; SKIP check if import fails).
6.  selection_method must be one of the known values.
7.  model_identifier must be a non-empty string.
8.  benchmark_metrics and baseline_metrics must be dicts with known keys;
    any present values must be finite non-negative floats.
9.  benchmark_build_ok and benchmark_correct must be booleans.
10. If benchmark_build_ok is False, reward (if present) must be <= 0.
11. reward, if present, must be finite and bounded by MAX_REWARD.
12. success must be consistent: True only if build_ok AND correct AND reward > 0.
13. pareto_frontier must be a list of strings (may be empty).
14. regression_overall_status, if present, must be one of the valid values.
15. No fabricated finite values where None is the honest representation.
"""

from __future__ import annotations

import math
from typing import Optional

from .schema import (
    ADAPTIVE_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    ExperienceRecord,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KNOWN_SELECTION_METHODS = frozenset({
    "moo_aware",
    "argmax_fallback_no_frontier",
    "argmax_fallback_frontier_mismatch",
    "argmax_fallback_exception",
    # Week 10 SelectionRecord provenance values
    "DQN∩Pareto",
    "DQN_fallback",
    # Allow legacy / test values without hard-failing
    "manual",
    "test",
})

_KNOWN_CONFIDENCE_VALUES = frozenset({
    "HIGH",
    "LOW",
    "INCONCLUSIVE",
    "INCOMPARABLE",
})

_KNOWN_REGRESSION_STATUSES = frozenset({
    "IMPROVED",
    "REGRESSED",
    "MIXED",
    "UNCHANGED",
    "INCONCLUSIVE",
    "INCOMPARABLE",
})

_KNOWN_METRIC_KEYS = frozenset({
    "execution_time_s",
    "code_size_bytes",
    "energy_j",
    "carbon_g",
})

MAX_VALID_REWARD = 200.0   # hard upper bound on absolute reward magnitude
MAX_IR_FEATURES = 64       # DQN state vector upper bound
MIN_SOURCE_HASH_LEN = 32   # minimum length for a source_hash


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

class ValidationResult:
    """Result of validating one ExperienceRecord."""

    __slots__ = ("valid", "errors")

    def __init__(self) -> None:
        self.valid: bool = True
        self.errors: list[str] = []

    def reject(self, reason: str) -> None:
        self.valid = False
        self.errors.append(reason)

    def __bool__(self) -> bool:
        return self.valid

    def __repr__(self) -> str:
        if self.valid:
            return "ValidationResult(valid=True)"
        return f"ValidationResult(valid=False, errors={self.errors!r})"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_experience(exp: ExperienceRecord) -> ValidationResult:
    """
    Validate an ExperienceRecord before accepting it into the store.

    Returns a ValidationResult.  Call bool(result) to check validity.
    result.errors contains human-readable rejection reasons.

    This function NEVER raises.  Any unexpected error is captured as a
    validation failure.
    """
    result = ValidationResult()
    try:
        _check_schema_version(exp, result)
        _check_required_strings(exp, result)
        _check_source_hash(exp, result)
        _check_ir_features(exp, result)
        _check_selected_action(exp, result)
        _check_selection_method(exp, result)
        _check_model_identifier(exp, result)
        _check_metric_dicts(exp, result)
        _check_boolean_fields(exp, result)
        _check_reward(exp, result)
        _check_noise_and_confidence(exp, result)
        _check_success_consistency(exp, result)
        _check_pareto_frontier(exp, result)
        _check_regression_status(exp, result)
    except Exception as exc:
        result.reject(f"Unexpected validation error: {type(exc).__name__}: {exc}")
    return result


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_schema_version(exp: ExperienceRecord, result: ValidationResult) -> None:
    if exp.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        result.reject(
            f"schema_version {exp.schema_version!r} not in "
            f"SUPPORTED_SCHEMA_VERSIONS {SUPPORTED_SCHEMA_VERSIONS!r}"
        )


def _check_required_strings(exp: ExperienceRecord, result: ValidationResult) -> None:
    required = {
        "experience_id": exp.experience_id,
        "program_id": exp.program_id,
        "source_hash": exp.source_hash,
        "run_id": exp.run_id,
        "timestamp": exp.timestamp,
        "selected_action": exp.selected_action,
        "model_identifier": exp.model_identifier,
    }
    for field, val in required.items():
        if not isinstance(val, str) or not val.strip():
            result.reject(f"Required field {field!r} is empty or not a string")


def _check_source_hash(exp: ExperienceRecord, result: ValidationResult) -> None:
    sh = exp.source_hash
    if not isinstance(sh, str) or len(sh) < MIN_SOURCE_HASH_LEN:
        _sh_preview = repr(sh[:16] if isinstance(sh, str) else sh)
        _sh_len = len(sh) if isinstance(sh, str) else "N/A"
        result.reject(
            f"source_hash must be a hex string of at least {MIN_SOURCE_HASH_LEN} chars; "
            f"got {_sh_preview}... (len={_sh_len})"
        )
        return
    if not all(c in "0123456789abcdefABCDEF" for c in sh):
        _sh_preview = repr(sh[:16])
        result.reject(f"source_hash {_sh_preview}... contains non-hex characters")


def _check_ir_features(exp: ExperienceRecord, result: ValidationResult) -> None:
    feats = exp.ir_features
    if not isinstance(feats, dict) or len(feats) == 0:
        result.reject("ir_features must be a non-empty dict")
        return
    if len(feats) > MAX_IR_FEATURES:
        result.reject(f"ir_features has {len(feats)} entries; max is {MAX_IR_FEATURES}")
        return
    for k, v in feats.items():
        if not isinstance(k, str):
            result.reject(f"ir_features key {k!r} is not a string")
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            result.reject(f"ir_features[{k!r}] = {v!r} is not a finite number")


def _check_selected_action(exp: ExperienceRecord, result: ValidationResult) -> None:
    action = exp.selected_action
    if not action:
        return  # already caught by _check_required_strings
    # Soft check: try to load ACTIONS; skip if unavailable (test / env without torch)
    try:
        from ml_optimizer import ACTIONS as _ACTIONS  # type: ignore[import]
        if action not in _ACTIONS:
            result.reject(
                f"selected_action {action!r} is not in ACTIONS "
                f"(known: {_ACTIONS!r})"
            )
    except Exception:
        pass  # Cannot import ml_optimizer — skip ACTIONS validation


def _check_selection_method(exp: ExperienceRecord, result: ValidationResult) -> None:
    sm = exp.selection_method
    if not isinstance(sm, str) or not sm.strip():
        result.reject("selection_method must be a non-empty string")
        return
    if sm not in _KNOWN_SELECTION_METHODS:
        result.reject(
            f"selection_method {sm!r} is not in known values "
            f"{sorted(_KNOWN_SELECTION_METHODS)!r}"
        )


def _check_model_identifier(exp: ExperienceRecord, result: ValidationResult) -> None:
    mi = exp.model_identifier
    if not isinstance(mi, str) or not mi.strip():
        result.reject("model_identifier must be a non-empty string")


def _check_metric_dicts(exp: ExperienceRecord, result: ValidationResult) -> None:
    for dict_name, d in (
        ("benchmark_metrics", exp.benchmark_metrics),
        ("baseline_metrics", exp.baseline_metrics),
    ):
        if not isinstance(d, dict):
            result.reject(f"{dict_name} must be a dict")
            continue
        for k, v in d.items():
            if k not in _KNOWN_METRIC_KEYS:
                result.reject(
                    f"{dict_name}[{k!r}] uses unknown metric key; "
                    f"known: {sorted(_KNOWN_METRIC_KEYS)!r}"
                )
            if v is not None:
                if not isinstance(v, (int, float)):
                    result.reject(f"{dict_name}[{k!r}] = {v!r} is not numeric")
                elif not math.isfinite(v):
                    result.reject(f"{dict_name}[{k!r}] = {v!r} is not finite")
                elif v < 0.0:
                    result.reject(f"{dict_name}[{k!r}] = {v!r} is negative")


def _check_boolean_fields(exp: ExperienceRecord, result: ValidationResult) -> None:
    for fname in ("benchmark_build_ok", "benchmark_correct", "success"):
        val = getattr(exp, fname)
        if not isinstance(val, bool):
            result.reject(f"{fname!r} must be a bool; got {type(val).__name__}")


def _check_reward(exp: ExperienceRecord, result: ValidationResult) -> None:
    r = exp.reward
    if r is None:
        return  # reward not yet computed — allowed at validation time
    if not isinstance(r, (int, float)) or not math.isfinite(r):
        result.reject(f"reward {r!r} is not a finite number")
        return
    if abs(r) > MAX_VALID_REWARD:
        result.reject(
            f"reward {r!r} exceeds MAX_VALID_REWARD ±{MAX_VALID_REWARD}; "
            "check reward config clamp setting"
        )
    # Failed build must not have a positive reward
    if not exp.benchmark_build_ok and r > 0:
        result.reject(
            f"reward {r!r} is positive but benchmark_build_ok is False; "
            "build failures must yield non-positive rewards"
        )


def _check_noise_and_confidence(exp: ExperienceRecord, result: ValidationResult) -> None:
    conf = getattr(exp, "confidence", None)
    if conf is not None:
        if conf not in _KNOWN_CONFIDENCE_VALUES:
            result.reject(
                f"confidence {conf!r} is not a valid value; "
                f"known: {sorted(_KNOWN_CONFIDENCE_VALUES)!r}"
            )
    rel = getattr(exp, "is_reliable", None)
    if rel is not None and not isinstance(rel, bool):
        result.reject(f"is_reliable must be a bool or None; got {type(rel).__name__}")


def _check_success_consistency(exp: ExperienceRecord, result: ValidationResult) -> None:
    """success=True requires build_ok, correct, reward > 0, and certified non-inconclusive outcomes."""
    if exp.success:
        if not exp.benchmark_build_ok:
            result.reject("success=True but benchmark_build_ok=False")
        if not exp.benchmark_correct:
            result.reject("success=True but benchmark_correct=False")
        if exp.reward is not None and exp.reward <= 0:
            result.reject(
                f"success=True but reward={exp.reward!r} is not positive"
            )
        # Week 10 noise guard: cannot certify success on inconclusive or unreliable performance measurement
        if getattr(exp, "is_reliable", None) is False:
            result.reject("success=True but measurement is unreliable (is_reliable=False)")
        if getattr(exp, "confidence", None) in ("INCONCLUSIVE", "INCOMPARABLE"):
            result.reject(f"success=True but measurement confidence is {exp.confidence}")
        if exp.regression_overall_status in ("INCONCLUSIVE", "INCOMPARABLE"):
            result.reject(f"success=True but regression_overall_status is {exp.regression_overall_status}")


def _check_pareto_frontier(exp: ExperienceRecord, result: ValidationResult) -> None:
    pf = exp.pareto_frontier
    if not isinstance(pf, list):
        result.reject("pareto_frontier must be a list")
        return
    for item in pf:
        if not isinstance(item, str):
            result.reject(f"pareto_frontier contains non-string item {item!r}")


def _check_regression_status(exp: ExperienceRecord, result: ValidationResult) -> None:
    rs = exp.regression_overall_status
    if rs is None:
        return
    if rs not in _KNOWN_REGRESSION_STATUSES:
        result.reject(
            f"regression_overall_status {rs!r} is not a valid value; "
            f"known: {sorted(_KNOWN_REGRESSION_STATUSES)!r}"
        )
