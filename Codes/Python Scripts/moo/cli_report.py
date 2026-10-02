"""
moo/cli_report.py — Human-readable CLI summary printer for Stage 3
MOO evaluation results.

Prints a structured table to stdout showing:
  - Baseline measurements
  - Per-strategy: normalized objective ratios and Pareto status
  - Pareto frontier members
  - Invalid/failed strategies

Does NOT label any strategy "best".
Does NOT modify any existing project files.
"""

from __future__ import annotations

import json
import math
import os
from typing import Optional

from .moo_result import MOOEvaluationResult, CandidateResult
from .measurement_quality import build_measurement_quality


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_ratio(v) -> str:
    """Format a normalized ratio value for the table."""
    if v is None:
        return "  N/A  "
    if isinstance(v, str):  # NormalizationError sentinel
        return f"  ERR  "
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return "  N/A  "
    return f"{v:7.3f}"


def _fmt_raw_time(m: Optional[dict]) -> str:
    if not m or not m.get("timing"):
        return "  N/A"
    t = m["timing"].get("median_s")
    if t is None:
        return "  N/A"
    if t < 0.001:
        return f"{t*1000:.3f}ms"
    return f"{t*1000:.2f}ms"


def _fmt_raw_energy(m: Optional[dict]) -> str:
    if not m or not m.get("energy"):
        return "  N/A"
    e = m["energy"].get("energy_joules")
    if e is None:
        return "  N/A"
    return f"{e:.4f}J"


def _fmt_raw_size(m: Optional[dict]) -> str:
    if not m or not m.get("code_size"):
        return "  N/A"
    v = m["code_size"].get("primary_value")
    if v is None:
        return "  N/A"
    return f"{v}B"


def _fmt_raw_carbon(m: Optional[dict]) -> str:
    if not m or not m.get("carbon"):
        return "  N/A"
    c = m["carbon"].get("carbon_grams")
    if c is None:
        return "  N/A"
    return f"{c:.5f}g"


def _get_norm(normalized: Optional[dict], obj_name: str):
    """Extract normalized value for obj_name from a serialized NormalizedObjectiveVector."""
    if not normalized:
        return None
    for row in normalized.get("objectives", []):
        if row.get("objective", {}).get("name") == obj_name:
            v = row.get("normalized_value")
            if isinstance(v, str) and v not in ("", None):
                # Could be a sentinel string
                return v
            return v
    return None


def _status_tag(c: CandidateResult) -> str:
    s = c.pareto_status
    if s == "FRONTIER":
        return "FRONTIER "
    if s == "DOMINATED":
        return "dominated"
    if s == "INVALID":
        return "INVALID  "
    return "UNKNOWN  "


# ---------------------------------------------------------------------------
# Main print function
# ---------------------------------------------------------------------------

