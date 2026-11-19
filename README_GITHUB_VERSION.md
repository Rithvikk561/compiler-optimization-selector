# TOACD-Core: GitHub Repository Edition
## Autonomous Multi-Agent Compiler Optimization Selector using Deep Q-Networks & Static Security Gates

---

### 📌 Project Overview
**TOACD-Core** (Tuning & Optimization Agent for Compiler Decisions) is an autonomous, multi-agent compiler optimization research platform that integrates Deep Reinforcement Learning (DQN), static Abstract Syntax Tree (AST) security analysis, and Multi-Objective Optimization (MOO).

* **Repository URL:** `https://github.com/Rithvikk561/compiler-optimization-selector`
* **Governing Invariant:** *"The LLM Explains. The Compiler Decides."*
* **Core Machine Learning:** Deep Q-Network (DQN) trained on 8-dimensional LLVM Intermediate Representation (IR) structural feature vectors.
* **Compiler Infrastructure:** LLVM / Clang compiler harness (`clang` & `opt`).

---

## 1. Architectural Pipeline: 6 Canonical Agents

Every optimization run is processed through a strict, typed sequential pipeline of six specialized domain agents:

```
[User C Source Code]
        │
        ▼
1. CodeAnalystAgent ──────────► LLVM IR generation & 8 canonical features extraction
        │
        ▼
2. ProgramProfilingAgent ─────► Deterministic heuristic classification & dominant feature
        │
        ▼
3. OptimizationStrategistAgent ─► Inference proposal: DQN Q-values across 9 compiler pass actions
        │
        ▼
4. OptimizationReviewerAgent ──► Multi-objective trade-off audit & Pareto non-dominance check
        │
        ▼
5. FinalDecisionAgent ────────► OptimizationSecurityGate verification & fallback ladder
        │
        ▼
6. BenchmarkAgent ────────────► Empirical physical compilation & execution timing
        │
        ▼
[Authoritative RunRecord & Visual Dashboard Report]
```

### Why Security Gate Authorization Precedes Benchmarking
In runtime execution, **Security Gate verification strictly precedes physical compilation and execution**.
* Under no circumstances may an unverified or unsafe optimization strategy be compiled and executed on the host hardware.
* If an optimization candidate strips stack protectors, removes assertions, or eliminates security sinks (HAZ-003 / CWE-570 violation), `FinalDecisionAgent` authoritatively quarantines the candidate and activates the fallback ladder to a safe baseline (`-O2` or `-O0`).
* `BenchmarkAgent` is subsequently invoked to compile and measure the verified **`effective_strategy`**, guaranteeing host system integrity.

---

## 2. Canonical 8 LLVM IR Features

Extracted deterministically from unoptimized LLVM IR (`-O0 -Xclang -disable-O0-optnone`):

1. **`InstructionsCount`**: Total IR instruction count (threshold `< 35.0` indicates Trivial Program).
2. **`BranchCount`**: Control transfer instructions (threshold `> 9.0` evaluates Loop-Oriented profile).
3. **`MemInstCount`**: Load/store memory operations (threshold `> 45.25` evaluates Memory-Oriented profile).
4. **`MathInstCount`**: Integer arithmetic operations (combined `> 5.0` evaluates Compute-Oriented profile).
5. **`FloatInstCount`**: Floating-point operations (combined `> 5.0` evaluates Compute-Oriented profile).
6. **`CallInstCount`**: Direct/indirect function calls (threshold `> 2.0` evaluates Call-Oriented profile).
7. **`BasicBlocksCount`**: Control flow graph basic blocks (complexity reference).
8. **`VectorInstCount`**: SIMD/vector operations (vectorization potential reference).

---

## 3. Quick Start: Running on Windows

### Step 1: Navigate to Project Directory
```powershell
cd "TOACD_GitHub_Version"
```

### Step 2: Activate Your Virtual Environment
```powershell
.\venv\Scripts\Activate.ps1
```

### Step 3: Launch the Modern Web Dashboard
Start the Tornado asynchronous web server on port **8080**:
```powershell
python "Codes/Python Scripts/run_web.py" --host 127.0.0.1 --port 8080
```

### Step 4: Access in Your Browser
Open your browser and navigate to:
👉 **[http://127.0.0.1:8080](http://127.0.0.1:8080)**

---

## 4. Alternative: Desktop GUI Application (Tkinter / TTKBootstrap)

If you prefer a native desktop window application:
```powershell
python "Codes/Python Scripts/gui_app.py"
```

---

## 5. Running the Automated Verification Tests

To run the complete automated test suite for the GitHub version:
```powershell
pytest "Codes/Python Scripts/moo/tests" -v
```
*(Tests normalization, dominance, Pareto frontier extraction, AST security rules, and multi-agent message routing).*

---

## 6. Security & Execution Boundaries

* **Compiler Execution Warning:** TOACD compiles and executes real C source code. While the static AST Security Gate intercepts common buffer overflows, dangerous system calls (`system`, `fork`, `exec`), and unsafe libc invocations, never run completely untrusted or hostile code on a bare metal production host without container isolation.
* **Energy & Environmental Metric Disclaimer:** Energy consumption (Joules) and Carbon footprint ($\text{gCO}_2\text{e}$) displayed in reports are **heuristic mathematical estimates/proxies** calculated from CPU instructions and execution time. They are not direct physical hardware sensor readings (e.g. RAPL or external power meters).
