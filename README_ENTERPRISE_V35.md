# TOACD Enterprise (v3.5): Technical Specification & User Guide
## Autonomous Compiler Pass Selection via Dual Deep RL & Contextual Bandits with Microsecond Kernel Timing & Multi-Provider AI Assistant

---

### 📌 Project Overview
**TOACD Enterprise (v3.5)** is the authoritative, enhanced production release of the TOACD compiler research platform. Expanding significantly upon the baseline core, Enterprise v3.5 introduces:

1. **Dual-Policy Machine Learning:** Seamless switching between Deep Q-Networks (DQN) and online Contextual Multi-Armed Bandits (LinUCB with Upper Confidence Bound exploration bonus $\alpha=0.5$).
2. **Win32 & POSIX Microsecond Kernel Timing Engine (v3.5):** Decouples pure Child Process CPU execution time ($T_{\text{cpu}}$) from Total Wall time ($T_{\text{wall}}$) and isolates signed OS Residuals ($T_{\text{residual}} = T_{\text{wall}} - T_{\text{cpu}}$).
3. **Multi-File C Project Build Engine (`CProject` + `BuildConfig`):** Multi-translation unit compilation, include paths, and custom linker flags (`multi_file_project`).
4. **SHA-256 Bitcode Cache (`ir_cache`):** Content-hashed caching delivering 70–80% compilation latency reduction.
5. **Multi-Provider AI Assistant (Architecture B+):** Completely decoupled advisory chatbot supporting Google Gemini, OpenAI, Claude, local Ollama, and deterministic Mock with live streaming SSE.
6. **Expanded 18-Sample Benchmark Suite:** Covering sorting algorithms, linear algebra, graph problems, and multi-file projects.
7. **Comprehensive Verification Harness:** **821 unit and integration tests passing with a 100% pass rate (0 failures)**.

---

## 1. Architectural Innovations in v3.5

### 1.1. Dual-Policy Optimization Engine: DQN vs LinUCB
* **LinUCB Contextual Bandit (`model_family="linucb"`):** Selects optimization pass $a$ that maximizes the Upper Confidence Bound:
  $$\text{UCB}_a = \theta_a^T x + \alpha \sqrt{x^T A_a^{-1} x}$$
  where $\theta_a$ is the ridge-regression coefficient vector, $A_a$ is the covariance matrix, and $\alpha=0.5$ balances exploitation and exploration. Telemetry includes Predicted Reward ($\hat{\mu}_a$), Exploration Bonus ($\alpha \cdot s_a$), and candidate arm ranking.
* **Deep Q-Network (`model_family="dqn"`):** Selects pass action with highest estimated state-action value $Q(s, a) = \max_a Q(s, a)$ evaluated by the neural network on the 8-D IR feature vector.
* **Strict Telemetry Isolation:** The UI clearly distinguishes between the two policy views without metric leakage.

### 1.2. Precision Kernel Timing Mechanics (v3.5 §17.6)
* Traditional benchmark timers record total wall-clock elapsed time, which conflates program execution with background OS context switching and disk I/O jitter.
* The v3.5 Measurement Engine queries process kernel handles (`GetProcessTimes` on Windows / `os.times()` on POSIX) to isolate:
  * **$T_{\text{cpu}}$**: Pure user-mode + kernel-mode CPU time consumed by the target binary.
  * **$T_{\text{wall}}$**: Physical high-resolution wall-clock duration (`time.perf_counter_ns()`).
  * **$T_{\text{residual}}$**: Operating system overhead ($T_{\text{wall}} - T_{\text{cpu}}$).

### 1.3. Multi-File C Project Builds
* Full support for projects composed of multiple `.c` and `.h` files structured in directories.
* Implements translation unit bitcode DAGs and custom linking stages.
* Active benchmark sample: `multi_file_project` (compiles `main.c`, `helper.c`, and `math_utils.c` with headers).

---

## 2. Expanded 18-Sample Benchmark Catalog