def print_moo_summary(result: MOOEvaluationResult, file=None, *, print_trace: bool = False) -> None:
    """
    Print a human-readable Stage 3 MOO summary to *file* (default: stdout).
    """
    import sys
    out = file or sys.stdout

    def w(*args, **kw):
        print(*args, file=out, **kw)

    SEP = "=" * 78
    THIN = "-" * 78

    w()
    w(SEP)
    w(f"  MOO Evaluation — {result.source_file}")
    w(f"  Timestamp : {result.timestamp}")
    if result.toolchain_notes:
        for note in result.toolchain_notes:
            w(f"  [TOOLCHAIN] {note}")
    w(SEP)

    if result.pipeline_error:
        w(f"\n  [PIPELINE ERROR] {result.pipeline_error}\n")
        return

    # ----------------------------------------------------------------
    mq = build_measurement_quality(result.baseline, result.candidates)
    cand_q_map = {
        c.get("strategy_name"): c for c in mq.get("candidates", [])
    }

    # ----------------------------------------------------------------
    # Baseline
    # ----------------------------------------------------------------
    b = result.baseline
    w("\nBaseline  (-O0, unoptimized reference):")
    if b and b.build_ok and b.measurement:
        m = b.measurement
        en_info = m.get("energy") or {}
        cs_info = m.get("code_size") or {}
        cb_info = m.get("carbon") or {}
        w(f"  Time    : {_fmt_raw_time(m)}")
        w(f"  Energy  : {_fmt_raw_energy(m)}  [source: {en_info.get('energy_source','?')[:60]}]")
        w(f"  Code sz : {_fmt_raw_size(m)}  [metric: {cs_info.get('size_source','?')[:60]}]")
        w(f"  Carbon  : {_fmt_raw_carbon(m)}  [estimated: {cb_info.get('carbon_is_estimated','?')}]")
        w(f"  Exit rc : {b.reference_exit_code}")

        base_q = mq.get("baseline", {})
        if base_q.get("status") == "unreliable":
            w("  Quality : UNRELIABLE (timing did not meet reliability criteria)")
            for bw in base_q.get("warnings", []):
                w(f"            ! {bw}")
        elif base_q.get("status") == "unknown":
            if base_q.get("status_source") == "legacy_missing":
                w("  Quality : unknown (legacy report)")
            else:
                w("  Quality : unknown")
                for bw in base_q.get("warnings", []):
                    w(f"            ! {bw}")
    elif b and not b.build_ok:
        w(f"  [BUILD FAILED] {b.build_error}")
    else:
        w("  [No baseline data]")

    # ----------------------------------------------------------------
    # Strategy table
    # ----------------------------------------------------------------
    w()
    w(THIN)
    COL_S = 32
    COL_R = 7
    hdr = (
        f"  {'Strategy':<{COL_S}} "
        f"{'Time':>{COL_R}} "
        f"{'Energy':>{COL_R}} "
        f"{'Size':>{COL_R}} "
        f"{'Carbon':>{COL_R}}  "
        f"Status"
    )
    w(hdr)
    w(THIN)

    for c in result.candidates:
        n = c.normalized
        t  = _fmt_ratio(_get_norm(n, "execution_time"))
        e  = _fmt_ratio(_get_norm(n, "energy"))
        sz = _fmt_ratio(_get_norm(n, "code_size"))
        co = _fmt_ratio(_get_norm(n, "carbon"))

        name = c.strategy_name
        if len(name) > COL_S:
            name = name[:COL_S - 1] + "…"

        tag = _status_tag(c)
        row = (
            f"  {name:<{COL_S}} "
            f"{t} "
            f"{e} "
            f"{sz} "
            f"{co}  "
            f"{tag}"
        )
        w(row)

        # Sub-line: show failure reason or correctness note for INVALID
        if c.pareto_status == "INVALID":
            reason = c.build_error or c.correctness_details or "(unknown)"
            w(f"    [{reason[:72]}]")
        else:
            cq = cand_q_map.get(c.strategy_name)
            if cq:
                if cq.get("status") == "unreliable" or (
                    cq.get("status") == "unknown" and cq.get("status_source") == "recorded"
                ):
                    for cw in cq.get("warnings", []):
                        w(f"    [QUALITY WARNING] {cw[:72]}")

    w(THIN)
    w(
        f"  Note: normalized values = candidate / baseline. "
        f"< 1.0 = improvement, > 1.0 = regression."
    )
    if result.candidates and result.candidates[0].measurement:
        en_info = result.candidates[0].measurement.get("energy") or {}
        est = en_info.get("energy_is_estimated")
        if est:
            w("  Energy and Carbon are ESTIMATED (elapsed_time × TDP × utilisation).")

    # ----------------------------------------------------------------
    # Pareto summary
    # ----------------------------------------------------------------
    w()
    w(SEP)
    w(f"  Summary: {result.n_strategies()} strategies attempted")
    w(f"    Valid   : {result.n_valid()} (measured + correct)")
    w(f"    Invalid : {result.n_invalid()} (failed build or incorrect)")

    q_status = mq.get("status")
    if q_status == "unreliable":
        w("    Quality : UNRELIABLE")
        for qw in mq.get("warnings", []):
            w(f"      ! {qw}")
    elif q_status == "unknown":
        w("    Quality : UNKNOWN")
        for qw in mq.get("warnings", []):
            w(f"      ! {qw}")
    w()

    if result.pareto_frontier:
        w(f"  Pareto frontier ({len(result.pareto_frontier)} non-dominated strategies):")
        for name in result.pareto_frontier:
            w(f"    • {name}")
    else:
        w("  Pareto frontier: (none — no valid candidates)")

    if result.pareto_dominated:
        w(f"\n  Dominated strategies ({len(result.pareto_dominated)}):")
        for name in result.pareto_dominated:
            # Find who dominates it
            for c in result.candidates:
                if c.strategy_name == name and c.dominated_by:
                    w(f"    - {name}  [dominated by: {', '.join(c.dominated_by)}]")
                    break
            else:
                w(f"    - {name}")

    if result.pareto_invalid:
        w(f"\n  Invalid strategies ({len(result.pareto_invalid)}):")
        for name in result.pareto_invalid:
            for c in result.candidates:
                if c.strategy_name == name:
                    reason = c.build_error or c.correctness_details or "(unknown)"
                    w(f"    ! {name}: {reason[:70]}")
                    break

    w()
    w(f"  Objectives used in Pareto: {', '.join(result.objectives_used)}")
    w(SEP)
    w()

    if print_trace and getattr(result, "decision_trace", None):
        print_decision_trace_summary(result.decision_trace, file=out)


# ---------------------------------------------------------------------------
# Decision Trace printer
# ---------------------------------------------------------------------------

