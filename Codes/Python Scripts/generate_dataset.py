import os
import subprocess
import time
import csv
import re

BENCHMARKS = [
    "loops_branches.c",
    "memory_ops.c",
    "security_checks.c",
    "math_heavy.c",
    "recursive_ops.c"
]

OPT_LEVELS = ["-O0", "-O1", "-O2", "-O3"]
OUTPUT_CSV = "dataset.csv"

# Provide absolute paths to clang and lli since they might not be in PATH
CLANG_PATH = r"E:\Downloads\App64\LLVM\bin\clang.exe"
LLI_PATH = r"E:\Downloads\App64\LLVM\bin\lli.exe"

def get_file_size(filepath):
    """Return the file size in bytes."""
    try:
        return os.path.getsize(filepath)
    except:
        return 0

def run_and_measure_time(executable):
    """Run via lli and return the execution time in seconds."""
    start_time = time.time()
    try:
        subprocess.run([LLI_PATH, executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except subprocess.TimeoutExpired:
        return -1.0 
    except Exception as e:
        return -1.0
    end_time = time.time()
    return end_time - start_time

def check_security_checks(filepath, executable):
    if filepath != "security_checks.c":
        return "N/A"
    try:
        with open(executable, "r") as f:
            out = f.read()
        has_assert = "assert_failed" in out
        if has_assert:
            return "Present or Partially Removed"
        else:
            return "Completely Removed"
    except Exception as e:
        return "Unknown"

def extract_ir_features(ll_filepath):
    """Parse the LLVM IR file to extract static code features."""
    features = {
        "BasicBlocksCount": 0,
        "InstructionsCount": 0,
        "BranchCount": 0,
        "MemInstCount": 0,
        "MathInstCount": 0,
        "FloatInstCount": 0,
        "VectorInstCount": 0,
        "CallInstCount": 0
    }
    
    if not os.path.exists(ll_filepath):
        return features
        
    try:
        with open(ll_filepath, 'r') as f:
            for line in f:
                line = line.split(';')[0].strip() # remove comments
                if not line:
                    continue
                    
                # Basic Block heuristic: label:
                if re.match(r"^[a-zA-Z0-9_.]+:$", line):
                    features["BasicBlocksCount"] += 1
                    continue
                    
                parts = line.split()
                if not parts:
                    continue
                
                # Check for assignment: %1 = op ...
                op = parts[0]
                if len(parts) >= 3 and parts[1] == "=":
                    op = parts[2]
                
                # Instruction lists
                if op in ['br', 'switch']:
                    features["BranchCount"] += 1
                    features["InstructionsCount"] += 1
                elif op in ['alloca', 'load', 'store', 'getelementptr']:
                    features["MemInstCount"] += 1
                    features["InstructionsCount"] += 1
                elif op in ['add', 'sub', 'mul', 'udiv', 'sdiv', 'urem', 'srem', 'shl', 'lshr', 'ashr', 'and', 'or', 'xor']:
                    features["MathInstCount"] += 1
                    features["InstructionsCount"] += 1
                elif op in ['fadd', 'fsub', 'fmul', 'fdiv', 'frem', 'fneg']:
                    features["FloatInstCount"] += 1
                    features["InstructionsCount"] += 1
                elif op in ['extractelement', 'insertelement', 'shufflevector']:
                    features["VectorInstCount"] += 1
                    features["InstructionsCount"] += 1
                elif op in ['call', 'invoke']:
                    features["CallInstCount"] += 1
                    features["InstructionsCount"] += 1
                # Other common instructions to just count towards total
                elif op in ['ret', 'icmp', 'fcmp', 'phi', 'select', 'trunc', 'zext', 'sext', 'fptrunc', 'fpext', 'fptoui', 'fptosi', 'uitofp', 'sitofp', 'ptrtoint', 'inttoptr', 'bitcast', 'addrspacecast']:
                    features["InstructionsCount"] += 1

    except Exception as e:
        print(f"Error parsing {ll_filepath}: {e}")
        
    return features

def main():
    print("Starting Week 7 Dataset Generation with IR Features...")
    
    if not os.path.exists(CLANG_PATH):
        print(f"Error: {CLANG_PATH} not found.")
        return

    dataset = []

    for benchmark in BENCHMARKS:
        if not os.path.exists(benchmark):
            print(f"Error: Could not find {benchmark}")
            continue
            
        print(f"\nProcessing {benchmark}...")
        base_name = os.path.splitext(benchmark)[0]
        
        for opt in OPT_LEVELS:
            ll_name = f"{base_name}_{opt.replace('-', '')}.ll"
            obj_name = f"{base_name}_{opt.replace('-', '')}.o"
            
            # Compile to LLVM IR
            subprocess.run([CLANG_PATH, opt, "-S", "-emit-llvm", benchmark, "-o", ll_name], capture_output=True)
            # Compile to Object File 
            subprocess.run([CLANG_PATH, opt, "-c", benchmark, "-o", obj_name], capture_output=True)
                
            code_size = get_file_size(obj_name)
            if code_size == 0:
                code_size = get_file_size(ll_name)
            
            # Execution time cannot be measured currently
            avg_time = "N/A"
            
            sec_checks = check_security_checks(benchmark, ll_name)
            ir_features = extract_ir_features(ll_name)
            
            row = {
                "Program": benchmark,
                "OptimizationLevel": opt,
                "CodeSizeBytes": code_size,
                "ExecTimeSeconds": avg_time,
                "SecurityChecks": sec_checks
            }
            row.update(ir_features)
            
            dataset.append(row)
            print(f"  {opt}: Code Size: {code_size}b, Insts: {ir_features['InstructionsCount']}, Blocks: {ir_features['BasicBlocksCount']}")

    print("\nWriting dataset to dataset.csv...")
    fieldnames = [
        "Program", "OptimizationLevel", "CodeSizeBytes", "ExecTimeSeconds", 
        "SecurityChecks", "BasicBlocksCount", "InstructionsCount", "BranchCount", 
        "MemInstCount", "MathInstCount", "FloatInstCount", "VectorInstCount", 
        "CallInstCount"
    ]
    with open(OUTPUT_CSV, "w", newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for row in dataset:
            writer.writerow(row)
            
    print("Done! Dataset generation complete.")

if __name__ == "__main__":
    main()
