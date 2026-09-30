"""
moo/measurement.py — Execution timing, code-size, energy, and carbon
measurement harness for the TOACD MOO Stage 1 foundation.

Design principles
-----------------
* All measurement sources are EXPLICITLY labelled — we never hide the
  fact that energy / carbon figures are estimated.
* Non-zero return codes are NOT treated as failures; they are recorded
  faithfully.
* Every raw timing sample is preserved; statistics are derived from them.
* Code size comes from llvm-size .text section where available; we fall
  back to raw file size and label the source clearly.
* Energy is estimated via elapsed_time × TDP × utilisation.  A future
  hardware backend can replace estimate_energy() without touching callers.
* Carbon is transparently derived from energy with a configurable grid
  intensity.
"""

from __future__ import annotations

import math
import os
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

from . import config


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TimingStats:
    """Descriptive statistics derived from raw timing samples (nanoseconds)."""
    n_samples: int
    median_ns: float
    min_ns: float
    max_ns: float
    mean_ns: float
    stdev_ns: float          # population-based; 0.0 when n_samples == 1
    median_s: float          # convenience seconds
    mean_s: float

    @staticmethod
    def from_samples(samples_ns: list[int]) -> "TimingStats":
        """Compute statistics from a list of raw nanosecond timings."""
        if not samples_ns:
            raise ValueError("Cannot compute TimingStats from empty sample list")
        n = len(samples_ns)
        med = statistics.median(samples_ns)
        mn = min(samples_ns)
        mx = max(samples_ns)
        mean = statistics.mean(samples_ns)
        std = statistics.stdev(samples_ns) if n > 1 else 0.0
        return TimingStats(
            n_samples=n,
            median_ns=float(med),
            min_ns=float(mn),
            max_ns=float(mx),
            mean_ns=float(mean),
            stdev_ns=float(std),
            median_s=float(med) / 1e9,
            mean_s=float(mean) / 1e9,
        )

    def to_dict(self) -> dict:
        return {
            "n_samples": self.n_samples,
            "median_ns": self.median_ns,
            "min_ns": self.min_ns,
            "max_ns": self.max_ns,
            "mean_ns": self.mean_ns,
            "stdev_ns": self.stdev_ns,
            "median_s": self.median_s,
            "mean_s": self.mean_s,
        }


@dataclass
class ExecutionRecord:
    """
    Result of running an executable (one warm-up or one measured run).

    A non-zero return_code is NOT automatically invalid; it is recorded
    faithfully and the caller decides what it means.
    """
    return_code: int
    stdout: str
    stderr: str
    elapsed_ns: int          # wall-clock elapsed time in nanoseconds
    timed_out: bool = False
    error: Optional[str] = None   # subprocess-level error (not rc != 0)


@dataclass
class CodeSizeResult:
    """
    Code size measurement for a compiled executable.

    Prefer .text_size_bytes (PE .text section via llvm-size).
    file_size_bytes is always available as a fallback.
    primary_metric and size_source describe exactly what is being reported.
    """
    file_path: str
    file_size_bytes: int
    text_size_bytes: Optional[int]    # None if llvm-size unavailable
    data_size_bytes: Optional[int]    # .data section
    bss_size_bytes: Optional[int]     # .bss section
    size_source: str                  # e.g. "llvm-size .text" or "file size fallback"
    primary_metric: str               # "text_size_bytes" or "file_size_bytes"
    primary_value: int                # the recommended size figure
    llvm_size_raw: Optional[str] = None   # raw llvm-size output for auditing

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "text_size_bytes": self.text_size_bytes,
            "data_size_bytes": self.data_size_bytes,
            "bss_size_bytes": self.bss_size_bytes,
            "size_source": self.size_source,
            "primary_metric": self.primary_metric,
            "primary_value": self.primary_value,
            "llvm_size_raw": self.llvm_size_raw,
        }


@dataclass
class EnergyResult:
    """
    Energy estimate for one measurement session.

    energy_is_estimated is ALWAYS True in this implementation; a future
    hardware backend may set it to False.  The energy_source field must
    always describe the origin so audit logs are self-explanatory.
    """
    energy_joules: float
    energy_source: str    # human-readable description of how it was derived
    energy_is_estimated: bool   # True = estimated; False = hardware measured

    def to_dict(self) -> dict:
        return {
            "energy_joules": self.energy_joules,
            "energy_source": self.energy_source,
            "energy_is_estimated": self.energy_is_estimated,
        }


