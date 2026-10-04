"""
moo/regression/historical.py — Historical run-to-run benchmark regression comparison.

Compares benchmark outputs across different runs (e.g. earlier git commit vs current,
or baseline test suite vs regression test suite) using Week 9 structured ProgramRecords.
Enforces source identity guards (SHA-256) and environment compatibility guards.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Optional, Sequence

from .comparator import (
    KNOWN_METRIC_SPECS,
    extract_metrics_from_baseline,
    extract_metrics_from_candidate,
)
from .detector import DEFAULT_THRESHOLDS, RegressionThresholds, derive_overall_status, detect_metric_change
from .schema import (
    HistoricalComparison,
    HistoricalProgramComparison,
    MetricComparison,
    OverallStatus,
)


def _index_records_by_id(records: Sequence[Any]) -> tuple[dict[str, Any], Optional[str]]:
    """Index ProgramRecord objects or dicts by program_id and infer run_id."""
    index: dict[str, Any] = {}
    inferred_run_id: Optional[str] = None
    for r in records:
        if hasattr(r, "to_dict"):
            d = r.to_dict()
        elif isinstance(r, dict):
            d = r
        else:
            continue

        pid = d.get("program_id")
        if pid:
            index[str(pid)] = d
            if inferred_run_id is None and d.get("run_id"):
                inferred_run_id = str(d.get("run_id"))

    return index, inferred_run_id


def _get_record_sha(d: dict[str, Any]) -> Optional[str]:
    """Extract source SHA-256 from record or corpus_entry."""
    ce = d.get("corpus_entry")
    if isinstance(ce, dict) and ce.get("source_sha256"):
        return str(ce.get("source_sha256"))
    if d.get("source_sha256"):
        return str(d.get("source_sha256"))
    return None


def _check_environment_compatibility(
    prev_manifest: Optional[dict[str, Any]],
    curr_manifest: Optional[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Verify toolchain and platform compatibility between benchmark runs."""
    if not prev_manifest or not curr_manifest:
        return True, []

    mismatches: list[str] = []

    # Platform check
    prev_plat = prev_manifest.get("platform", {})
    curr_plat = curr_manifest.get("platform", {})
    if prev_plat.get("system") and curr_plat.get("system"):
        if prev_plat.get("system") != curr_plat.get("system"):
            mismatches.append(
                f"Platform mismatch: previous '{prev_plat.get('system')}' vs current '{curr_plat.get('system')}'"
            )

    # Toolchain check
    prev_tool = prev_manifest.get("toolchain", {}) or {}
    curr_tool = curr_manifest.get("toolchain", {}) or {}
    if prev_tool.get("clang_version") and curr_tool.get("clang_version"):
        if prev_tool.get("clang_version") != curr_tool.get("clang_version"):
            mismatches.append(
                f"Toolchain mismatch: clang '{prev_tool.get('clang_version')}' vs '{curr_tool.get('clang_version')}'"
            )

    # Measurement configuration check
    for cfg_key in ("warmup_runs", "measure_runs"):
        if cfg_key in prev_manifest and cfg_key in curr_manifest:
            if prev_manifest[cfg_key] != curr_manifest[cfg_key]:
                mismatches.append(
                    f"Measurement config mismatch for {cfg_key}: {prev_manifest[cfg_key]} vs {curr_manifest[cfg_key]}"
                )

    return len(mismatches) == 0, mismatches


