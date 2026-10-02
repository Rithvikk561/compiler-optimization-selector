"""
moo/selector_bridge.py — Stage 4: MOO-aware candidate filter.

This module is the ONLY new interface between the Stage 3 MOO pipeline
and the existing AI optimization selector (optimization_selector.py).

Design principles
-----------------
* Read-only with respect to Stage 3 results — never re-runs or modifies them.
* Cache-first: load the most recent moo_*.json for the source program before
  ever considering a live pipeline run.
* Fail-safe: every public function returns a safe default on ANY exception.
  The caller (optimization_selector.py) must never crash because of this module.
* No new MOO implementation — only consumes the existing Stage 3 structures.
* No weighted scalarization, no XAI, no adaptive learning yet.

Public API
----------
get_pareto_frontier_for(source_path)
    -> list[str]   # strategy names on the Pareto frontier; [] on any failure

moo_aware_select(source_path, q_values, actions, frontier)
    -> (str, str)  # (selected_strategy, selection_reason)

SelectionResult (namedtuple)
    strategy, reason, frontier, q_rank, moo_active
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Named result type
# ---------------------------------------------------------------------------

class SelectionResult:
    """
    Full diagnostic record for one MOO-aware selection decision.

    Attributes
    ----------
    strategy        : the selected ACTIONS string
    reason          : human-readable selection reason label
    frontier        : Pareto frontier names used (empty list if MOO inactive)
    q_rank          : list of (action, q_value) in descending Q-value order
    moo_active      : True if MOO filter was actually applied
    filtered_out    : strategy names that the AI preferred but MOO filtered out
    """
    __slots__ = ("strategy", "reason", "frontier", "q_rank",
                 "moo_active", "filtered_out")

    def __init__(
        self,
        strategy: str,
        reason: str,
        frontier: list[str],
        q_rank: list[tuple[str, float]],
        moo_active: bool,
        filtered_out: list[str],
    ) -> None:
        self.strategy = strategy
        self.reason = reason
        self.frontier = frontier
        self.q_rank = q_rank
        self.moo_active = moo_active
        self.filtered_out = filtered_out

    def __repr__(self) -> str:
        return (
            f"SelectionResult(strategy={self.strategy!r}, "
            f"moo_active={self.moo_active}, reason={self.reason!r})"
        )


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _report_dir() -> str:
    """Return the moo/reports/ directory path (same as config.REPORT_DIR)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "reports")


def _source_key(source_path: str) -> str:
    """
    Derive the filename stem used in moo report filenames from a source path.

    moo_*.json files are named:
        moo_{safe_source_name}_{timestamp}.json
    where safe_source_name = source_file.replace('.','_').replace(' ','_')

    We match only on safe_source_name prefix, not timestamp.
    """
    name = os.path.basename(source_path)       # e.g. "TC1_loop_heavy.c"
    safe = name.replace(".", "_").replace(" ", "_")  # "TC1_loop_heavy_c"
    return safe


def _find_latest_moo_report(source_path: str, report_dir: Optional[str] = None) -> Optional[str]:
    """
    Find the most recently written moo_*.json report for *source_path*.

    Returns the absolute path to the JSON file, or None if no match.

    Only files whose names match the pattern:
        moo_{safe_source_key}_*.json
    are considered.  The Stage 3 diagnostic diag_*.json files are ignored.
    """
    rdir = report_dir or _report_dir()
    if not os.path.isdir(rdir):
        return None

    key = _source_key(source_path)
    prefix = f"moo_{key}_"

    candidates = []
    try:
        for fname in os.listdir(rdir):
            if fname.startswith(prefix) and fname.endswith(".json"):
                full = os.path.join(rdir, fname)
                try:
                    mtime = os.path.getmtime(full)
                    candidates.append((mtime, full))
                except OSError:
                    pass
    except OSError:
        return None

    if not candidates:
        return None

    # Most recently modified first
    candidates.sort(reverse=True)
    return candidates[0][1]


