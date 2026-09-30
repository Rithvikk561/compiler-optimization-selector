import os
import subprocess
import time
import pandas as pd
import matplotlib.pyplot as plt
from optimization_selector import get_best_optimization, apply_optimization
from ml_optimizer import CLANG_PATH

# Constants for Carbon Emission Estimation
CPU_POWER_WATTS = 100.0  # Assumed average CPU power draw in Watts
CARBON_INTENSITY_GCO2_PER_KWH = 400.0  # Global average carbon intensity (gCO2/kWh)

def estimate_carbon_emission(exec_time_seconds):
    """
    Estimates the carbon emissions of the execution.
    Formula: Energy (kWh) = Power (kW) * Time (hours)
             Carbon (gCO2) = Energy (kWh) * Carbon Intensity (gCO2/kWh)
    """
    hours = exec_time_seconds / 3600.0
    kwh = (CPU_POWER_WATTS / 1000.0) * hours
    return kwh * CARBON_INTENSITY_GCO2_PER_KWH

BENCHMARKS = [
    "Codes/test_cases/loops_branches.c",
    "Codes/test_cases/math_heavy.c",
    "Codes/test_cases/memory_ops.c",
    "Codes/test_cases/security_checks.c"
]

STRATEGIES = ["-O0", "-O2", "-O3", "AI-Selected"]

def measure_metrics(c_file, strategy):
    base = os.path.basename(c_file).split('.')[0]
    ll_file = f"eval_{base}_{strategy.replace('-', '')}.ll"
    exe_file = f"eval_{base}_{strategy.replace('-', '')}.exe"
    
    start_comp = time.time()
    if strategy == "AI-Selected":
        best_action = get_best_optimization(c_file)
        apply_optimization(c_file, ll_file, best_action)
    else:
        subprocess.run([CLANG_PATH, strategy, "-S", "-emit-llvm", c_file, "-o", ll_file], capture_output=True)
    compilation_time = time.time() - start_comp
    
    # Compile IR to EXE
    subprocess.run([CLANG_PATH, ll_file, "-o", exe_file], capture_output=True)
    
    code_size = os.path.getsize(exe_file) if os.path.exists(exe_file) else 0
    
    start_exec = time.time()
    try:
        subprocess.run([exe_file], capture_output=True, timeout=10)
        execution_time = time.time() - start_exec
    except subprocess.TimeoutExpired:
        execution_time = 10.0
    except Exception:
        execution_time = 0.0
        
    # Cleanup
    for f in [ll_file, exe_file]:
        if os.path.exists(f): os.remove(f)
        
    carbon_emission = estimate_carbon_emission(execution_time)
        
    return {
        "Benchmark": base,
        "Strategy": strategy,
        "CompilationTime": compilation_time,
        "ExecutionTime": execution_time,
        "CarbonEmission_gCO2": carbon_emission,
        "CodeSize": code_size
    }

def main():
    results = []
    print("Starting Performance & Green Carbon Evaluation...")
    for b in BENCHMARKS:
        if not os.path.exists(b): continue
        print(f"Evaluating {b}...")
        for s in STRATEGIES:
            metrics = measure_metrics(b, s)
            results.append(metrics)
            print(f"  {s}: ExecTime={metrics['ExecutionTime']:.4f}s, Size={metrics['CodeSize']}b, Carbon={metrics['CarbonEmission_gCO2']:.6e} gCO2")

    df = pd.DataFrame(results)
    df.to_csv("performance_evaluation.csv", index=False)
    print("Results saved to performance_evaluation.csv")

    # Generate Graphs
    for metric in ["ExecutionTime", "CodeSize", "CarbonEmission_gCO2"]:
        pivot_df = df.pivot(index="Benchmark", columns="Strategy", values=metric)
        pivot_df.plot(kind="bar", figsize=(10, 6))
        plt.title(f"Comparison of {metric} across Strategies")
        plt.ylabel(metric)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(f"{metric}_comparison.png")
        print(f"Graph saved: {metric}_comparison.png")

if __name__ == "__main__":
    main()
