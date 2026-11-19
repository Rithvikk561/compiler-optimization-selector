# TOACD: Faculty Demonstration & Feature Evaluation Guide
## Comprehensive Walkthrough for Evaluating Every Major System Capability

---

### 🌟 Welcome Faculty Evaluator!
This document provides a guided, multi-stage demonstration script for evaluating the technical contributions, algorithms, security mechanisms, and AI assistant capabilities of **TOACD**.

---

## 📑 Demonstration Workflow Overview

```
[1. Verify Environment] ➔ [2. Select Benchmark] ➔ [3. Execute 6 Agents] ➔ [4. Inspect Security Gate]
                                    │
                                    ▼
[8. AI Assistant Chat] ◄─ [7. Microsecond Timing] ◄─ [6. Pareto Frontier] ◄─ [5. Compare Policies]
```

---

## Stage 1: System Health & Toolchain Verification

1. Start the web application and open **[http://127.0.0.1:8081](http://127.0.0.1:8081)** (or `8080`).
2. Look at the **System Status Header** at the top of the interface:
   * **Clang Status:** Green indicator confirming Clang is detected with active version string.
   * **Active Policy Model:** Displays active strategy engine (e.g. `DQN` or `LinUCB`).
   * **Toolchain API Diagnostic:** You can also query `GET http://127.0.0.1:8081/api/status` to view the raw JSON diagnostic reporting Clang path, Opt path, and PyTorch availability.

---

## Stage 2: Benchmark Workload Selection

In the top-left control panel, open the **Benchmark Sample** dropdown menu. The system includes 18 canonical benchmark programs spanning distinct algorithmic domains:

* **`Polybench GEMM` (`gemm.c`):** High-density matrix multiplication (compute-bound, loop nest).
* **`Quick Sort` (`quick_sort.c`):** Recursive divide-and-conquer partition algorithm (branch-heavy).
* **`Pointer-Heavy Array Ops` (`pointer_array_ops.c`):** Memory indirection and pointer chasing.
* **`TC2: Security Bounds Check` (`TC2_security_bounds_check.c`):** Array boundary guard preservation test.
* **`Multi-File C Project` (`multi_file_project/`):** Full multi-translation unit project (`main.c`, `helper.c`, `math_utils.c`).

*Notice that when a benchmark is selected, the complete C source code populates immediately into the interactive code editor.*

---

## Stage 3: Executing the 6-Agent Deliberative Pipeline

Click the prominent blue **"Run Optimization Pipeline"** button. Observe the 6 specialized domain agents execute in strict sequence:

1. **`CodeAnalystAgent`:**
   * Invokes Clang with `-O0 -Xclang -disable-O0-optnone -S -emit-llvm` to emit unoptimized bitcode.
   * Deterministically parses the LLVM IR to extract the **8 canonical structural features** (`InstructionsCount`, `BranchCount`, `MemInstCount`, `MathInstCount`, `FloatInstCount`, `CallInstCount`, `BasicBlocksCount`, `VectorInstCount`).
2. **`ProgramProfilingAgent`:**
   * Evaluates deterministic heuristic thresholds to classify the workload profile (e.g. *Compute-Oriented*, *Memory-Oriented*, *Loop-Oriented*, or *Trivial Program*).
   * Identifies the dominant structural feature.
3. **`OptimizationStrategistAgent`:**
   * Passes the 8-D vector into the machine learning policy to propose an optimal pass sequence from the 9 candidate actions (`-O1`, `-O2`, `-O3`, `-Os`, `-Oz`, `mem2reg,instcombine`, `loop-unroll`, etc.).
4. **`OptimizationReviewerAgent`:**
   * Audits Multi-Objective trade-offs across Execution Time, Binary Size, and Compile Overhead.
   * Conducts Pareto non-dominance verification.
5. **`FinalDecisionAgent` (Security Gate Authorization):**
   * Authoritatively evaluates static AST security rules.
   * Guarantees safety *before* any physical binary is compiled.
6. **`BenchmarkAgent`:**
   * Empirically compiles the authorized candidate and runs physical timing measurements.

---

## Stage 4: Demonstrating the AST Security Gate (CWE-570 / Hazard Mitigation)

TOACD enforces the core rule: **Under no circumstances may an unverified or dangerous optimization candidate be executed.**

### How to Demonstrate Security Gate Enforcement:
1. In the benchmark dropdown, select **`TC2: Security Bounds Check`** or **`TC4: Security Null Overflow`**.
2. Notice the explicit array boundary checks and pointer guard sinks present in the code.
3. Click **"Run Optimization Pipeline"**.
4. In the **Right-Hand Panel**, inspect the **Security Gate Telemetry Card**:
   * **Candidate Verdict:** Shows whether guard block preservation is `PRESERVED`, `REDUCED`, or `ELIMINATED`.
   * **Authoritative Gate Decision:** Confirms `ACCEPT`, `ACCEPT_WITH_WARNINGS`, or `FALLBACK`.
   * If aggressive optimization (e.g. aggressive dead-code elimination) eliminates safety checks, the gate intercepts the candidate, triggers the fallback ladder to safe baseline `-O2` or `-O0`, and logs the mitigation event in the permanent ledger.

---

## Stage 5: Demonstrating Dual Machine Learning Policies (DQN vs LinUCB)

*(Available in TOACD Enterprise v3.5)*

TOACD Enterprise features a dual-policy machine learning architecture:

### 1. LinUCB Contextual Bandit:
* Selects candidate arm by balancing exploitation and exploration:
  $$\text{UCB}_a = \theta_a^T x + \alpha \sqrt{x^T A_a^{-1} x} \quad (\alpha=0.5)$$
* **What to inspect in the UI:** Look at the **LinUCB Telemetry Table**:
  * **Predicted Reward ($\hat{\mu}_a$):** Expected performance improvement.
  * **Exploration Bonus ($\alpha \cdot s_a$):** Uncertainty bonus based on arm observation count.
  * **Total UCB Score:** Combined selection metric.

### 2. Deep Q-Network (DQN):
* Switch the strategy selector to **DQN**.
* Evaluates action values $Q(s, a) = \max_a Q(s, a)$ through the multi-layer neural network.
* **What to inspect in the UI:** The full 9-action Q-values table with the argmax winner highlighted. Zero LinUCB metrics leak into this view.

---

## Stage 6: Interpreting the Pareto Frontier & Multi-Objective Trade-offs

1. In the center dashboard, inspect the **Pareto Optimization Frontier Graph**:
   * **X-Axis:** Execution Time (Normalized vs `-O0` baseline; lower is faster).
   * **Y-Axis:** Executable Binary Size (Normalized vs `-O0` baseline; lower is smaller).
2. **Analysis:**
   * Highlights non-dominated frontier strategies with a solid line.
   * Demonstrates that while `-O3` may maximize pure throughput, custom passes like `mem2reg,instcombine` or `-Os` achieve non-dominated balance points with drastically smaller binary footprints.

---

## Stage 7: Microsecond Kernel Timing (Win32 & POSIX v3.5)

In the Benchmark Metrics card, inspect the microsecond timing breakdown:

* **Child Process CPU Time ($T_{\text{cpu}}$):** Pure user and kernel CPU execution cycles spent solely within the benchmark child process (`GetProcessTimes` API).
* **Physical Wall-Clock Time ($T_{\text{wall}}$):** Total elapsed physical time recorded by high-resolution hardware counters.
* **OS Residual Overhead ($T_{\text{residual}}$):** Calculated as $T_{\text{wall}} - T_{\text{cpu}}$, reflecting host operating system context switching and scheduler jitter.
* **Significance:** Completely eliminates timing inflation, providing scientifically reproducible compiler autotuning data.

---

## Stage 8: 🤖 Demonstrating the AI Coding Assistant Chatbot

The platform features an intelligent, advisory AI Coding Assistant operating under Architecture B+ (decoupled from the compiler, purely explanatory).

### 8.1. How Faculty Can Use Their Own Gemini API Key (Takes 60 Seconds)
Faculty members do not need to share accounts or enter credit card information:
1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Sign in with any standard Google account and click **"Create API Key"** (100% free tier, zero billing setup required).
3. Copy the key (starts with `AIzaSy...`).
4. In the TOACD web dashboard:
   * Click the **🤖 AI Assistant** tab on the right side.
   * Click the **Provider Switcher** button at the top of the chat panel.
   * Select **Google Gemini** from the dropdown.
   * Paste your key into the **API Key** input box.
   * Click **Test Connection** (turns green: `Connected successfully!`).
   * Click **Save & Connect**.

### 8.2. 100% Offline Demonstration (No API Key Required)
If you prefer not to use an external API key or are demonstrating without internet access:
* Simply leave the provider set to **`Mock`**.
* The assistant will generate deterministic Explainable AI (XAI) responses grounded directly in the compilation run record and IR features!

### 8.3. Prompts to Test with the AI Assistant
Once connected, try asking:
* *"Why did the OptimizationStrategistAgent recommend this specific pass sequence?"*
* *"Explain what the 8 LLVM IR features tell us about this program's computational complexity."*
* *"How did the AST Security Gate protect against buffer boundary degradation?"*
* Click the quick-action button: **"Explain in Simple English"** for an automated plain-language summary of the entire run record!

---

## Summary of Evaluator Deliverables

| Capability | What is Verified |
|---|---|
| **Autonomous Multi-Agent Coordination** | 6 specialized domain agents executing deterministically in typed sequence. |
| **Compiler Intelligence** | Deep Q-Networks and Contextual Multi-Armed Bandits outperforming static `-O3`. |
| **Compiler Safety** | AST Security Gate intercepts vulnerabilities before physical code execution. |
| **Scientific Reproducibility** | Microsecond kernel process timing isolating pure CPU execution from OS residual jitter. |
| **Explainable AI Integration** | AI Assistant explains compiler decisions in plain language without overriding compiler autonomy. |
