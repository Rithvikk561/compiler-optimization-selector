"""
moo/measurement_quality.py — Measurement quality assessment and reporting
for TOACD MOO results.

Week 5 Change #2: Observability and reporting layer.

Design principles:
- Pure, defensive helper functions that NEVER raise on missing or malformed inputs.
- Observability only: does NOT influence Pareto analysis, normalization,
  objective formulas, AI selector, or candidate filtering.
- Status precedence:
    unreliable > unknown > reliable
- Missing values stay None.  Legacy reports without Week 5 metadata are marked
  with status="unknown" and status_source="legacy_missing".
"""

from __future__ import annotations

from typing import Any, Optional


def assess_measurement(measurement: Optional[dict]) -> dict:
    """
    Assess the quality and reliability of a single measurement dictionary.

    Parameters
    ----------
    measurement : dict or None
        Serialized MeasurementResult dictionary (from MeasurementResult.to_dict()),
        or None if no measurement was taken.

    Returns
    -------
    dict
        Assessment dictionary with:
        - median_s: float or None
        - cv: float or None
        - n_samples: int or None
        - n_timeouts: int or None
        - n_errors: int or None
        - timing_is_reliable: bool or None
        - status: "reliable" | "unreliable" | "unknown"
        - status_source: "recorded" | "legacy_missing"
        - warnings: list[str]
    """
    if not isinstance(measurement, dict):
        return {
            "median_s": None,
            "cv": None,
            "n_samples": None,
            "n_timeouts": None,
            "n_errors": None,
            "timing_is_reliable": None,
            "status": "unknown",
            "status_source": "legacy_missing",
            "warnings": [
                "No measurement recorded.",
                "Timing reliability is unknown.",
            ],
        }

    # Extract timing sub-dict safely
    timing_dict = measurement.get("timing")
    if not isinstance(timing_dict, dict):
        timing_dict = {}

    median_s = timing_dict.get("median_s")
    if median_s is not None and not isinstance(median_s, (int, float)):
        median_s = None

    n_samples = timing_dict.get("n_samples")
    if n_samples is not None and not isinstance(n_samples, int):
        n_samples = None

    # Check whether Week 5 quality metadata is recorded
    # Week 5 measurements explicitly include the 'timing_is_reliable' key
    has_recorded_metadata = "timing_is_reliable" in measurement or "n_timeouts" in measurement

    if has_recorded_metadata:
        status_source = "recorded"
        cv = timing_dict.get("cv")
        if cv is not None and not isinstance(cv, (int, float)):
            cv = None

        n_timeouts = measurement.get("n_timeouts")
        if n_timeouts is not None and not isinstance(n_timeouts, int):
            n_timeouts = None

        n_errors = measurement.get("n_errors")
        if n_errors is not None and not isinstance(n_errors, int):
            n_errors = None

        raw_rel = measurement.get("timing_is_reliable")
        if raw_rel is True:
            timing_is_reliable = True
            status = "reliable"
        elif raw_rel is False:
            timing_is_reliable = False
            status = "unreliable"
        else:
            timing_is_reliable = None
            status = "unknown"
    else:
        # Legacy/pre-Week-5 report: missing metadata MUST stay None
        status_source = "legacy_missing"
        cv = None
        n_timeouts = None
        n_errors = None
        timing_is_reliable = None
        status = "unknown"

    # Formulate warnings based on recorded facts
    warnings: list[str] = []
    if status == "reliable":
        warnings = []
    elif status == "unreliable":
        cv_str = f"CV {cv * 100:.1f}%" if cv is not None else "CV unknown"
        samples_str = f"{n_samples} samples" if n_samples is not None else "unknown samples"
        timeouts_str = f"{n_timeouts} timeouts" if n_timeouts is not None else "unknown timeouts"
        errors_str = f"{n_errors} errors" if n_errors is not None else "unknown errors"

        warnings.append(
            f"Timing: UNRELIABLE ({cv_str}, {samples_str}, {timeouts_str}, {errors_str})"
        )
        warnings.append("Runtime comparisons may not be trustworthy.")
    else:  # unknown
        if status_source == "legacy_missing":
            warnings.append("Measurement quality metadata missing (legacy report).")
            warnings.append("Timing reliability is unknown.")
        elif not timing_dict or n_samples == 0:
            warnings.append("No valid timing samples were recorded.")
            warnings.append("Timing reliability is unknown.")
        else:
            warnings.append("Timing reliability could not be determined.")
            warnings.append("Timing reliability is unknown.")

    return {
        "median_s": median_s,
        "cv": cv,
        "n_samples": n_samples,
        "n_timeouts": n_timeouts,
        "n_errors": n_errors,
        "timing_is_reliable": timing_is_reliable,
        "status": status,
        "status_source": status_source,
        "warnings": warnings,
    }


