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


def get_best_optimization(c_file_path, *, return_trace=False, return_xai=False):
    env = CompilerEnv(c_file_path)
    state = torch.FloatTensor(env.features)

    model = DQN(8, len(ACTIONS))

    if os.path.exists(MODEL_PATH):
        model.load_state_dict(torch.load(MODEL_PATH, weights_only=True))
    else:
        print(f"Error: {MODEL_PATH} not found.")
        if return_trace and return_xai:
            return (None, None, None)
        if return_trace or return_xai:
            return (None, None)
        return None

    model.eval()

    with torch.no_grad():
        q_values = model(state)
        # Keep the original argmax as the unconditional fallback.
        action_idx = torch.argmax(q_values).item()

    # --- Stage 4: MOO-aware candidate filter ---
    # Attempt to intersect the AI's Q-value ranking with the Pareto frontier.
    # Any exception at any step falls back to the original argmax result above.
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

        raw_feats = env.features.tolist() if hasattr(env.features, "tolist") else list(env.features)

        result, trace = moo_aware_select_with_trace(
            c_file_path,
            q_values.tolist(),
            ACTIONS,
            frontier,
            report_data=report_data,
            ir_features=raw_feats,
        )
        print(f"[MOO-aware selector] {result.reason}")
        if result.filtered_out:
            print(f"[MOO-aware selector] MOO filtered: {result.filtered_out}")

        strategy = result.strategy

    except Exception as _moo_exc:  # noqa: BLE001
        # Fallback: exact original behavior — argmax already computed above.
        print(f"[MOO-aware selector] MOO unavailable ({_moo_exc}); "
              f"using original AI selection.")
        strategy = ACTIONS[action_idx]
        trace = None

    # --- Informational Post-Processing (Phase 2B) ---
    # Profiling and XAI are purely informational and MUST NEVER alter `strategy`.

    # 1. Program Profile generation (informational only — does NOT influence selection)
    if trace is not None:
        try:
            from moo.program_profiler import profile_program
            raw_feats = env.features.tolist() if hasattr(env.features, "tolist") else list(env.features)
            prof = profile_program(raw_feats)
            trace.program_profile = prof.to_dict() if prof is not None else None
        except Exception:
            trace.program_profile = None

    # 2. XAI result generation (isolated from optimization selection)
    xai_res = None
    if trace is not None and return_xai:
        try:
            xai_res = trace.to_xai_result()
        except Exception:
            xai_res = None

    if return_trace and return_xai:
        return strategy, trace, xai_res
    if return_xai:
        return strategy, xai_res
    if return_trace:
        return strategy, trace
    return strategy


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