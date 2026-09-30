# Week 7 Dataset Description

## Overview
This dataset contains mappings between three specific C benchmark programs compiled with LLVM `clang` under various optimization levels (-O0, -O1, -O2, -O3) and the resulting binary characteristics.

## Benchmark Programs
1. `loops_branches.c`: Contains complex looping structures (simple loops, nested loops) and deep conditional branches.
2. `memory_ops.c`: Demonstrates pointer math, array iterations, and dynamic memory allocations.
3. `security_checks.c`: Incorporates `assert()` statements and bounds-checking conditionals.
4. `math_heavy.c`: Simulates heavy floating-point arithmetic computation inside iterative loops.
5. `recursive_ops.c`: Simulates deep mathematical recursion using structures like Fibonacci and Ackermann functions.

## Feature Mapping (dataset.csv)
The generated `dataset.csv` contains the following columns mapping target variables to our new AI training features:

### General Outcomes
* **Program**: The name of the original C source file.
* **OptimizationLevel**: The `clang` flag used for compilation (-O0 to -O3).
* **CodeSizeBytes**: The size of the compiled object file (`.o`) on disk (in bytes). Higher optimization often reduces the code size, but aggressive optimizations (like loop unrolling in -O3) might increase it.
* **ExecTimeSeconds**: The average execution time of the binary. *Note: Currently set to N/A as the LLVM environment on this machine lacks the standard C library headers to compile to an executable, and `lli.exe` is missing to interpret the LLVM IR.*
* **SecurityChecks**: A simplistic heuristic indicating if security checks (strings like "Assertion failed" or explicit bounds checks) were retained in the resulting binary.
  * *N/A*: Not applicable for the benchmark.
  * *Present*: Checks were retained.
  * *Partially Removed*: Some checks were optimized away.
  * *Completely Removed*: All text indicating checks were optimized away.

### Static Code Features (Extracted from LLVM IR)
These features give insights into what the optimizer fundamentally changed about the code structure:
* **BasicBlocksCount**: Number of basic blocks. More blocks imply more complex branching logic.
* **InstructionsCount**: Total number of LLVM IR instructions.
* **BranchCount**: Number of branching instructions (`br` and `switch`).
* **MemInstCount**: Number of memory access and allocation instructions (`alloca`, `load`, `store`, `getelementptr`). High numbers indicate a memory-bound workload.
* **MathInstCount**: Number of integer arithmetic instructions (like `add`, `sub`, `mul`).
* **FloatInstCount**: Number of floating-point arithmetic instructions (like `fadd`, `fmul`).
* **VectorInstCount**: Number of vector operation instructions (like `insertelement` or `shufflevector`). Useful for detecting auto-vectorization.
* **CallInstCount**: Number of function calls. Reductions here usually indicate successful function inlining.

## LLVM IR Files
Alongside the dataset, intermediate LLVM IR code (`.ll` files) is generated for each program at each optimization level. These `.ll` files serve as the raw input "features" for ML-based compiler optimization models.