def print_decision_trace_summary(
    trace: "DecisionTrace",
    file=None,
    *,
    show_q_rank: bool = True,
    max_q_rank_entries: int = 5,
) -> None:
    """
    Print a structured decision-trace summary to *file* (default: stdout).

    Called only when the caller explicitly opts in (print_trace=True).
    Does NOT change print_moo_summary() behavior.

    Parameters
    ----------
    trace              : DecisionTrace to print
    file               : output file (default: sys.stdout)
    show_q_rank        : if True, print the AI Q-value ranking table
    max_q_rank_entries : maximum number of q_rank entries to print (0 = all)
    """
    import sys
    out = file or sys.stdout

    def w(*args, **kw):
        print(*args, file=out, **kw)

    SEP = "=" * 66

    w()
    w(SEP)
    w("  DECISION TRACE")
    w(SEP)
    w(f"  Selection method : {trace.selection_method}")
    if trace.ai_choice_was_pareto_optimal is True:
        opt_note = "Pareto-optimal"
    elif trace.ai_choice_was_pareto_optimal is False:
        opt_note = "NOT Pareto-optimal"
    else:
        opt_note = "Pareto status unknown"
    w(f"  AI top choice    : {trace.ai_top_choice}  (Q={trace.ai_top_q:.3f})  [{opt_note}]")
    w(f"  Final selection  : {trace.final_strategy}  [{trace.selection_reason}]")
    w(f"  MOO active       : {'yes' if trace.moo_active else 'no'}")
    if trace.objectives_used:
        w(f"  Objectives used  : {', '.join(trace.objectives_used)}")

    if show_q_rank and trace.q_rank_full:
        entries = trace.q_rank_full
        if max_q_rank_entries > 0:
            entries = entries[:max_q_rank_entries]

        w()
        w(f"  AI Q-value ranking (top {len(entries)} of {len(trace.q_rank_full)}):")
        w(f"    {'Rank':<4}  {'Strategy':<33}  {'Q-value':<7}   {'Pareto':<10}")
        w(f"    {'-'*4}  {'-'*33}  {'-'*7}   {'-'*10}")

        frontier_set = set(trace.pareto_frontier)
        dominated_set = set(trace.pareto_dominated)
        invalid_set = set(trace.pareto_invalid)

        for i, (strat, qv) in enumerate(entries, 1):
            if strat in frontier_set:
                p_status = "FRONTIER"
            elif strat in dominated_set:
                p_status = "DOMINATED"
            elif strat in invalid_set:
                p_status = "INVALID"
            else:
                p_status = "UNKNOWN"

            marker = ""
            if strat == trace.final_strategy and strat == trace.ai_top_choice:
                marker = " ← selected & AI choice"
            elif strat == trace.final_strategy:
                marker = " ← selected"
            elif strat == trace.ai_top_choice:
                marker = " ← AI choice"

            w(f"    {i:<4}  {strat:<33}  {qv:7.3f}   {p_status:<10}{marker}")

    if trace.candidates_considered:
        w()
        w("  Candidates considered (Pareto frontier ∩ ACTIONS):")
        w("    " + "  • ".join(["• " + c for c in trace.candidates_considered]))

    if trace.filtered_out:
        w()
        w("  Filtered out by MOO (higher-Q, not Pareto-efficient):")
        w("    " + "  • ".join(["• " + f for f in trace.filtered_out]))

    if trace.objective_snapshot:
        w()
        w("  Objective snapshot (normalized = candidate / baseline; <1.0 = improvement):")
        w(f"    {'Strategy':<20}  {'Time':>7}  {'Energy':>7}  {'Size':>7}  {'Carbon':>7}  {'Q':>7}")
        w(f"    {'-'*20}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*7}")

        for snap in trace.objective_snapshot:
            def _fmt_r(val):
                return f"{val:7.3f}" if val is not None else "    N/A"

            def _fmt_q(val):
                return f"{val:7.3f}" if val is not None else "    N/A"

            t_str = _fmt_r(snap.execution_time_ratio)
            e_str = _fmt_r(snap.energy_ratio)
            s_str = _fmt_r(snap.code_size_ratio)
            c_str = _fmt_r(snap.carbon_ratio)
            q_str = _fmt_q(snap.q_value)

            marker = ""
            if snap.strategy_name == trace.final_strategy:
                marker = "  ← selected"
            elif snap.strategy_name == trace.ai_top_choice:
                marker = "  ← AI choice"

            name_tag = f"{snap.strategy_name} [{snap.pareto_status}]"
            if len(name_tag) > 20:
                name_tag = name_tag[:19] + "…"

            w(f"    {name_tag:<20}  {t_str}  {e_str}  {s_str}  {c_str}  {q_str}{marker}")

    w(SEP)
    w()


# ---------------------------------------------------------------------------
# JSON report saver
# ---------------------------------------------------------------------------

def save_moo_report(result: MOOEvaluationResult, report_dir: str) -> str:
    """
    Save the MOOEvaluationResult as a JSON file in *report_dir*.
    Returns the absolute path of the written file.
    """
    os.makedirs(report_dir, exist_ok=True)
    safe = result.source_file.replace(".", "_").replace(" ", "_")
    ts = result.timestamp.replace(":", "-").replace("T", "_")
    filename = f"moo_{safe}_{ts}.json"
    filepath = os.path.join(report_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    return filepath
