import os
import subprocess
import pandas as pd
from optimization_selector import get_best_optimization, apply_optimization
from ml_optimizer import CLANG_PATH

SECURITY_BENCHMARK = "Codes/test_cases/security_checks.c"

def check_security(c_file, strategy):
    base = os.path.basename(c_file).split('.')[0]
    ll_file = f"sec_{base}_{strategy.replace('-', '')}.ll"
    
    if strategy == "AI-Selected":
        best_action = get_best_optimization(c_file)
        apply_optimization(c_file, ll_file, best_action)
    else:
        subprocess.run([CLANG_PATH, strategy, "-S", "-emit-llvm", c_file, "-o", ll_file], capture_output=True)
    
    status = "Preserved"
    try:
        with open(ll_file, 'r') as f:
            content = f.read()
            if "assert_failed" not in content and "abort" not in content:
                status = "Removed (UNSAFE)"
    except:
        status = "Error Reading IR"
        
    if os.path.exists(ll_file): os.remove(ll_file)
    return status

def main():
    print("Starting Security Evaluation...")
    if not os.path.exists(SECURITY_BENCHMARK):
        print(f"Error: {SECURITY_BENCHMARK} not found.")
        return
        
    results = []
    strategies = ["-O0", "-O2", "-O3", "AI-Selected"]
    
    for s in strategies:
        print(f"Checking security for {s}...")
        status = check_security(SECURITY_BENCHMARK, s)
        results.append({"Strategy": s, "Security Checks Status": status})
        print(f"  Result: {status}")

    df = pd.DataFrame(results)
    
    # Generate Markdown Report (Manual Table)
    report = "# Security Evaluation Report\n\n"
    report += "## AI-Assisted Compiler Optimization Security vs Performance Trade-off\n\n"
    report += "This report evaluates the preservation of security checks (assertions/bounds checks) across different optimization levels.\n\n"
    report += "### Results Table\n\n"
    report += "| Strategy | Security Checks Status |\n"
    report += "| :--- | :--- |\n"
    for _, row in df.iterrows():
        report += f"| {row['Strategy']} | {row['Security Checks Status']} |\n"
    report += "\n\n### Discussion\n\n"
    report += "- **-O0**: Security checks are fully preserved but performance is poor.\n"
    report += "- **-O2/-O3**: Aggressive optimizations may strip away security checks if they assume undefined behavior is unreachable.\n"
    report += "- **AI-Selected**: The AI model is trained to apply performance-improving passes while explicitly penalizing the removal of security markers.\n"
    
    with open("security_report.md", "w") as f:
        f.write(report)
    print("Security report saved to security_report.md")

if __name__ == "__main__":
    main()