def build_measurement_quality(
    baseline_measurement: Any,
    candidates: Any,
) -> dict:
    """
    Build the top-level measurement_quality block for MOOEvaluationResult.

    Parameters
    ----------
    baseline_measurement : BaselineMeasurement, dict, or None
        Baseline evaluation data.
    candidates : list[CandidateResult], list[dict], or None
        List of candidate optimization strategies.

    Returns
    -------
    dict
        Structured measurement quality dictionary according to Schema v1.
    """
    # 1. Assess baseline
    if hasattr(baseline_measurement, "measurement"):
        m_base = baseline_measurement.measurement
    elif isinstance(baseline_measurement, dict) and "measurement" in baseline_measurement:
        m_base = baseline_measurement["measurement"]
    elif isinstance(baseline_measurement, dict):
        m_base = baseline_measurement
    else:
        m_base = None

    base_assessment = assess_measurement(m_base)

    # 2. Assess candidates (only those that actually contain a measurement)
    candidate_assessments: list[dict] = []
    if candidates and hasattr(candidates, "__iter__"):
        for cand in candidates:
            if hasattr(cand, "measurement"):
                m_cand = cand.measurement
                s_name = getattr(cand, "strategy_name", "")
                s_idx = getattr(cand, "strategy_index", 0)
            elif isinstance(cand, dict):
                m_cand = cand.get("measurement")
                s_name = cand.get("strategy_name", "")
                s_idx = cand.get("strategy_index", 0)
            else:
                m_cand = None
                s_name = ""
                s_idx = 0

            # Only assess candidates that actually contain a measurement
            if m_cand is not None:
                assessed = assess_measurement(m_cand)
                cand_entry = {
                    "strategy_name": s_name,
                    "strategy_index": s_idx,
                    **assessed,
                }
                candidate_assessments.append(cand_entry)

    # 3. Counts over assessed candidates
    n_reliable = sum(1 for c in candidate_assessments if c.get("status") == "reliable")
    n_unreliable = sum(1 for c in candidate_assessments if c.get("status") == "unreliable")
    n_unknown = sum(1 for c in candidate_assessments if c.get("status") == "unknown")

    # 4. Overall status precedence:
    # - any unreliable -> "unreliable"
    # - otherwise any unknown -> "unknown"
    # - otherwise -> "reliable"
    all_statuses = [base_assessment.get("status")] + [
        c.get("status") for c in candidate_assessments
    ]

    if any(s == "unreliable" for s in all_statuses):
        overall_status = "unreliable"
    elif any(s == "unknown" for s in all_statuses):
        overall_status = "unknown"
    elif all_statuses and all(s == "reliable" for s in all_statuses):
        overall_status = "reliable"
    else:
        overall_status = "unknown"

    # 5. Top-level warnings
    top_warnings: list[str] = []
    if overall_status == "unreliable":
        if base_assessment.get("status") == "unreliable":
            top_warnings.append(
                "Baseline timing is unreliable; runtime comparisons may not be trustworthy."
            )
        if n_unreliable > 0:
            top_warnings.append(
                f"{n_unreliable} candidate strategy timing measurement(s) are unreliable."
            )
    elif overall_status == "unknown":
        if base_assessment.get("status") == "unknown":
            top_warnings.append("Baseline timing reliability is unknown.")
        if n_unknown > 0:
            top_warnings.append(
                f"{n_unknown} candidate strategy timing measurement(s) have unknown reliability."
            )
        elif not candidate_assessments and base_assessment.get("status") == "unknown":
            top_warnings.append("No valid measurement data available.")

    return {
        "schema_version": 1,
        "status": overall_status,
        "baseline": base_assessment,
        "candidates": candidate_assessments,
        "n_reliable": n_reliable,
        "n_unreliable": n_unreliable,
        "n_unknown": n_unknown,
        "warnings": top_warnings,
    }