1. `gemm`: Polybench General Matrix Multiply (Compute-heavy)
2. `quick_sort`: In-place recursive Quick Sort (Divide-and-conquer)
3. `bubble_sort`: Iterative Bubble Sort (Memory & Branch intensive)
4. `merge_sort`: Out-of-place Merge Sort (Memory allocation & recursion)
5. `binary_search`: Logarithmic binary search on sorted array
6. `matrix_mult`: Standard 2D matrix multiplication
7. `prime_sieve`: Sieve of Eratosthenes prime generation
8. `fibonacci`: Recursive vs iterative Fibonacci calculation
9. `tower_of_hanoi`: Classic recursive Hanoi puzzle
10. `pointer_array_ops`: Heavy pointer arithmetic and array indexing
11. `dynamic_memory`: Heap allocation (`malloc`/`free`) simulation
12. `nested_loops`: Deeply nested loop iteration
13. `multi_file_project`: Full multi-translation unit C architecture
14. `tc1_loop_heavy`: Loop-intensive stress test case
15. `tc2_security_bounds`: Array bounds checking and guard preserving
16. `tc3_math_intensive`: Complex integer and floating-point math
17. `tc4_security_null`: Null pointer check preservation
18. `security_buffer_overflow`: Buffer boundary security test case

---

## 3. Quick Start: Running on Windows

### Step 1: Navigate to Project Directory
```powershell
cd "TOACD_Enterprise_v35"
```

### Step 2: Activate Your Virtual Environment
```powershell
.\venv\Scripts\Activate.ps1
```

### Step 3: Launch the Web Dashboard on Port 8081
```powershell
python "Codes/Python Scripts/run_web.py" --host 127.0.0.1 --port 8081
```
*(Port 8081 allows running simultaneously alongside the GitHub version on 8080!)*

### Step 4: Open in Web Browser
Open your browser and navigate to:
👉 **[http://127.0.0.1:8081](http://127.0.0.1:8081)**

---

## 4. 🤖 AI Coding Assistant & Chatbot Setup

TOACD Enterprise features a built-in AI Coding Assistant operating under Architecture B+ (strictly decoupled from the compiler pipeline, purely advisory).

### Configuring Your Gemini API Key:
1. Obtain a 100% free API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
2. **In-Browser Setup (Easiest, No Restart Required):**
   * In the web interface at `http://127.0.0.1:8081`, click the **🤖 AI Assistant** tab in the right-side panel.
   * Click the **Provider Switcher** badge at the top of the chat panel.
   * Choose **Gemini** from the dropdown.
   * Paste your key into the **API Key** input box.
   * Click **Test Connection** (green checkmark confirmation).
   * Click **Save & Connect**.
3. **Alternative Setup via `.env` File:**
   * Copy `.env.example` to `.env`.
   * Add:
     ```ini
     TOACD_ASSISTANT_ENABLED=true
     TOACD_LLM_PROVIDER=gemini
     GEMINI_API_KEY=AIzaSyYourActualKeyHere
     TOACD_EXTERNAL_AI_ALLOWED=true
     ```
4. **100% Offline Mode (No API Key Required):**
   * Leave the provider set to **`mock`** (or select `Mock` in the dropdown). The system uses deterministic Explainable AI (XAI) grounded directly in the compilation run record.

---

## 5. Running the Test Suites

### Full Regression Suite (821 Tests):
```powershell
pytest "Codes/Python Scripts/moo/tests" -v
```
*(Expected: **821 passed, 0 failed** in ~95 seconds).*

### AI Assistant Test Suite (97 Tests):
```powershell
pytest "Codes/Python Scripts/web/tests/test_assistant.py" -v
```
*(Expected: **97 passed, 0 failed** in ~15 seconds).*

---

## 6. Execution Security Notice
* **Process Sandboxing:** In Enterprise v3.5, execution of compiled binaries is bounded by 5.0-second hard timeouts, process handle cleanup, and POSIX resource limit sandboxing (`setrlimit`).
* Always inspect custom C code before compiling. Never execute hostile code on bare-metal systems.
