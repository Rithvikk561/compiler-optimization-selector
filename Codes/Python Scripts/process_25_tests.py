import os
import subprocess
import csv
import re

TEST_CASES_DIR = "test_cases"
OUTPUT_DIR = "ir_output"
OUTPUT_CSV = os.path.join("Datasets", "dataset.csv")
OPT_LEVELS = ["-O0", "-O1", "-O2", "-O3"]

# Provide absolute paths to clang
CLANG_PATH = r"E:\Downloads\App64\LLVM\bin\clang.exe"

def get_file_size(filepath):
    try:
        return os.path.getsize(filepath)
    except:
        return 0

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
                    
                if re.match(r"^[a-zA-Z0-9_.]+:$", line):
                    features["BasicBlocksCount"] += 1
                    continue
                    
                parts = line.split()
                if not parts:
                    continue
                
                op = parts[0]
                if len(parts) >= 3 and parts[1] == "=":
                    op = parts[2]
                
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
                elif op in ['ret', 'icmp', 'fcmp', 'phi', 'select', 'trunc', 'zext', 'sext', 'fptrunc', 'fpext', 'fptoui', 'fptosi', 'uitofp', 'sitofp', 'ptrtoint', 'inttoptr', 'bitcast', 'addrspacecast']:
                    features["InstructionsCount"] += 1
    except Exception as e:
        print(f"Error parsing {ll_filepath}: {e}")
        
    return features

def main():
    print("Starting generation for the 25 Code test cases...")
    
    if not os.path.exists(CLANG_PATH):
        print(f"Error: {CLANG_PATH} not found.")
        return

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    if not os.path.exists("Datasets"):
        os.makedirs("Datasets")

    dataset = []

    for filename in os.listdir(TEST_CASES_DIR):
        if not filename.endswith(".c"):
            continue
            
        filepath = os.path.join(TEST_CASES_DIR, filename)
        base_name = os.path.splitext(filename)[0]
        print(f"Processing {filename}...")
        
        for opt in OPT_LEVELS:
            ll_name = os.path.join(OUTPUT_DIR, f"{base_name}_{opt.replace('-', '')}.ll")
            obj_name = os.path.join(OUTPUT_DIR, f"{base_name}_{opt.replace('-', '')}.o")
            
            subprocess.run([CLANG_PATH, opt, "-S", "-emit-llvm", "-w", filepath, "-o", ll_name], capture_output=True)
            subprocess.run([CLANG_PATH, opt, "-c", "-w", filepath, "-o", obj_name], capture_output=True)
                
            code_size = get_file_size(obj_name)
            if code_size == 0:
                code_size = get_file_size(ll_name)
            
            ir_features = extract_ir_features(ll_name)
            
            row = {
                "Program": filename,
                "OptimizationLevel": opt,
                "CodeSizeBytes": code_size,
                "ExecTimeSeconds": "N/A",
                "SecurityChecks": "N/A"
            }
            row.update(ir_features)
            
            dataset.append(row)

    print(f"\nWriting dataset to {OUTPUT_CSV}...")
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
