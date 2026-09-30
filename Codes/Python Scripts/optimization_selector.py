import os
import torch
import subprocess
import sys
import re
from ml_optimizer import DQN, ACTIONS, CLANG_PATH, CompilerEnv

MODEL_PATH = "ml_optimizer_model.pth"

OPT_PATH = r"C:\Users\rithv\Downloads\clang+llvm-23.1.0-x86_64-pc-windows-msvc\clang+llvm-23.1.0-x86_64-pc-windows-msvc\bin\opt.exe"


def get_best_optimization(c_file_path):
    env = CompilerEnv(c_file_path)
    state = torch.FloatTensor(env.features)

    model = DQN(8, len(ACTIONS))

    if os.path.exists(MODEL_PATH):
        model.load_state_dict(torch.load(MODEL_PATH, weights_only=True))
    else:
        print(f"Error: {MODEL_PATH} not found.")
        return None

    model.eval()

    with torch.no_grad():
        q_values = model(state)
        action_idx = torch.argmax(q_values).item()

    return ACTIONS[action_idx]


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