"""
moo/bench/corpus.py — Deterministic corpus manifest builder.

Scans Codes/test_cases/ for existing C programs and produces a
deterministically-ordered CorpusEntry list.  The ordering is by program_id
(alphabetical / numeric prefix).

SHA-256 digests are computed from the raw source bytes so that corpus identity
is stable across platforms and filesystem timestamps.

Generated programs (from moo.bench.generator) are identified by origin
"generated" and carry generator metadata.

The manifest can be serialized to JSON and round-tripped via from_dict().
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Optional, Sequence

from .schema import CorpusEntry

# ---------------------------------------------------------------------------
# Existing test_cases discovery
# ---------------------------------------------------------------------------

# Patterns for files that should be excluded from the benchmark corpus even
# if they have a .c extension (non-benchmark C files found in test_cases/).
_EXCLUDE_PATTERNS: list[str] = [
    r".*_ai_opt\..*",      # pre-compiled AI-optimized output files
    r"test_remove\.c",     # intentionally-broken test file
    r"test\.c",            # one-off scratch file
    r"test_pass\.c",       # trivial pass/fail test
    r"ai_test_.*\.c",      # AI test files not part of the benchmark corpus
]

_EXCLUDE_RE = [re.compile(p) for p in _EXCLUDE_PATTERNS]


def _should_exclude(filename: str) -> tuple[bool, Optional[str]]:
    """Return (excluded, reason_or_None)."""
    for pat in _EXCLUDE_RE:
        if pat.fullmatch(filename):
            return True, f"Excluded by pattern {pat.pattern!r}"
    return False, None


def _sha256_file(path: str) -> str:
    """Compute SHA-256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _program_id_from_filename(filename: str) -> str:
    """
    Derive a stable program_id from a .c filename.
    Examples:
      "01_hello_world.c" -> "01_hello_world"
      "TC1_loop_heavy.c" -> "TC1_loop_heavy"
    """
    return os.path.splitext(filename)[0]


def _sort_key(entry: CorpusEntry) -> tuple:
    """
    Sort key for deterministic ordering.
    Existing programs are sorted by origin ("existing" < "generated") then
    by program_id (numeric-prefix-aware).
    """
    origin_rank = 0 if entry.origin == "existing" else 1
    pid = entry.program_id
    # Extract leading numeric prefix for natural sorting
    m = re.match(r"^(\d+)", pid)
    num_prefix = int(m.group(1)) if m else 99999
    return (origin_rank, num_prefix, pid)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_corpus_manifest(
    test_cases_dir: str,
    generated_entries: Optional[list[CorpusEntry]] = None,
) -> list[CorpusEntry]:
    """
    Build a deterministically-ordered list of CorpusEntry objects.

    Parameters
    ----------
    test_cases_dir    : absolute path to Codes/test_cases/ directory
    generated_entries : optional list of CorpusEntry with origin="generated"
                        produced by the benchmark generator

    Returns
    -------
    Deterministically-ordered list of CorpusEntry objects.
    Ordering: existing programs first (by natural numeric sort), then
    generated programs (by program_id).
    The list is stable across calls given the same inputs.
    """
    entries: list[CorpusEntry] = []

    if os.path.isdir(test_cases_dir):
        filenames = sorted(
            f for f in os.listdir(test_cases_dir) if f.endswith(".c")
        )
        for fn in filenames:
            src_path = os.path.abspath(os.path.join(test_cases_dir, fn))
            excluded, reason = _should_exclude(fn)
            pid = _program_id_from_filename(fn)
            try:
                sha = _sha256_file(src_path) if not excluded else ""
            except OSError:
                sha = ""
                excluded = True
                reason = "Cannot read source file"

            entries.append(CorpusEntry(
                program_id=pid,
                source_path=src_path,
                source_sha256=sha,
                origin="existing",
                family=None,
                generator_seed=None,
                generator_index=None,
                excluded=excluded,
                exclusion_reason=reason,
            ))

    if generated_entries:
        # Ensure no ID collision with existing programs
        existing_ids = {e.program_id for e in entries}
        for ge in generated_entries:
            if ge.program_id in existing_ids:
                ge.excluded = True
                ge.exclusion_reason = (
                    f"ID collision with existing program: {ge.program_id!r}"
                )
            entries.append(ge)

    # Deterministic ordering
    entries.sort(key=_sort_key)
    return entries


def save_corpus_manifest(entries: list[CorpusEntry], output_path: str) -> None:
    """Write corpus manifest to a JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    data = {
        "schema_version": "week9.1.0",
        "n_total": len(entries),
        "n_excluded": sum(1 for e in entries if e.excluded),
        "n_active": sum(1 for e in entries if not e.excluded),
        "entries": [e.to_dict() for e in entries],
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def load_corpus_manifest(json_path: str) -> list[CorpusEntry]:
    """Load a corpus manifest written by save_corpus_manifest()."""
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [CorpusEntry.from_dict(e) for e in data.get("entries", [])]