def _load_moo_report(json_path: str) -> Optional[dict]:
    """
    Load and parse a moo_*.json file.

    Returns the dict on success, None on any parse/IO error.
    Validates that the required keys exist.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("selector_bridge: failed to load %s: %s", json_path, exc)
        return None

    required = ("source_file", "pareto_frontier", "pareto_dominated",
                 "pareto_invalid", "candidates", "pipeline_error")
    for key in required:
        if key not in data:
            logger.warning(
                "selector_bridge: report %s missing required key %r; ignoring.",
                json_path, key,
            )
            return None

    return data


def _load_report_for_trace(
    source_path: str,
    report_dir: Optional[str] = None,
) -> Optional[dict]:
    """
    Load the most recent moo_*.json for source_path and return the full dict.
    Returns None on any failure (no report found, I/O error, validation failure).
    This is an internal helper — not part of the public API.
    """
    json_path = _find_latest_moo_report(source_path, report_dir)
    if json_path is None:
        return None
    data = _load_moo_report(json_path)
    if data is None:
        return None
    if data.get("pipeline_error"):
        return None
    return data


# ---------------------------------------------------------------------------
# Public: get_pareto_frontier_for()
# ---------------------------------------------------------------------------

def get_pareto_frontier_for(
    source_path: str,
    report_dir: Optional[str] = None,
    *,
    allow_live_run: bool = False,
) -> list[str]:
    """
    Return the Pareto-frontier strategy names for *source_path*.

    Strategy
    --------
    1. Look for the most recent moo_*.json in moo/reports/ that matches
       the source file basename.
    2. If found and valid, return data["pareto_frontier"].
    3. If *allow_live_run* is True and no cached result exists, run the
       Stage 3 pipeline live and save the result.  (Default: False — the
       GUI must not trigger an unexpected 60-second benchmark run.)
    4. On any failure, return [] so the caller falls back to pure AI.

    Parameters
    ----------
    source_path     : absolute path to the C source file
    report_dir      : override the default moo/reports/ directory (for tests)
    allow_live_run  : if True, run pipeline.evaluate_program() when no cache
                      exists.  Default False (safe for GUI context).

    Returns
    -------
    list[str] — strategy names on the Pareto frontier, or [] on any failure.
    """
    try:
        json_path = _find_latest_moo_report(source_path, report_dir)

        if json_path is not None:
            data = _load_moo_report(json_path)
            if data is not None:
                if data.get("pipeline_error"):
                    logger.warning(
                        "selector_bridge: cached report for %s has pipeline_error=%r; "
                        "returning empty frontier.",
                        os.path.basename(source_path), data["pipeline_error"],
                    )
                    return []
                frontier = data.get("pareto_frontier", [])
                if isinstance(frontier, list):
                    logger.debug(
                        "selector_bridge: loaded frontier %s for %s from %s",
                        frontier, os.path.basename(source_path), os.path.basename(json_path),
                    )
                    return list(frontier)
                return []

        # No cache found
        if allow_live_run:
            return _run_pipeline_and_get_frontier(source_path, report_dir)

        logger.info(
            "selector_bridge: no cached MOO report for %s; returning empty frontier. "
            "Run pipeline.evaluate_program() to generate one.",
            os.path.basename(source_path),
        )
        return []

    except Exception as exc:
        logger.error(
            "selector_bridge: unexpected error in get_pareto_frontier_for(%s): %s",
            source_path, exc,
        )
        return []


def _run_pipeline_and_get_frontier(
    source_path: str,
    report_dir: Optional[str] = None,
) -> list[str]:
    """
    Run the Stage 3 pipeline live for *source_path* and save the result.
    Returns the Pareto frontier or [] on any error.
    Only called when allow_live_run=True.
    """
    try:
        from .pipeline import evaluate_program
        from .cli_report import save_moo_report
        from .config import REPORT_DIR

        rdir = report_dir or REPORT_DIR
        result = evaluate_program(source_path)
        if result.pipeline_error:
            logger.warning(
                "selector_bridge: live pipeline for %s failed: %s",
                os.path.basename(source_path), result.pipeline_error,
            )
            return []
        save_moo_report(result, rdir)
        return list(result.pareto_frontier)
    except Exception as exc:
        logger.error(
            "selector_bridge: live pipeline run failed for %s: %s",
            source_path, exc,
        )
        return []


# ---------------------------------------------------------------------------
# Public: moo_aware_select()
# ---------------------------------------------------------------------------

def moo_aware_select(
    source_path: str,
    q_values: list[float],
    actions: list[str],
    frontier: list[str],
) -> SelectionResult:
    """
    Apply the MOO Pareto frontier as a candidate filter on the AI Q-value ranking.

    Algorithm
    ---------
    1. Build a ranked list of (action, q_value) in descending Q-value order.
    2. If *frontier* is non-empty:
       a. Find all actions that are on the frontier.
       b. From those, pick the one with the highest Q-value.
       c. If no frontier action is in *actions*, fall back to argmax.
    3. If *frontier* is empty → pure argmax (existing behavior).

    The AI's Q-value ranking is always the tiebreaker.
    The frontier is always the filter.

    Parameters
    ----------
    source_path : path to the source file (used only for logging)
    q_values    : list of floats, one per action (DQN output, in ACTIONS order)
    actions     : list of action strings, parallel to q_values
    frontier    : Pareto-frontier strategy names from get_pareto_frontier_for()

    Returns
    -------
    SelectionResult with .strategy, .reason, .frontier, .q_rank, .moo_active,
    .filtered_out fields.

    Safety
    ------
    This function NEVER raises.  Any exception produces the argmax fallback.
    """
    try:
        return _moo_aware_select_impl(source_path, q_values, actions, frontier)
    except Exception as exc:
        logger.error(
            "selector_bridge: moo_aware_select raised unexpectedly for %s: %s; "
            "falling back to argmax.",
            os.path.basename(source_path), exc,
        )
        # Emergency fallback — pick action with highest q_value
        try:
            best_idx = max(range(len(q_values)), key=lambda i: q_values[i])
            best_action = actions[best_idx]
        except Exception:
            best_action = actions[0] if actions else ""
        return SelectionResult(
            strategy=best_action,
            reason="MOO fallback (exception): selected original highest-Q strategy",
            frontier=[],
            q_rank=[],
            moo_active=False,
            filtered_out=[],
        )


def _moo_aware_select_impl(
    source_path: str,
    q_values: list[float],
    actions: list[str],
    frontier: list[str],
) -> SelectionResult:
    """
    Core implementation of moo_aware_select (may raise; wrapped by caller).
    """
    if len(q_values) != len(actions):
        raise ValueError(
            f"q_values length {len(q_values)} != actions length {len(actions)}"
        )
    if not actions:
        raise ValueError("actions list is empty")

    # Build ranked list: [(action, q_value)] descending by Q
    q_rank = sorted(
        zip(actions, q_values),
        key=lambda av: av[1],
        reverse=True,
    )

    # --- Case 1: No frontier (MOO unavailable or failed) ---
    if not frontier:
        best_action = q_rank[0][0]
        return SelectionResult(
            strategy=best_action,
            reason="MOO fallback: selected original highest-Q strategy",
            frontier=[],
            q_rank=list(q_rank),
            moo_active=False,
            filtered_out=[],
        )

    # --- Case 2: Frontier available — apply filter ---
    frontier_set = set(frontier)

    # Identify which frontier strategies are actually in the actions list
    valid_frontier_in_actions = [
        (act, qv) for act, qv in q_rank
        if act in frontier_set
    ]

    if not valid_frontier_in_actions:
        # Frontier strategies don't match any known action — shouldn't happen
        # with a coherent config, but handle gracefully.
        best_action = q_rank[0][0]
        logger.warning(
            "selector_bridge: frontier strategies %s not found in ACTIONS for %s; "
            "falling back to argmax.",
            frontier, os.path.basename(source_path),
        )
        return SelectionResult(
            strategy=best_action,
            reason="MOO fallback: frontier strategies not in ACTIONS — selected highest-Q strategy",
            frontier=list(frontier),
            q_rank=list(q_rank),
            moo_active=False,
            filtered_out=[],
        )

    # Pick the highest-Q Pareto-frontier strategy
    selected_action = valid_frontier_in_actions[0][0]

    # Determine what the pure argmax would have chosen
    ai_top_action = q_rank[0][0]
    was_filtered = ai_top_action not in frontier_set

    # Strategies the AI preferred but MOO filtered out (higher Q, not on frontier)
    filtered_out = [
        act for act, qv in q_rank
        if act not in frontier_set and qv > valid_frontier_in_actions[0][1]
    ]

    if was_filtered:
        reason = (
            f"MOO-aware: selected highest-Q Pareto strategy '{selected_action}' "
            f"(AI top '{ai_top_action}' was not Pareto-efficient)"
        )
    else:
        reason = (
            f"MOO-aware: selected highest-Q Pareto strategy '{selected_action}' "
            f"(same as AI top choice)"
        )

    return SelectionResult(
        strategy=selected_action,
        reason=reason,
        frontier=list(frontier),
        q_rank=list(q_rank),
        moo_active=True,
        filtered_out=filtered_out,
    )


# ---------------------------------------------------------------------------
# Public: moo_aware_select_with_trace()
# ---------------------------------------------------------------------------

def moo_aware_select_with_trace(
    source_path: str,
    q_values: list[float],
    actions: list[str],
    frontier: list[str],
    *,
    report_data: Optional[dict] = None,
) -> tuple[SelectionResult, Optional["DecisionTrace"]]:
    """
    Same selection algorithm as moo_aware_select(). Additionally returns a
    DecisionTrace capturing the full reasoning chain.

    Parameters
    ----------
    source_path  : path to the source file (used only for logging)
    q_values     : list of floats, one per action (DQN output, in ACTIONS order)
    actions      : list of action strings, parallel to q_values
    frontier     : Pareto-frontier strategy names (from get_pareto_frontier_for())
    report_data  : optional full moo_*.json dict (from _load_report_for_trace()).
                   If None, objective_snapshot will be empty and dominated/invalid
                   lists will be derived from frontier alone.

    Returns
    -------
    (SelectionResult, DecisionTrace | None)
    SelectionResult is identical to what moo_aware_select() would return.
    DecisionTrace is None if trace construction itself raises an exception.

    Safety
    ------
    This function NEVER raises. Any exception in selection falls back to argmax
    (same as moo_aware_select). Any exception in trace construction returns
    (result, None) without affecting the selection result.
    """
    # Step 1: run the existing selection (unchanged algorithm)
    result = moo_aware_select(source_path, q_values, actions, frontier)

    # Step 2: build trace (may return None on failure)
    trace = _build_decision_trace(
        q_values=q_values,
        actions=actions,
        frontier=frontier,
        result=result,
        report_data=report_data,
    )
    return result, trace


def _build_decision_trace(
    q_values: list[float],
    actions: list[str],
    frontier: list[str],
    result: SelectionResult,
    report_data: Optional[dict],
) -> Optional["DecisionTrace"]:
    """
    Construct a DecisionTrace from the inputs and the SelectionResult.
    Returns None on any exception — never raises.
    """
    try:
        from .decision_trace import (
            DecisionTrace,
            ObjectiveSnapshot,
            SELECTION_METHOD_MOO_AWARE,
            SELECTION_METHOD_ARGMAX_NO_FRONTIER,
            SELECTION_METHOD_ARGMAX_FRONTIER_MISMATCH,
            SELECTION_METHOD_ARGMAX_EXCEPTION,
        )

        # --- AI layer ---
        q_rank_full = sorted(
            zip(actions, q_values),
            key=lambda av: av[1],
            reverse=True,
        )
        ai_top_choice = q_rank_full[0][0] if q_rank_full else (actions[0] if actions else "")
        ai_top_q = q_rank_full[0][1] if q_rank_full else 0.0

        # --- Pareto layer (from report_data where available) ---
        pareto_dominated = list(report_data.get("pareto_dominated", [])) if report_data else []
        pareto_invalid   = list(report_data.get("pareto_invalid",   [])) if report_data else []
        objectives_used  = list(report_data.get("objectives_used",  [])) if report_data else []

        # --- Filtering ---
        if not frontier:
            ai_choice_was_pareto_optimal = None
        else:
            ai_choice_was_pareto_optimal = (ai_top_choice in set(frontier))

        candidates_considered = [
            act for act, _ in q_rank_full
            if act in set(frontier)
        ]

        # --- Selection method ---
        if "exception" in result.reason:
            selection_method = SELECTION_METHOD_ARGMAX_EXCEPTION
        elif result.moo_active:
            selection_method = SELECTION_METHOD_MOO_AWARE
        elif not frontier:
            selection_method = SELECTION_METHOD_ARGMAX_NO_FRONTIER
        elif frontier and not candidates_considered:
            selection_method = SELECTION_METHOD_ARGMAX_FRONTIER_MISMATCH
        else:
            # moo_active=False with a non-empty frontier and candidates:
            # this means the AI top choice IS on the frontier (no filter needed)
            selection_method = SELECTION_METHOD_MOO_AWARE

        # --- Objective snapshot ---
        snapshot_targets = set(candidates_considered) | {ai_top_choice}
        objective_snapshot = _build_objective_snapshot(
            targets=snapshot_targets,
            q_rank_full=q_rank_full,
            report_data=report_data,
        )

        return DecisionTrace(
            ai_top_choice=ai_top_choice,
            ai_top_q=ai_top_q,
            q_rank_full=list(q_rank_full),
            pareto_frontier=list(frontier),
            pareto_dominated=pareto_dominated,
            pareto_invalid=pareto_invalid,
            objectives_used=objectives_used,
            moo_active=result.moo_active,
            ai_choice_was_pareto_optimal=ai_choice_was_pareto_optimal,
            candidates_considered=candidates_considered,
            filtered_out=list(result.filtered_out),
            final_strategy=result.strategy,
            selection_reason=result.reason,
            selection_method=selection_method,
            objective_snapshot=objective_snapshot,
        )
    except Exception as exc:
        logger.warning("selector_bridge: _build_decision_trace failed: %s", exc)
        return None


def _build_objective_snapshot(
    targets: set[str],
    q_rank_full: list[tuple[str, float]],
    report_data: Optional[dict],
) -> list["ObjectiveSnapshot"]:
    """
    Build ObjectiveSnapshot list for each strategy in *targets*.
    Normalized values come from report_data["candidates"][*]["normalized"].
    q_value comes from q_rank_full.
    Returns [] if report_data is None.
    """
    from .decision_trace import ObjectiveSnapshot

    if not report_data:
        return []

    q_map = {act: qv for act, qv in q_rank_full}
    snapshots = []

    for cand_dict in report_data.get("candidates", []):
        name = cand_dict.get("strategy_name", "")
        if name not in targets:
            continue

        norm = cand_dict.get("normalized") or {}
        # Extract normalized objective values from the serialized
        # NormalizedObjectiveVector structure: {"objectives": [{"objective": {"name": "..."}, "normalized_value": ...}]}
        obj_values = {}
        for row in norm.get("objectives", []):
            obj_name = row.get("objective", {}).get("name")
            val = row.get("normalized_value")
            if obj_name and isinstance(val, (int, float)):
                obj_values[obj_name] = float(val)

        snapshots.append(ObjectiveSnapshot(
            strategy_name=name,
            pareto_status=cand_dict.get("pareto_status", "UNKNOWN"),
            execution_time_ratio=obj_values.get("execution_time"),
            energy_ratio=obj_values.get("energy"),
            code_size_ratio=obj_values.get("code_size"),
            carbon_ratio=obj_values.get("carbon"),
            q_value=q_map.get(name),
        ))

    # Sort by Q-value descending for deterministic output
    snapshots.sort(key=lambda s: (s.q_value is None, -(s.q_value or 0.0)))
    return snapshots


# ---------------------------------------------------------------------------
# Convenience: invalidate_cache()
# ---------------------------------------------------------------------------

def invalidate_cache(source_path: str, report_dir: Optional[str] = None) -> int:
    """
    Remove all cached moo_*.json reports for *source_path*.

    Returns the number of files removed (0 if none found or on error).
    Useful for tests and for forcing a fresh pipeline run.
    """
    try:
        rdir = report_dir or _report_dir()
        if not os.path.isdir(rdir):
            return 0
        key = _source_key(source_path)
        prefix = f"moo_{key}_"
        removed = 0
        for fname in os.listdir(rdir):
            if fname.startswith(prefix) and fname.endswith(".json"):
                try:
                    os.remove(os.path.join(rdir, fname))
                    removed += 1
                except OSError:
                    pass
        return removed
    except Exception:
        return 0
