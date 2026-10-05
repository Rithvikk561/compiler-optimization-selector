import os
import torch
import subprocess
import sys
import re
from ml_optimizer import DQN, ACTIONS, CLANG_PATH, CompilerEnv

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "ml_optimizer_model.pth"
)

OPT_PATH = r"C:\Users\rithv\Downloads\clang+llvm-23.1.0-x86_64-pc-windows-msvc\clang+llvm-23.1.0-x86_64-pc-windows-msvc\bin\opt.exe"


from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SelectionResultWithProvenance:
    """Provenance-aware optimization selection record."""
    strategy: str
    provenance: str
    model_id: str
    q_value_selected: Optional[float]
    q_value_argmax: Optional[float]
    q_rank: List[Tuple[str, float]] = field(default_factory=list)
    decision_trace: Optional[Any] = None
    xai_result: Optional[Any] = None
    frontier: List[str] = field(default_factory=list)
    moo_active: bool = False
    filtered_out: List[str] = field(default_factory=list)
    ir_features: Optional[Dict[str, float]] = None


def select_with_provenance(c_file_path, *, allow_moo=True):
    """
    Select best optimization with full provenance, Q-values, DecisionTrace, and XAI.

    Reuses the existing DQN model and selector_bridge without code duplication.
    Does NOT modify the selection decision.
    """
    if not os.path.exists(c_file_path):
        return None

    try:
        env = CompilerEnv(c_file_path)
        state = torch.FloatTensor(env.features)
    except Exception as exc:
        print(f"Error extracting features: {exc}")
        return None

    model = DQN(8, len(ACTIONS))
    model_id = "production_v0"

    if os.path.exists(MODEL_PATH):
        model.load_state_dict(torch.load(MODEL_PATH, weights_only=True))
    else:
        print(f"Error: {MODEL_PATH} not found.")
        return None

    model.eval()

    with torch.no_grad():
        q_values = model(state)
        action_idx = torch.argmax(q_values).item()

    q_vals_list = q_values.tolist()
    q_val_argmax = float(q_vals_list[action_idx])
    q_rank = sorted(
        zip(ACTIONS, [float(q) for q in q_vals_list]),
        key=lambda pair: pair[1],
        reverse=True,
    )

    raw_feats = env.features.tolist() if hasattr(env.features, "tolist") else list(env.features)
    try:
        from moo.xai import format_ir_features
        feats_dict = format_ir_features(raw_feats)
    except Exception:
        feats_dict = {f"feat_{i}": float(v) for i, v in enumerate(raw_feats)}

    trace = None
    provenance = "DQN_ARGMAX"
    frontier = []
    moo_active = False
    filtered_out = []

    if allow_moo:
        try:
            import sys
            import os as _os
            _moo_parent = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            if _moo_parent not in sys.path:
                sys.path.insert(0, _moo_parent)

            from moo.selector_bridge import (
                moo_aware_select_with_trace,
                _load_report_for_trace,
            )

            report_data = _load_report_for_trace(c_file_path)
            frontier = list(report_data.get("pareto_frontier", [])) if report_data else []

            result, trace = moo_aware_select_with_trace(
                c_file_path,
                q_vals_list,
                ACTIONS,
                frontier,
                report_data=report_data,
                ir_features=raw_feats,
            )
            print(f"[MOO-aware selector] {result.reason}")
            if result.filtered_out:
                print(f"[MOO-aware selector] MOO filtered: {result.filtered_out}")

            strategy = result.strategy
            moo_active = bool(result.moo_active)
            filtered_out = list(result.filtered_out)

            if moo_active:
                provenance = "DQN_MOO"
            elif trace and trace.selection_method in (
                "argmax_fallback_no_frontier",
                "argmax_fallback_frontier_mismatch",
            ):
                provenance = "DQN_ARGMAX"
            elif trace and trace.selection_method == "argmax_fallback_exception":
                provenance = "FALLBACK"
            else:
                provenance = "DQN_ARGMAX"

        except Exception as _moo_exc:  # noqa: BLE001
            print(f"[MOO-aware selector] MOO unavailable ({_moo_exc}); using original AI selection.")
            strategy = ACTIONS[action_idx]
            trace = None
            provenance = "FALLBACK"
    else:
        strategy = ACTIONS[action_idx]
        provenance = "DQN_ARGMAX"

    # Find Q-value for selected strategy
    q_value_selected = q_val_argmax
    for s, q in q_rank:
        if s == strategy:
            q_value_selected = q
            break

    # Attach informational profile
    if trace is not None:
        try:
            from moo.program_profiler import profile_program
            prof = profile_program(raw_feats)
            trace.program_profile = prof.to_dict() if prof is not None else None
        except Exception:
            trace.program_profile = None

    # Attach informational XAI
    xai_res = None
    if trace is not None:
        try:
            xai_res = trace.to_xai_result()
        except Exception:
            xai_res = None

    return SelectionResultWithProvenance(
        strategy=strategy,
        provenance=provenance,
        model_id=model_id,
        q_value_selected=q_value_selected,
        q_value_argmax=q_val_argmax,
        q_rank=q_rank,
        decision_trace=trace,
        xai_result=xai_res,
        frontier=frontier,
        moo_active=moo_active,
        filtered_out=filtered_out,
        ir_features=feats_dict,
    )


