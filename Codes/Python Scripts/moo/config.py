"""
moo/config.py — Configuration and environment discovery for the MOO
diagnostic tool.

Discovers toolchain paths from the environment without hardcoding
personal usernames or download paths. Falls back gracefully but
NEVER silently substitutes one tool for another.

Reads ACTIONS directly from the existing ml_optimizer.py so that
the diagnostic reflects the actual deployed strategies.
"""

import os
import sys
import shutil
import subprocess
import importlib.util


# ---------------------------------------------------------------------------
# Toolchain discovery helpers
# ---------------------------------------------------------------------------

def _run_version(path: str) -> str:
    """Return the first non-empty stdout/stderr line from `<path> --version`."""
    try:
        r = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, timeout=10
        )
        out = (r.stdout + r.stderr).strip()
        return out.splitlines()[0] if out else "<no output>"
    except Exception as exc:
        return f"<error: {exc}>"


def _find_tool(tool_name: str, env_var: str = None,
               common_paths: list = None) -> str | None:
    """
    Search for *tool_name* (e.g. 'clang.exe') in order:
      1. Value of environment variable *env_var* (if set and points to a file).
      2. Each entry in *common_paths* that exists.
      3. PATH (shutil.which).
    Returns the absolute path string or None.
    """
    # 1. Environment variable override
    if env_var:
        val = os.environ.get(env_var, "")
        if val and os.path.isfile(val):
            return os.path.abspath(val)

    # 2. Well-known install locations (not personal-username-specific)
    for p in (common_paths or []):
        if os.path.isfile(p):
            return os.path.abspath(p)

    # 3. PATH
    found = shutil.which(tool_name)
    if found:
        return os.path.abspath(found)

    return None


# ---------------------------------------------------------------------------
# Discover clang
# ---------------------------------------------------------------------------
CLANG_COMMON = [
    r"C:\Program Files\LLVM\bin\clang.exe",
    r"C:\Program Files (x86)\LLVM\bin\clang.exe",
    r"/usr/bin/clang",
    r"/usr/local/bin/clang",
]

CLANG_PATH: str | None = _find_tool(
    "clang.exe",
    env_var="TOACD_CLANG_PATH",
    common_paths=CLANG_COMMON,
)

# ---------------------------------------------------------------------------
# Discover opt — the separately installed LLVM opt.exe
# The environment carries a newer opt.exe that may differ from the system
# clang version.  We probe known install prefixes; the user may also set
# TOACD_OPT_PATH to override.
# We scan %LLVM_PREFIX% / %LLVM_ROOT% first, then common paths, then PATH.
# ---------------------------------------------------------------------------
_llvm_prefixes: list[str] = []

for _ev in ("LLVM_PREFIX", "LLVM_ROOT", "LLVM_DIR", "LLVM_HOME"):
    _v = os.environ.get(_ev, "")
    if _v:
        _llvm_prefixes.append(os.path.join(_v, "bin", "opt.exe"))
        _llvm_prefixes.append(os.path.join(_v, "opt.exe"))

# Scan all LLVM-looking directories on PATH for opt.exe
for _dir in os.environ.get("PATH", "").split(os.pathsep):
    if "llvm" in _dir.lower() or "clang" in _dir.lower():
        _candidate = os.path.join(_dir, "opt.exe")
        if os.path.isfile(_candidate):
            _llvm_prefixes.append(_candidate)