@dataclass
class CarbonResult:
    """
    Carbon footprint derived from energy.

    carbon_is_estimated is True whenever energy_is_estimated is True.
    grid_intensity_g_per_kwh and its source are always stored so results
    are reproducible from a different grid region.
    """
    carbon_grams: float
    grid_intensity_g_per_kwh: float
    grid_intensity_source: str
    energy_source: str          # forwarded from EnergyResult for self-containedness
    carbon_is_estimated: bool   # True when derived from estimated energy

    def to_dict(self) -> dict:
        return {
            "carbon_grams": self.carbon_grams,
            "grid_intensity_g_per_kwh": self.grid_intensity_g_per_kwh,
            "grid_intensity_source": self.grid_intensity_source,
            "energy_source": self.energy_source,
            "carbon_is_estimated": self.carbon_is_estimated,
        }


@dataclass
class MeasurementResult:
    """
    Complete measurement record for one executable under one strategy.

    Fields
    ------
    strategy            — optimization strategy label (e.g. "-O2")
    exe_path            — absolute path of the measured executable
    warmup_runs         — number of warm-up runs performed
    measure_runs        — number of timed runs performed
    raw_samples_ns      — every timed sample in nanoseconds (length == measure_runs,
                          unless some runs timed out or errored)
    timing              — TimingStats derived from raw_samples_ns; None if no
                          valid samples were collected
    last_return_code    — return code of the last measured run
    last_stdout         — stdout of the last measured run
    last_stderr         — stderr of the last measured run
    all_return_codes    — return code from every measured run
    code_size           — CodeSizeResult for the executable
    energy              — EnergyResult (estimated)
    carbon              — CarbonResult derived from energy
    measurement_error   — subprocess-level error string; None on success
    """
    strategy: str
    exe_path: str
    warmup_runs: int
    measure_runs: int
    raw_samples_ns: list[int] = field(default_factory=list)
    timing: Optional[TimingStats] = None
    last_return_code: Optional[int] = None
    last_stdout: str = ""
    last_stderr: str = ""
    all_return_codes: list[int] = field(default_factory=list)
    code_size: Optional[CodeSizeResult] = None
    energy: Optional[EnergyResult] = None
    carbon: Optional[CarbonResult] = None
    measurement_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "exe_path": self.exe_path,
            "warmup_runs": self.warmup_runs,
            "measure_runs": self.measure_runs,
            "raw_samples_ns": self.raw_samples_ns,
            "timing": self.timing.to_dict() if self.timing else None,
            "last_return_code": self.last_return_code,
            "last_stdout": self.last_stdout,
            "last_stderr": self.last_stderr,
            "all_return_codes": self.all_return_codes,
            "code_size": self.code_size.to_dict() if self.code_size else None,
            "energy": self.energy.to_dict() if self.energy else None,
            "carbon": self.carbon.to_dict() if self.carbon else None,
            "measurement_error": self.measurement_error,
        }


# ---------------------------------------------------------------------------
# Core measurement functions
# ---------------------------------------------------------------------------