def get_best_optimization(c_file_path, *, return_trace=False, return_xai=False):
    sel = select_with_provenance(c_file_path)
    if sel is None:
        if return_trace and return_xai:
            return (None, None, None)
        if return_trace or return_xai:
            return (None, None)
        return None

    if return_trace and return_xai:
        return sel.strategy, sel.decision_trace, sel.xai_result
    if return_xai:
        return sel.strategy, sel.xai_result
    if return_trace:
        return sel.strategy, sel.decision_trace
    return sel.strategy


def get_best_optimization_with_xai(c_file_path):
    """Convenience helper returning (strategy, xai_result)."""
    return get_best_optimization(c_file_path, return_xai=True)


def apply_optimization(input_c, output_ll, action):
    print(f"Applying AI-Selected Optimization: {action}")

    if action.startswith("-O"):
        result = subprocess.run(
            [
                CLANG_PATH,
                action,
                "-S",
                "-emit-llvm",
                input_c,
                "-o",
                output_ll
            ],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print("Optimization failed:")
            print(result.stderr)
            return False

    else:
        temp_unopt = "temp_unopt_selector.ll"

        result = subprocess.run(
            [
                CLANG_PATH,
                "-O0",
                "-Xclang",
                "-disable-O0-optnone",
                "-S",
                "-emit-llvm",
                input_c,
                "-o",
                temp_unopt
            ],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print("Failed to generate unoptimized IR:")
            print(result.stderr)
            return False

        cmd = [
            OPT_PATH,
            f"-passes={action}",
            temp_unopt,
            "-S",
            "-o",
            output_ll
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"Custom optimization failed: {action}")
            print(result.stderr)

            if os.path.exists(temp_unopt):
                os.remove(temp_unopt)

            return False

        if os.path.exists(temp_unopt):
            os.remove(temp_unopt)

    if not os.path.exists(output_ll):
        print("Error: Optimized IR was not created.")
        return False

    print(f"Optimization successful: {action}")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python optimization_selector.py <input_c_file>")
        return

    input_c = sys.argv[1]

    if not os.path.exists(input_c):
        print(f"Error: {input_c} not found.")
        return

    output_ll = os.path.splitext(input_c)[0] + "_ai_opt.ll"

    best_action = get_best_optimization(input_c)

    if best_action is None:
        return

    success = apply_optimization(input_c, output_ll, best_action)

    if success:
        print(f"Optimized IR saved to {output_ll}")
    else:
        print("Optimization was not completed.")


if __name__ == "__main__":
    main()