def _read_opt_path_from_project() -> str | None:
    """
    Read OPT_PATH from the existing optimization_selector.py.
    This is the same opt.exe the project itself uses, so we use the same one.
    Returns None if the file cannot be parsed or the path does not exist.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))   # .../moo/
    ps_dir = os.path.dirname(script_dir)                       # .../Python Scripts/
    sel_path = os.path.join(ps_dir, "optimization_selector.py")
    if not os.path.isfile(sel_path):
        return None
    try:
        # Parse the file as text — avoid importing it (it imports ml_optimizer
        # which imports torch, which may not be installed).
        import re as _re
        with open(sel_path, encoding="utf-8", errors="replace") as fh:
            src = fh.read()
        # Match: OPT_PATH = r"..." or OPT_PATH = "..."
        m = _re.search(r'^OPT_PATH\s*=\s*[r]?["\'](.+?)["\']', src, _re.MULTILINE)
        if m:
            p = m.group(1)
            if os.path.isfile(p):
                return os.path.abspath(p)
    except Exception:
        pass
    return None


_project_opt = _read_opt_path_from_project()

OPT_COMMON: list[str] = (
    ([_project_opt] if _project_opt else [])
    + _llvm_prefixes
    + [
        r"C:\Program Files\LLVM\bin\opt.exe",
        r"C:\Program Files (x86)\LLVM\bin\opt.exe",
        r"/usr/bin/opt",
        r"/usr/local/bin/opt",
    ]
)

OPT_PATH: str | None = _find_tool(
    "opt.exe",
    env_var="TOACD_OPT_PATH",
    common_paths=OPT_COMMON,
)

# If PATH-based discovery found the system clang's opt (same major), keep it.
# But if clang and opt report different LLVM majors we flag a warning.
# (Actual incompatibility detection happens in toolchain.py.)

# ---------------------------------------------------------------------------
# Read ACTIONS from the actual ml_optimizer.py
# ---------------------------------------------------------------------------

def _load_actions_from_project() -> list[str]:
    """
    Dynamically import ACTIONS from the real ml_optimizer.py so that the
    diagnostic always tests the same strategies the project uses.
    Returns a list of action strings, or raises ImportError.
    """
    # ml_optimizer.py lives two directories up from this file
    script_dir = os.path.dirname(os.path.abspath(__file__))           # .../moo/
    ps_dir = os.path.dirname(script_dir)                              # .../Python Scripts/
    ml_path = os.path.join(ps_dir, "ml_optimizer.py")

    if not os.path.isfile(ml_path):
        raise FileNotFoundError(f"ml_optimizer.py not found at: {ml_path}")

    spec = importlib.util.spec_from_file_location("_ml_optimizer_ref", ml_path)
    mod = importlib.util.module_from_spec(spec)

    # ml_optimizer imports torch / numpy — those must be installed.
    # If they are not, we fall back to the known hardcoded list and log a
    # warning; we do NOT silently pretend we loaded the real list.
    try:
        spec.loader.exec_module(mod)
    except ImportError as exc:
        import warnings
        warnings.warn(
            f"Could not import ml_optimizer.py ({exc}). "
            "Falling back to hardcoded ACTIONS list. "
            "Ensure torch/numpy are installed to use the live definition.",
            RuntimeWarning
        )
        return _FALLBACK_ACTIONS[:]

    actions = getattr(mod, "ACTIONS", None)
    if not isinstance(actions, list) or not actions:
        raise ValueError("ACTIONS in ml_optimizer.py is missing or empty.")
    return list(actions)


# Fallback — only used when ml_optimizer.py cannot be imported due to missing
# optional dependencies (torch, numpy).  This list MUST be kept in sync with
# ml_optimizer.py manually.
_FALLBACK_ACTIONS: list[str] = [
    "-O0",
    "-O1",
    "-O2",
    "-O3",
    "mem2reg,instcombine",
    "mem2reg,simplifycfg",
    "mem2reg,instcombine,simplifycfg,dce",
    "mem2reg,instcombine,simplifycfg,gvn,loop-unroll",
    "mem2reg,instcombine,simplifycfg,dce,gvn,loop-unroll",
]

ACTIONS: list[str] = _load_actions_from_project()

# ---------------------------------------------------------------------------
# Locate test files from the existing project
# ---------------------------------------------------------------------------
def _locate_test_file(filename: str) -> str | None:
    """
    Search for *filename* relative to the project root (test_cases/ directory).
    Returns the absolute path or None.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))           # .../moo/
    ps_dir = os.path.dirname(script_dir)                              # .../Python Scripts/
    codes_dir = os.path.dirname(ps_dir)                               # .../Codes/
    test_dir = os.path.join(codes_dir, "test_cases")

    candidate = os.path.join(test_dir, filename)
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)

    # Broader search upward from Codes/
    for root, _dirs, files in os.walk(codes_dir):
        if filename in files:
            return os.path.abspath(os.path.join(root, filename))

    return None


TEST_FILE_TC1: str | None = _locate_test_file("TC1_loop_heavy.c")
TEST_FILE_SC: str | None = _locate_test_file("security_checks.c")

TEST_FILES: list[dict] = [
    {
        "name": "TC1_loop_heavy.c",
        "path": TEST_FILE_TC1,
        # TC1 is a normal program; expected exit code is 0.
        "expected_exit_code": None,  # None = match reference behaviour
        "non_zero_ok": False,
    },
    {
        "name": "security_checks.c",
        "path": TEST_FILE_SC,
        # security_checks.c returns assert_failed which may be non-zero;
        # correctness is defined as matching the reference run, NOT as == 0.
        "expected_exit_code": None,  # None = match reference behaviour
        "non_zero_ok": True,
    },
]

# ---------------------------------------------------------------------------
# JSON report output directory
# ---------------------------------------------------------------------------
_REPORT_DIR_DEFAULT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "reports"
)
REPORT_DIR: str = os.environ.get("TOACD_REPORT_DIR", _REPORT_DIR_DEFAULT)


# ---------------------------------------------------------------------------
# Measurement constants — timing
# ---------------------------------------------------------------------------

# Number of warm-up executions before recording timing samples.
# Warm-up lets the OS loader, filesystem cache, and CPU branch predictor
# settle.  Configurable via TOACD_WARMUP_RUNS.
WARMUP_RUNS: int = int(os.environ.get("TOACD_WARMUP_RUNS", "3"))

# Number of timed measurement runs per candidate.
# Configurable via TOACD_MEASURE_RUNS.
MEASURE_RUNS: int = int(os.environ.get("TOACD_MEASURE_RUNS", "10"))

