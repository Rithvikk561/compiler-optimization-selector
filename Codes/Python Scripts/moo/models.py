"""
moo/models.py — Data-model dataclasses for the MOO diagnostic tool.

These are pure data containers; no compilation logic lives here.
"""

from __future__ import annotations

import dataclasses
from typing import Optional


@dataclasses.dataclass
class ToolInfo:
    """Describes a discovered toolchain executable."""
    name: str           # human label, e.g. "clang"
    path: Optional[str] # absolute path, or None if not found
    version_string: str = ""  # first line of --version output
    found: bool = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class IncompatibilityWarning:
    """Records a detected toolchain incompatibility."""
    kind: str       # e.g. "version_mismatch", "tool_missing"
    detail: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class BaselineInfo:
    """IR and executable information for the unoptimized reference build."""
    ir_path: Optional[str]
    ir_hash: Optional[str]          # SHA-256 of the IR file
    ir_command: Optional[str]       # exact command that produced the IR
    ir_returncode: Optional[int]
    ir_stdout: str = ""
    ir_stderr: str = ""
    ir_ok: bool = False

    exe_path: Optional[str] = None
    exe_command: Optional[str] = None
    exe_returncode: Optional[int] = None
    exe_stdout: str = ""
    exe_stderr: str = ""
    exe_ok: bool = False

    # Reference run results (used for correctness comparison)
    run_returncode: Optional[int] = None
    run_stdout: str = ""
    run_stderr: str = ""
    run_ok: bool = False

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class CorrectnessResult:
    """Outcome of comparing an optimized run against the reference run."""
    checked: bool           # False if executable could not be built
    correct: bool           # True if behaviour matches reference
    ref_exit_code: Optional[int]
    opt_exit_code: Optional[int]
    ref_stdout: str = ""
    opt_stdout: str = ""
    ref_stderr: str = ""
    opt_stderr: str = ""
    stdout_match: bool = False
    stderr_match: bool = False
    exit_code_match: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class StrategyResult:
    """Full diagnostic record for one optimization strategy on one source file."""
    strategy_index: int         # 0-based index into ACTIONS
    strategy_name: str          # e.g. "-O2" or "mem2reg,instcombine"
    strategy_kind: str          # "clang_flag" | "opt_passes"

    # --- IR generation ---
    ir_command: Optional[str] = None
    ir_returncode: Optional[int] = None
    ir_stdout: str = ""
    ir_stderr: str = ""
    ir_path: Optional[str] = None
    ir_hash: Optional[str] = None
    ir_ok: bool = False

    # --- Executable build ---
    exe_command: Optional[str] = None
    exe_returncode: Optional[int] = None
    exe_stdout: str = ""
    exe_stderr: str = ""
    exe_path: Optional[str] = None
    exe_ok: bool = False

    # --- IR difference ---
    ir_changed: Optional[bool] = None      # None if baseline or opt IR unavailable
    ir_hash_duplicate_of: Optional[int] = None  # strategy index with same hash

    # --- Correctness ---
    correctness: Optional[CorrectnessResult] = None

    # --- Overall status ---
    status: str = "UNKNOWN"     # "PASS" | "FAIL" | "ERROR"
    failure_reason: str = ""

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        if self.correctness is not None:
            d["correctness"] = self.correctness.to_dict()
        return d


@dataclasses.dataclass
class FileReport:
    """Diagnostic report for a single source file across all strategies."""
    source_file: str
    source_path: Optional[str]
    timestamp: str

    # Toolchain info (same for every file; included per-file for auditability)
    clang_info: Optional[ToolInfo] = None
    opt_info: Optional[ToolInfo] = None
    incompatibilities: list = dataclasses.field(default_factory=list)

    baseline: Optional[BaselineInfo] = None
    strategy_results: list = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "source_file": self.source_file,
            "source_path": self.source_path,
            "timestamp": self.timestamp,
            "clang_info": self.clang_info.to_dict() if self.clang_info else None,
            "opt_info": self.opt_info.to_dict() if self.opt_info else None,
            "incompatibilities": [i.to_dict() for i in self.incompatibilities],
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "strategy_results": [r.to_dict() for r in self.strategy_results],
        }
        return d