def compare_historical_runs(
    previous_records: Sequence[Any],
    current_records: Sequence[Any],
    previous_run_id: Optional[str] = None,
    current_run_id: Optional[str] = None,
    strategy_to_compare: str = "baseline (-O0)",
    previous_manifest: Optional[dict[str, Any]] = None,
    current_manifest: Optional[dict[str, Any]] = None,
    thresholds: Optional[RegressionThresholds] = None,
    strict_env: bool = True,
) -> HistoricalComparison:
    """
    Compare two historical benchmark runs program by program with source identity
    and environment compatibility guards.
    """
    thresh = thresholds if thresholds is not None else DEFAULT_THRESHOLDS

    prev_map, prev_inferred = _index_records_by_id(previous_records)
    curr_map, curr_inferred = _index_records_by_id(current_records)

    p_run = previous_run_id or prev_inferred or "previous_run"
    c_run = current_run_id or curr_inferred or "current_run"

    env_compatible, env_notes = _check_environment_compatibility(previous_manifest, current_manifest)

    all_pids = sorted(set(list(prev_map.keys()) + list(curr_map.keys())))

    progs: dict[str, HistoricalProgramComparison] = {}
    n_common = 0
    n_missing_prev = 0
    n_missing_curr = 0
    n_failed_prev = 0
    n_failed_curr = 0
    n_source_mismatch = 0
    n_env_incompatible = 0
    n_improved = 0
    n_regressed = 0
    n_mixed = 0
    n_unchanged = 0
    n_inconclusive = 0

    for pid in all_pids:
        prev_d = prev_map.get(pid)
        curr_d = curr_map.get(pid)

        # 1. Missing in current
        if curr_d is None:
            n_missing_curr += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="missing_current",
                previous_run_id=p_run,
                current_run_id=c_run,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=["Program was present in previous run but missing in current run"],
            )
            continue

        # 2. Missing in previous
        if prev_d is None:
            n_missing_prev += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="missing_previous",
                previous_run_id=p_run,
                current_run_id=c_run,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=["Program was added in current run; no previous run data available"],
            )
            continue

        # 3. Present in both
        n_common += 1

        # Check environment compatibility guard
        if strict_env and not env_compatible:
            n_env_incompatible += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="environment_incompatible",
                previous_run_id=p_run,
                current_run_id=c_run,
                environment_compatible=False,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=list(env_notes),
            )
            continue

        # Check source hash identity guard
        prev_sha = _get_record_sha(prev_d)
        curr_sha = _get_record_sha(curr_d)
        if prev_sha and curr_sha and prev_sha != curr_sha:
            n_source_mismatch += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="source_mismatch",
                previous_run_id=p_run,
                current_run_id=c_run,
                source_sha256=curr_sha,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=[
                    f"Source SHA-256 mismatch (previous: '{prev_sha[:8]}...', current: '{curr_sha[:8]}...'); "
                    f"source code changed between runs; deltas not fabricated."
                ],
            )
            continue

        # Check failures
        prev_status = prev_d.get("status", "ok")
        curr_status = curr_d.get("status", "ok")
        prev_err = prev_d.get("pipeline_error")
        curr_err = curr_d.get("pipeline_error")

        if prev_status == "pipeline_error" or prev_d.get("baseline") is None:
            n_failed_prev += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="failed_previous",
                previous_run_id=p_run,
                current_run_id=c_run,
                source_sha256=curr_sha or prev_sha,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=[f"Previous run failed: {prev_err or 'baseline unavailable'}"],
            )
            continue

        if curr_status == "pipeline_error" or curr_d.get("baseline") is None:
            n_failed_curr += 1
            progs[pid] = HistoricalProgramComparison(
                program_id=pid,
                status="failed_current",
                previous_run_id=p_run,
                current_run_id=c_run,
                source_sha256=curr_sha or prev_sha,
                overall_status=OverallStatus.INCOMPARABLE,
                notes=[f"Current run failed: {curr_err or 'baseline unavailable'}"],
            )
            continue

        # Both succeeded: extract metric comparison for strategy_to_compare
        def _get_strat_data(d: dict, strat: str) -> Any:
            if strat.startswith("baseline"):
                return d.get("baseline")
            cands = d.get("candidates") or []
            for c in cands:
                name = c.get("strategy_name") if isinstance(c, dict) else getattr(c, "strategy_name", "")
                if name == strat:
                    return c
            return None

        prev_strat_data = _get_strat_data(prev_d, strategy_to_compare)
        curr_strat_data = _get_strat_data(curr_d, strategy_to_compare)

        prev_em = extract_metrics_from_baseline(prev_strat_data) if strategy_to_compare.startswith("baseline") else extract_metrics_from_candidate(prev_strat_data)
        curr_em = extract_metrics_from_baseline(curr_strat_data) if strategy_to_compare.startswith("baseline") else extract_metrics_from_candidate(curr_strat_data)

        all_m = sorted(set(list(prev_em.metrics.keys()) + list(curr_em.metrics.keys())))
        m_comps: dict[str, MetricComparison] = {}
        for mname in all_m:
            lower_is_better, unit = KNOWN_METRIC_SPECS.get(mname, (True, ""))
            p_val = prev_em.metrics.get(mname)
            c_val = curr_em.metrics.get(mname)
            th_pct = thresh.get_threshold(mname)

            is_est = False
            if mname == "energy":
                is_est = prev_em.energy_is_estimated or curr_em.energy_is_estimated
            elif mname == "carbon":
                is_est = prev_em.carbon_is_estimated or curr_em.carbon_is_estimated

            mc = detect_metric_change(
                metric_name=mname,
                baseline_val=p_val,    # previous run is baseline
                target_val=c_val,      # current run is target
                lower_is_better=lower_is_better,
                unit=unit,
                threshold_pct=th_pct,
                baseline_is_reliable=prev_em.timing_is_reliable,
                target_is_reliable=curr_em.timing_is_reliable,
                baseline_cv=prev_em.timing_cv,
                target_cv=curr_em.timing_cv,
                is_estimated=is_est,
            )
            m_comps[mname] = mc

        overall = derive_overall_status(m_comps)
        if overall == OverallStatus.IMPROVED:
            n_improved += 1
        elif overall == OverallStatus.REGRESSED:
            n_regressed += 1
        elif overall == OverallStatus.MIXED:
            n_mixed += 1
        elif overall == OverallStatus.UNCHANGED:
            n_unchanged += 1
        elif overall == OverallStatus.INCONCLUSIVE:
            n_inconclusive += 1

        # Also extract per-strategy comparisons for common candidate strategies
        strat_historical: dict[str, dict[str, MetricComparison]] = {}
        prev_cands = {
            (c.get("strategy_name") if isinstance(c, dict) else getattr(c, "strategy_name", "")): c
            for c in (prev_d.get("candidates") or [])
        }
        curr_cands = {
            (c.get("strategy_name") if isinstance(c, dict) else getattr(c, "strategy_name", "")): c
            for c in (curr_d.get("candidates") or [])
        }
        common_strats = sorted(set(prev_cands.keys()).intersection(curr_cands.keys()))
        for sname in common_strats:
            if not sname:
                continue
            s_prev_em = extract_metrics_from_candidate(prev_cands[sname])
            s_curr_em = extract_metrics_from_candidate(curr_cands[sname])
            s_metrics_dict: dict[str, MetricComparison] = {}
            for mname in sorted(set(list(s_prev_em.metrics.keys()) + list(s_curr_em.metrics.keys()))):
                lower_is_better, unit = KNOWN_METRIC_SPECS.get(mname, (True, ""))
                th_pct = thresh.get_threshold(mname)
                s_metrics_dict[mname] = detect_metric_change(
                    metric_name=mname,
                    baseline_val=s_prev_em.metrics.get(mname),
                    target_val=s_curr_em.metrics.get(mname),
                    lower_is_better=lower_is_better,
                    unit=unit,
                    threshold_pct=th_pct,
                    baseline_is_reliable=s_prev_em.timing_is_reliable,
                    target_is_reliable=s_curr_em.timing_is_reliable,
                    baseline_cv=s_prev_em.timing_cv,
                    target_cv=s_curr_em.timing_cv,
                )
            strat_historical[sname] = s_metrics_dict

        progs[pid] = HistoricalProgramComparison(
            program_id=pid,
            status="ok",
            previous_run_id=p_run,
            current_run_id=c_run,
            source_sha256=curr_sha or prev_sha,
            environment_compatible=True,
            metric_comparisons=m_comps,
            strategy_historical=strat_historical,
            overall_status=overall,
            notes=[],
        )

    summary = {
        "n_total_programs": len(all_pids),
        "n_common": n_common,
        "n_missing_previous": n_missing_prev,
        "n_missing_current": n_missing_curr,
        "n_failed_previous": n_failed_prev,
        "n_failed_current": n_failed_curr,
        "n_source_mismatch": n_source_mismatch,
        "n_env_incompatible": n_env_incompatible,
        "n_improved": n_improved,
        "n_regressed": n_regressed,
        "n_mixed": n_mixed,
        "n_unchanged": n_unchanged,
        "n_inconclusive": n_inconclusive,
    }

    return HistoricalComparison(
        previous_run_id=p_run,
        current_run_id=c_run,
        programs=progs,
        summary=summary,
    )