# Hard per-run timeout in seconds (wall-clock).
# Configurable via TOACD_RUN_TIMEOUT_S.
RUN_TIMEOUT_S: int = int(os.environ.get("TOACD_RUN_TIMEOUT_S", "30"))


# ---------------------------------------------------------------------------
# Measurement constants — code size
# ---------------------------------------------------------------------------

# Tool used for section-level code-size measurement.
# "llvm-size" is preferred; falls back to raw file size if unavailable.
# Configurable via TOACD_SIZE_TOOL (path to llvm-size executable).
LLVM_SIZE_PATH: str | None = _find_tool(
    "llvm-size.exe",
    env_var="TOACD_SIZE_TOOL",
    common_paths=[
        r"C:\Program Files\LLVM\bin\llvm-size.exe",
        r"C:\Program Files (x86)\LLVM\bin\llvm-size.exe",
        r"/usr/bin/llvm-size",
        r"/usr/local/bin/llvm-size",
    ],
)


# ---------------------------------------------------------------------------
# Measurement constants — energy (estimated)
#
# True hardware energy measurement (e.g. Intel RAPL, NVML) requires either
# kernel-level access or vendor SDK.  On this Windows workstation neither is
# available without administrative privilege or a specialised tool.
#
# POLICY: we do NOT pretend to measure hardware energy.
# Instead we provide a transparent CPU-time × TDP estimate, clearly marked
# as "estimated".  The architecture allows a real hardware backend to be
# plugged in later.
#
# The estimate formula is:
#   energy_joules ≈ elapsed_seconds × tdp_watts × utilisation_fraction
#
# All three factors are explicit and configurable.
# ---------------------------------------------------------------------------

# Thermal Design Power of the CPU, in Watts.
# This is the manufacturer's rated sustained power, NOT a live measurement.
# Override with TOACD_CPU_TDP_WATTS to match the actual hardware.
CPU_TDP_WATTS: float = float(os.environ.get("TOACD_CPU_TDP_WATTS", "45.0"))

# Assumed CPU utilisation fraction during a single-threaded benchmark.
# 1.0 = full core; 0.5 = half core.
# Override with TOACD_CPU_UTILISATION.
CPU_UTILISATION: float = float(os.environ.get("TOACD_CPU_UTILISATION", "1.0"))

# Whether energy measurement is estimated (True) or from real hardware (False).
# This MUST be True in this environment; a future hardware backend would set it
# to False.  Do NOT change this to False without wiring up actual hardware
# counters.
ENERGY_IS_ESTIMATED: bool = True

# Human-readable description of the energy source for audit trails.
ENERGY_SOURCE: str = (
    os.environ.get("TOACD_ENERGY_SOURCE", "")
    or f"estimated: elapsed_time * TDP({CPU_TDP_WATTS}W) * utilisation({CPU_UTILISATION})"
)


# ---------------------------------------------------------------------------
# Measurement constants — carbon
#
# Carbon intensity of the electricity grid, in gCO2eq/kWh.
# Source: IEA 2023 world average ≈ 436 gCO2eq/kWh.
# Override with TOACD_GRID_INTENSITY_G_PER_KWH to use a country/region-
# specific value.  The unit and origin MUST be documented in results.
#
# carbon_grams = energy_joules / 3_600_000 (Wh) * 1000 (Wh→kWh) * intensity
#              = energy_joules * intensity / 3_600_000
# ---------------------------------------------------------------------------

GRID_INTENSITY_G_PER_KWH: float = float(
    os.environ.get("TOACD_GRID_INTENSITY_G_PER_KWH", "436.0")
)
GRID_INTENSITY_SOURCE: str = (
    os.environ.get("TOACD_GRID_INTENSITY_SOURCE", "")
    or "IEA 2023 world average (436 gCO2eq/kWh); override via TOACD_GRID_INTENSITY_G_PER_KWH"
)

# Carbon is estimated whenever energy is estimated.
CARBON_IS_ESTIMATED: bool = ENERGY_IS_ESTIMATED


# ---------------------------------------------------------------------------
# Measurement quality thresholds  (Week 5 addition)
# ---------------------------------------------------------------------------

# Coefficient-of-variation threshold for timing noise detection.
# If stdev / median > CV_WARN_THRESHOLD the measurement is flagged as noisy
# (timing_is_reliable = False in MeasurementResult).
# A value of 0.10 means "flag when noise exceeds 10% of the median time".
# Override with TOACD_CV_WARN_THRESHOLD.
CV_WARN_THRESHOLD: float = float(
    os.environ.get("TOACD_CV_WARN_THRESHOLD", "0.10")
)

# Minimum number of valid timing samples (non-timeout, non-error) required
# for timing_is_reliable to be True.  Fewer samples means the median and CV
# are not statistically robust.
# Override with TOACD_MIN_RELIABLE_SAMPLES.
MIN_RELIABLE_SAMPLES: int = int(
    os.environ.get("TOACD_MIN_RELIABLE_SAMPLES", "5")
)

