# TOACD: Complete Windows Installation & Environment Guide
## Step-by-Step Setup Instructions for Academic Evaluators & Faculty

---

### 🌟 Introduction
This guide provides verified, step-by-step instructions to set up the host machine (Windows 10 / 11) to run both **TOACD-Core (GitHub Version)** and **TOACD Enterprise (v3.5)** locally without requiring any cloud hosting or external paid infrastructure.

---

## 1. System Prerequisites

Before starting, ensure the host machine has the following two core software components installed:

### 1.1. Python (Version 3.10 to 3.14)
* **Check Python Installation:**
  Open PowerShell or Command Prompt and run:
  ```powershell
  python --version
  ```
  *(Expected: Python 3.10.x, 3.11.x, 3.12.x, 3.13.x, or 3.14.x).*
* **If Python is NOT installed:**
  Download and install the official Windows 64-bit installer from [python.org](https://www.python.org/downloads/).  
  ⚠️ **CRITICAL:** Check the box that says: **"Add Python to PATH"** during installation.

---

### 1.2. LLVM / Clang Compiler Toolchain
TOACD compiles real C programs into LLVM Intermediate Representation (IR), analyzes 8 structural features, applies pass pipelines, and benchmarks native executables.

* **Check Clang Installation:**
  ```powershell
  clang --version
  ```
* **If Clang is NOT installed, choose one of these two simple options:**
  * **Option A (Fastest via Windows Package Manager — Recommended):**
    Open PowerShell as Administrator and run:
    ```powershell
    winget install LLVM.LLVM
    ```
    *Close and reopen your PowerShell window after installation.*
  * **Option B (Official Pre-built Installer):**
    Download the Windows 64-bit installer from the official [LLVM Releases Page](https://github.com/llvm/llvm-project/releases) (e.g. `LLVM-18.1.8-win64.exe` or `LLVM-17.0.6-win64.exe`).  
    ⚠️ **CRITICAL:** Select the option **"Add LLVM to the system PATH for all users"** during setup.
* **Verify Both Tools:**
  ```powershell
  clang --version
  opt --version
  ```

---

## 2. Virtual Environment Setup & Dependencies

It is recommended to run each project inside a dedicated Python virtual environment.

### Step 2.1: Open PowerShell in the Project Directory
Navigate to the extracted project folder (e.g. `TOACD_Enterprise_v35` or `TOACD_GitHub_Version`):
```powershell
cd "C:\path\to\your\project_folder"
```

### Step 2.2: Create a Python Virtual Environment
```powershell
python -m venv venv
```

### Step 2.3: Activate the Virtual Environment
```powershell
.\venv\Scripts\Activate.ps1
```

> [!NOTE]
> If PowerShell displays an execution policy error:  
> `File ... cannot be loaded because running scripts is disabled on this system.`  
> Run this single command in your PowerShell window to permit the virtual environment activation for this session:
> ```powershell
> Set-ExecutionPolicy -Scope Process RemoteSigned
> .\venv\Scripts\Activate.ps1
> ```

### Step 2.4: Install Python Dependencies
Run the standard pip installer:
```powershell
pip install -r requirements.txt
```

#### What is installed:
* `torch`: Deep Reinforcement Learning (DQN policy inference).
* `numpy`, `pandas`: Tabular telemetry, IR feature matrices, and Pareto frontier mathematics.
* `tornado`: Asynchronous HTTP REST server and Server-Sent Events (SSE) streaming engine.
* `matplotlib`: Graphical scatter plots for Multi-Objective Optimization frontiers.
* `ttkbootstrap`: Modern UI theme engine for the desktop GUI.
* `pytest`: Automated verification test runner.

> [!TIP]
> **PyTorch CPU Wheel Optimization:**  
> If you have a slow internet connection or wish to avoid downloading large GPU wheels, install the lightweight CPU-only version of PyTorch:
> ```powershell
> pip install torch --index-url https://download.pytorch.org/whl/cpu
> ```

---

## 3. Launching Both Projects

Both applications can run simultaneously on the same machine on different ports:

### 3.1. Running Project 1: GitHub Version (Port 8080)
Open a terminal in the `TOACD_GitHub_Version` folder:
```powershell
.\venv\Scripts\Activate.ps1
python "Codes/Python Scripts/run_web.py" --host 127.0.0.1 --port 8080
```
Open your browser to: 👉 **[http://127.0.0.1:8080](http://127.0.0.1:8080)**

---

### 3.2. Running Project 2: Enterprise v3.5 (Port 8081)
Open a second terminal in the `TOACD_Enterprise_v35` folder:
```powershell
.\venv\Scripts\Activate.ps1
python "Codes/Python Scripts/run_web.py" --host 127.0.0.1 --port 8081
```
Open your browser to: 👉 **[http://127.0.0.1:8081](http://127.0.0.1:8081)**

---

## 4. Troubleshooting & FAQ

| Problem | Root Cause | Exact Solution |
|---|---|---|
| `'clang' is not recognized as an internal or external command` | Clang is not registered in the system `PATH`. | 1. Check if `C:\Program Files\LLVM\bin\clang.exe` exists.<br>2. Add `C:\Program Files\LLVM\bin` to your Windows Environment Variables `Path`.<br>3. Restart PowerShell. |
| `Address already in use: 8080` | Port 8080 is held by another process or previous session. | Run the server on an alternate port: `--port 8085` or `--port 8090`. |
| `Running scripts is disabled on this system` | Default Windows PowerShell execution policy restriction. | Run: `Set-ExecutionPolicy -Scope Process RemoteSigned` before running `Activate.ps1`. |
| AI Chatbot returns error or fails connection test | Invalid or missing API key, or firewall blocking HTTPS requests. | Check your Gemini API key in the Provider Switcher modal, ensure internet access is active, or switch to the built-in `Mock` provider for 100% offline testing. |
| Pytest warnings regarding collection | Pytest informs that test classes with custom `__init__` cannot be instantiated directly. | This is normal expected behavior; run `pytest moo/tests -q` to view standard pass/fail metrics. |
