import os
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
import pandas as pd
import subprocess
import time
import re

# Configurations
CLANG_PATH = r"C:\Program Files\LLVM\bin\clang.exe"
# Based on common LLVM passes
PASSES = ["mem2reg", "instcombine", "simplifycfg", "dce", "loop-unroll", "gvn"]
# We'll use combinations of these or just the list itself
ACTIONS = [
    "-O0", "-O1", "-O2", "-O3",
    "mem2reg,instcombine",
    "mem2reg,simplifycfg",
    "mem2reg,instcombine,simplifycfg,dce",
    "mem2reg,instcombine,simplifycfg,gvn,loop-unroll",
    "mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll"
]

# Simple DQN Model
class DQN(nn.Module):
    def __init__(self, input_dim, output_dim):
        super(DQN, self).__init__()
        self.fc = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU(),
            nn.Linear(64, output_dim)
        )

    def forward(self, x):
        return self.fc(x)

class CompilerEnv:
    def __init__(self, benchmark_path):
        self.benchmark_path = benchmark_path
        self.ir_path = "temp_unopt.ll"
        self.generate_unoptimized_ir()
        self.features = self.extract_features(self.ir_path)
        
    def generate_unoptimized_ir(self):
        subprocess.run([CLANG_PATH, "-O0", "-Xclang", "-disable-O0-optnone", "-S", "-emit-llvm", self.benchmark_path, "-o", self.ir_path], capture_output=True)

    def extract_features(self, ir_file):
        # Using a simplified version of the existing feature extractor
        features = {
            "BasicBlocksCount": 0, "InstructionsCount": 0, "BranchCount": 0,
            "MemInstCount": 0, "MathInstCount": 0, "FloatInstCount": 0,
            "VectorInstCount": 0, "CallInstCount": 0
        }
        if not os.path.exists(ir_file): return np.zeros(8)
        
        try:
            with open(ir_file, 'r') as f:
                for line in f:
                    line = line.split(';')[0].strip()
                    if not line: continue
                    if re.match(r"^[a-zA-Z0-9_.]+:$", line): features["BasicBlocksCount"] += 1
                    parts = line.split()
                    if not parts: continue
                    op = parts[0]
                    if len(parts) >= 3 and parts[1] == "=": op = parts[2]
                    
                    if op in ['br', 'switch']: features["BranchCount"] += 1
                    elif op in ['alloca', 'load', 'store', 'getelementptr']: features["MemInstCount"] += 1
                    elif op in ['add', 'sub', 'mul', 'udiv', 'sdiv', 'urem', 'srem', 'shl', 'lshr', 'ashr', 'and', 'or', 'xor']: features["MathInstCount"] += 1
                    elif op in ['fadd', 'fsub', 'fmul', 'fdiv', 'frem', 'fneg']: features["FloatInstCount"] += 1
                    elif op in ['extractelement', 'insertelement', 'shufflevector']: features["VectorInstCount"] += 1
                    elif op in ['call', 'invoke']: features["CallInstCount"] += 1
                    features["InstructionsCount"] += 1
        except: pass
        return np.array(list(features.values()), dtype=np.float32)

    def step(self, action_idx):
        action = ACTIONS[action_idx]
        opt_ir = "temp_opt.ll"
        opt_exe = os.path.abspath("temp_opt.exe")
        
        # Apply optimization
        if action.startswith("-O"):
            subprocess.run([CLANG_PATH, action, "-S", "-emit-llvm", self.benchmark_path, "-o", opt_ir], capture_output=True)
        else:
            temp_unopt = "temp_unopt_step.ll"
            subprocess.run([CLANG_PATH, "-O0", "-Xclang", "-disable-O0-optnone", "-S", "-emit-llvm", self.benchmark_path, "-o", temp_unopt], capture_output=True)
            cmd = [CLANG_PATH, "-S", "-emit-llvm", "-mllvm", f"-passes={action}", temp_unopt, "-o", opt_ir]
            subprocess.run(cmd, capture_output=True)
            if os.path.exists(temp_unopt): os.remove(temp_unopt)
        
        # Compile to executable to measure time
        if os.path.exists(opt_ir):
            subprocess.run([CLANG_PATH, opt_ir, "-o", opt_exe], capture_output=True)
        
        # Measure Performance
        exec_time = 1.0 # default
        code_size = 1e9 # default
        
        if os.path.exists(opt_exe):
            start = time.time()
            try:
                subprocess.run([opt_exe], capture_output=True, timeout=5)
                exec_time = time.time() - start
            except:
                exec_time = 5.0
            code_size = os.path.getsize(opt_exe)
        
        # Security Check
        security_violated = False
        if os.path.exists(opt_ir) and "security_checks.c" in self.benchmark_path:
            with open(opt_ir, 'r') as f:
                ir_content = f.read()
                if "assert_failed" not in ir_content:
                    security_violated = True
        
        # Reward function
        reward = (1.0 / (exec_time + 0.001)) + (10000.0 / (code_size + 1))
        if security_violated:
            reward -= 1000.0
            
        return self.features, reward, True, {}

def train():
    print("Initializing RL Training...")
    benchmarks = ["loops_branches.c", "security_checks.c", "math_heavy.c"]
    # Filter only existing benchmarks
    benchmarks = [b for b in benchmarks if os.path.exists(os.path.join("Codes/test_cases", b))]
    if not benchmarks:
        # Fallback to current directory if not found in test_cases
        benchmarks = [b for b in ["loops_branches.c", "security_checks.c", "math_heavy.c"] if os.path.exists(b)]

    if not benchmarks:
        print("No benchmarks found for training.")
        return

    model = DQN(8, len(ACTIONS))
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    criterion = nn.MSELoss()

    for epoch in range(10):
        total_reward = 0
        for b in benchmarks:
            env = CompilerEnv(b)
            state = torch.FloatTensor(env.features)
            
            # Epsilon-greedy (simplified)
            q_values = model(state)
            action_idx = torch.argmax(q_values).item()
            
            _, reward, done, _ = env.step(action_idx)
            
            # Simple Q-learning update
            target = torch.tensor(reward, dtype=torch.float32)
            loss = criterion(q_values[action_idx], target)
            
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            total_reward += reward
        print(f"Epoch {epoch+1}, Total Reward: {total_reward:.2f}")

    torch.save(model.state_dict(), "ml_optimizer_model.pth")
    print("Model saved to ml_optimizer_model.pth")

if __name__ == "__main__":
    # Ensure we are in the right directory or use relative paths correctly
    train()