def _run_once(
    exe_path: str,
    timeout_s: int = config.RUN_TIMEOUT_S,
    args: list[str] | None = None,
) -> ExecutionRecord:
    """
    Execute *exe_path* once and return an ExecutionRecord.

    A non-zero return code is NOT an error at this level — it is captured
    and returned.  Only subprocess-level failures (process launch errors,
    timeouts) set the error field.
    """
    cmd = [exe_path] + (args or [])
    t0 = time.perf_counter_ns()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        elapsed_ns = time.perf_counter_ns() - t0
        return ExecutionRecord(
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            elapsed_ns=elapsed_ns,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ns = time.perf_counter_ns() - t0
        return ExecutionRecord(
            return_code=-1,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            elapsed_ns=elapsed_ns,
            timed_out=True,
            error=f"TimeoutExpired after {timeout_s}s",
        )
    except Exception as exc:
        elapsed_ns = time.perf_counter_ns() - t0
        return ExecutionRecord(
            return_code=-1,
            stdout="",
            stderr="",
            elapsed_ns=elapsed_ns,
            error=str(exc),
        )


def measure_execution(
    exe_path: str,
    strategy: str = "",
    warmup_runs: int = config.WARMUP_RUNS,
    measure_runs: int = config.MEASURE_RUNS,
    timeout_s: int = config.RUN_TIMEOUT_S,
    args: list[str] | None = None,
) -> MeasurementResult:
    """
    Measure the execution time of *exe_path*.

    Parameters
    ----------
    exe_path     : absolute path to the compiled executable
    strategy     : label for this measurement (e.g. "-O2")
    warmup_runs  : number of un-timed warm-up executions
    measure_runs : number of timed executions (raw samples retained)
    timeout_s    : per-run wall-clock timeout in seconds
    args         : extra command-line arguments passed to the executable

    Returns
    -------
    MeasurementResult with timing stats, raw samples, and return codes.
    Non-zero return codes are NOT filtered out or replaced with zeros.
    """
    result = MeasurementResult(
        strategy=strategy,
        exe_path=exe_path,
        warmup_runs=warmup_runs,
        measure_runs=measure_runs,
    )

    if not os.path.isfile(exe_path):
        result.measurement_error = f"Executable not found: {exe_path}"
        return result

    # --- Warm-up runs (not timed) ---
    for _ in range(warmup_runs):
        _run_once(exe_path, timeout_s=timeout_s, args=args)

    # --- Timed measurement runs ---
    raw_samples: list[int] = []
    all_rcs: list[int] = []
    last: ExecutionRecord | None = None

    for _ in range(measure_runs):
        rec = _run_once(exe_path, timeout_s=timeout_s, args=args)
        last = rec
        all_rcs.append(rec.return_code)
        if rec.error is None:
            # Only collect timing for runs that didn't error at the subprocess level.
            # Timed-out runs still contribute their elapsed time (it is meaningful).
            raw_samples.append(rec.elapsed_ns)
        # Note: we do NOT skip non-zero return codes — they are still timed.

    result.raw_samples_ns = raw_samples
    result.all_return_codes = all_rcs

    if last is not None:
        result.last_return_code = last.return_code
        result.last_stdout = last.stdout
        result.last_stderr = last.stderr
        if last.error:
            result.measurement_error = last.error

    if raw_samples:
        result.timing = TimingStats.from_samples(raw_samples)
        # Derive energy and carbon from the median elapsed time
        result.energy = estimate_energy(result.timing.median_s)
        result.carbon = derive_carbon(result.energy)
    else:
        result.measurement_error = (
            result.measurement_error or "No valid timing samples collected"
        )

    return result


# ---------------------------------------------------------------------------
# Code size
# ---------------------------------------------------------------------------

def measure_code_size(exe_path: str) -> CodeSizeResult:
    """
    Measure the code size of a compiled executable.

    Primary metric: PE .text section size via llvm-size (when available).
    Fallback: raw file size, clearly labelled.

    The .text, .data, and .bss section sizes are parsed from llvm-size
    output.  The raw llvm-size output is preserved for auditing.

    Returns a CodeSizeResult whose size_source and primary_metric fields
    always describe exactly what is being reported.
    """
    file_size = os.path.getsize(exe_path) if os.path.isfile(exe_path) else 0

    if config.LLVM_SIZE_PATH and os.path.isfile(config.LLVM_SIZE_PATH):
        text_sz, data_sz, bss_sz, raw_out = _run_llvm_size(exe_path)
        if text_sz is not None:
            return CodeSizeResult(
                file_path=exe_path,
                file_size_bytes=file_size,
                text_size_bytes=text_sz,
                data_size_bytes=data_sz,
                bss_size_bytes=bss_sz,
                size_source="llvm-size .text section (PE format)",
                primary_metric="text_size_bytes",
                primary_value=text_sz,
                llvm_size_raw=raw_out,
            )
        # llvm-size ran but parsing failed — fall through to file size
        return CodeSizeResult(
            file_path=exe_path,
            file_size_bytes=file_size,
            text_size_bytes=None,
            data_size_bytes=None,
            bss_size_bytes=None,
            size_source=(
                f"file size fallback (llvm-size ran but output unparseable): {raw_out!r}"
            ),
            primary_metric="file_size_bytes",
            primary_value=file_size,
            llvm_size_raw=raw_out,
        )

    # llvm-size not available
    return CodeSizeResult(
        file_path=exe_path,
        file_size_bytes=file_size,
        text_size_bytes=None,
        data_size_bytes=None,
        bss_size_bytes=None,
        size_source=(
            "file size fallback (llvm-size not found; set TOACD_SIZE_TOOL to enable)"
        ),
        primary_metric="file_size_bytes",
        primary_value=file_size,
        llvm_size_raw=None,
    )


def _run_llvm_size(exe_path: str) -> tuple[Optional[int], Optional[int], Optional[int], str]:
    """
    Run llvm-size on *exe_path* and parse .text / .data / .bss section sizes.

    Returns (text_bytes, data_bytes, bss_bytes, raw_output).
    Any field is None if not found in the output.
    """
    try:
        r = subprocess.run(
            [config.LLVM_SIZE_PATH, exe_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        raw = (r.stdout + r.stderr).strip()
    except Exception as exc:
        return None, None, None, f"<error: {exc}>"

    # llvm-size --format=sysv output looks like:
    #   section          size      addr
    #   .text            1234      4096
    #   .data             512      8192
    #   .bss              256      12288
    #
    # Default (Berkeley) output looks like:
    #   text    data     bss     dec     hex filename
    #   1234     512     256    2002     7d2  foo.exe
    #
    # We try Berkeley first (simpler), then sysv.

    text_sz = data_sz = bss_sz = None

    lines = raw.splitlines()

    # Try Berkeley (default) format: first non-header line, columns 0/1/2
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("text"):
            continue
        parts = stripped.split()
        if len(parts) >= 3:
            try:
                text_sz = int(parts[0])
                data_sz = int(parts[1])
                bss_sz  = int(parts[2])
                return text_sz, data_sz, bss_sz, raw
            except ValueError:
                pass

    # Try sysv format: look for lines matching "<name> <size> <addr>"
    import re
    for line in lines:
        m = re.match(r'^\s*(\.\w+)\s+(\d+)\s+', line)
        if not m:
            continue
        name, sz = m.group(1), int(m.group(2))
        if name == ".text":
            text_sz = sz
        elif name == ".data":
            data_sz = sz
        elif name == ".bss":
            bss_sz = sz

    return text_sz, data_sz, bss_sz, raw


# ---------------------------------------------------------------------------
# Energy estimation
# ---------------------------------------------------------------------------

def estimate_energy(elapsed_seconds: float) -> EnergyResult:
    """
    Estimate CPU energy consumption from elapsed wall-clock time.

    Formula (transparent):
        energy_joules = elapsed_seconds × CPU_TDP_WATTS × CPU_UTILISATION

    This is NOT a hardware measurement.  The result is always marked as
    estimated (energy_is_estimated=True).  Override CPU_TDP_WATTS and
    CPU_UTILISATION via environment variables to calibrate for real hardware.

    A future hardware backend (e.g. Intel RAPL, NVML) can replace this
    function without changing any callers.
    """
    energy_joules = elapsed_seconds * config.CPU_TDP_WATTS * config.CPU_UTILISATION
    return EnergyResult(
        energy_joules=energy_joules,
        energy_source=config.ENERGY_SOURCE,
        energy_is_estimated=config.ENERGY_IS_ESTIMATED,
    )


# ---------------------------------------------------------------------------
# Carbon derivation
# ---------------------------------------------------------------------------

def derive_carbon(energy: EnergyResult) -> CarbonResult:
    """
    Derive carbon grams from an EnergyResult and the configured grid intensity.

    Formula (transparent):
        carbon_grams = energy_joules
                       × grid_intensity_g_per_kwh
                       / 3_600_000   [J → kWh conversion]

    The result is marked estimated whenever the energy is estimated.
    All constants and their sources are stored in the result for auditing.
    """
    carbon_grams = (
        energy.energy_joules
        * config.GRID_INTENSITY_G_PER_KWH
        / 3_600_000.0
    )
    return CarbonResult(
        carbon_grams=carbon_grams,
        grid_intensity_g_per_kwh=config.GRID_INTENSITY_G_PER_KWH,
        grid_intensity_source=config.GRID_INTENSITY_SOURCE,
        energy_source=energy.energy_source,
        carbon_is_estimated=energy.energy_is_estimated or config.CARBON_IS_ESTIMATED,
    )


# ---------------------------------------------------------------------------
# Full measurement pipeline (convenience wrapper)
# ---------------------------------------------------------------------------

def measure_all(
    exe_path: str,
    strategy: str = "",
    warmup_runs: int = config.WARMUP_RUNS,
    measure_runs: int = config.MEASURE_RUNS,
    timeout_s: int = config.RUN_TIMEOUT_S,
    args: list[str] | None = None,
) -> MeasurementResult:
    """
    Run the full measurement pipeline: timing + code size.

    Energy and carbon are derived inside measure_execution from the median
    elapsed time.  Code size is measured separately and attached.

    Returns a complete MeasurementResult.
    """
    result = measure_execution(
        exe_path=exe_path,
        strategy=strategy,
        warmup_runs=warmup_runs,
        measure_runs=measure_runs,
        timeout_s=timeout_s,
        args=args,
    )
    # Attach code size (independent of timing; always run even if timing failed)
    if os.path.isfile(exe_path):
        result.code_size = measure_code_size(exe_path)
    return result
