"""
moo/adaptive/storage.py — Week 11: Experience storage and replay buffer.

Provides:
  ExperienceStore
      Persistent, versioned, corruption-safe, duplicate-aware storage
      for ExperienceRecord objects.  Each record is stored as a single
      JSON line in an append-only JSONL file (one record per line).

  ReplayBuffer
      In-memory bounded buffer supporting random sampling for learning.
      Deterministic when a seed is supplied.

Design rules
------------
* Append-only on-disk format (JSONL) — no silent overwrites.
* Duplicate detection by experience_id.
* Atomic write: new records are appended and fsynced before confirmation.
* Corruption-safe read: each line is parsed independently; corrupt lines
  are counted and reported but do NOT abort the load.
* Bounded capacity: ReplayBuffer discards oldest entries when full.
* No fabricated experiences.
* No benchmark system: the store only reads/writes ExperienceRecord objects.
* Deterministic sampling: seeded RNG produces reproducible samples.
"""

from __future__ import annotations

import json
import math
import os
import random
from typing import Optional

from .schema import (
    ADAPTIVE_SCHEMA_VERSION,
    ExperienceRecord,
    make_timestamp,
)
from .validator import validate_experience


# ---------------------------------------------------------------------------
# Manifest — tracks store metadata alongside the JSONL data file
# ---------------------------------------------------------------------------

_MANIFEST_FILENAME = "experience_store_manifest.json"
_EXPERIENCE_FILENAME = "experiences.jsonl"
_STORE_SCHEMA_VERSION = "week11.1.0"


class _StoreManifest:
    """Lightweight manifest for ExperienceStore metadata."""

    __slots__ = (
        "schema_version", "created_at", "last_updated_at",
        "record_count", "corrupt_lines", "store_dir",
    )

    def __init__(
        self,
        *,
        schema_version: str = _STORE_SCHEMA_VERSION,
        created_at: str = "",
        last_updated_at: str = "",
        record_count: int = 0,
        corrupt_lines: int = 0,
        store_dir: str = "",
    ) -> None:
        self.schema_version = schema_version
        self.created_at = created_at
        self.last_updated_at = last_updated_at
        self.record_count = record_count
        self.corrupt_lines = corrupt_lines
        self.store_dir = store_dir

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "record_count": self.record_count,
            "corrupt_lines": self.corrupt_lines,
        }

    @classmethod
    def from_dict(cls, d: dict, store_dir: str = "") -> "_StoreManifest":
        return cls(
            schema_version=str(d.get("schema_version", _STORE_SCHEMA_VERSION)),
            created_at=str(d.get("created_at", "")),
            last_updated_at=str(d.get("last_updated_at", "")),
            record_count=int(d.get("record_count", 0)),
            corrupt_lines=int(d.get("corrupt_lines", 0)),
            store_dir=store_dir,
        )


# ---------------------------------------------------------------------------
# ExperienceStore
# ---------------------------------------------------------------------------

class ExperienceStore:
    """
    Persistent, append-only experience store backed by a JSONL file.

    Parameters
    ----------
    store_dir
        Directory where the JSONL data file and manifest are kept.
        Created if it does not exist.

    Public methods
    --------------
    add(experience)         → bool
        Validate and append one ExperienceRecord.  Returns True if accepted,
        False if rejected (duplicate or invalid).

    add_batch(experiences)  → tuple[int, int]
        Add a list of records.  Returns (n_accepted, n_rejected).

    load_all()              → list[ExperienceRecord]
        Load and return all valid records from disk.
        Corrupt/invalid lines are counted in manifest.corrupt_lines.

    record_count            property → int
        Number of valid records currently on disk (from manifest).

    exists(experience_id)   → bool
        True if experience_id is already stored (duplicate check).

    manifest_path / data_path  properties
    """

    def __init__(self, store_dir: str) -> None:
        self._store_dir = os.path.abspath(store_dir)
        os.makedirs(self._store_dir, exist_ok=True)
        self._data_path = os.path.join(self._store_dir, _EXPERIENCE_FILENAME)
        self._manifest_path = os.path.join(self._store_dir, _MANIFEST_FILENAME)
        self._manifest = self._load_or_create_manifest()
        # In-memory index of known experience_ids for duplicate detection.
        # Populated lazily on first duplicate check.
        self._id_index: Optional[set[str]] = None

    # ----------------------------------------------------------------
    # Properties
    # ----------------------------------------------------------------

    @property
    def store_dir(self) -> str:
        return self._store_dir

    @property
    def manifest_path(self) -> str:
        return self._manifest_path

    @property
    def data_path(self) -> str:
        return self._data_path

    @property
    def record_count(self) -> int:
        return self._manifest.record_count

    @property
    def corrupt_line_count(self) -> int:
        return self._manifest.corrupt_lines

    # ----------------------------------------------------------------
    # Public: add
    # ----------------------------------------------------------------

    def add(self, experience: ExperienceRecord) -> bool:
        """
        Validate and append one ExperienceRecord.

        Returns True if the record was accepted and written, False if:
          - validation failed
          - it is a duplicate (same experience_id already stored)
        """
        # 1. Validate
        result = validate_experience(experience)
        if not result:
            return False

        # 2. Duplicate check
        if self.exists(experience.experience_id):
            return False

        # 3. Serialize
        try:
            line = json.dumps(experience.to_dict(), separators=(",", ":")) + "\n"
        except Exception:
            return False

        # 4. Atomic append + fsync
        try:
            with open(self._data_path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            return False

        # 5. Update in-memory index
        if self._id_index is not None:
            self._id_index.add(experience.experience_id)

        # 6. Update manifest
        self._manifest.record_count += 1
        self._manifest.last_updated_at = make_timestamp()
        self._save_manifest()

        return True

    def add_batch(
        self,
        experiences: list[ExperienceRecord],
    ) -> tuple[int, int]:
        """
        Add multiple experiences.

        Returns (n_accepted, n_rejected).
        """
        accepted = 0
        rejected = 0
        for exp in experiences:
            if self.add(exp):
                accepted += 1
            else:
                rejected += 1
        return accepted, rejected

    # ----------------------------------------------------------------
    # Public: load
    # ----------------------------------------------------------------

    def load_all(self) -> list[ExperienceRecord]:
        """
        Load all valid records from the JSONL file.

        Corrupt or invalid lines are skipped and counted.
        Returns an empty list if the file does not exist yet.
        """
        if not os.path.isfile(self._data_path):
            return []

        records: list[ExperienceRecord] = []
        corrupt = 0
        id_set: set[str] = set()

        try:
            with open(self._data_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        exp = ExperienceRecord.from_dict(d)
                        # Deduplicate in-memory
                        if exp.experience_id in id_set:
                            continue
                        id_set.add(exp.experience_id)
                        records.append(exp)
                    except Exception:
                        corrupt += 1
        except OSError:
            return []

        # Update manifest if corruption count changed
        if corrupt != self._manifest.corrupt_lines:
            self._manifest.corrupt_lines = corrupt
            self._save_manifest()

        # Refresh in-memory index
        self._id_index = id_set

        return records

    # ----------------------------------------------------------------
    # Public: exists (duplicate check)
    # ----------------------------------------------------------------

    def exists(self, experience_id: str) -> bool:
        """Return True if experience_id is already stored."""
        if self._id_index is None:
            self._build_id_index()
        return experience_id in (self._id_index or set())

    # ----------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------

    def _build_id_index(self) -> None:
        """Populate _id_index by scanning the JSONL file."""
        if not os.path.isfile(self._data_path):
            self._id_index = set()
            return
        ids: set[str] = set()
        try:
            with open(self._data_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        eid = d.get("experience_id", "")
                        if eid:
                            ids.add(str(eid))
                    except Exception:
                        pass
        except OSError:
            pass
        self._id_index = ids

    def _load_or_create_manifest(self) -> _StoreManifest:
        if os.path.isfile(self._manifest_path):
            try:
                with open(self._manifest_path, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                return _StoreManifest.from_dict(d, store_dir=self._store_dir)
            except Exception:
                pass
        # Create fresh manifest
        now = make_timestamp()
        m = _StoreManifest(
            created_at=now,
            last_updated_at=now,
            store_dir=self._store_dir,
        )
        self._save_manifest(m)
        return m

    def _save_manifest(self, manifest: Optional[_StoreManifest] = None) -> None:
        m = manifest or self._manifest
        try:
            with open(self._manifest_path, "w", encoding="utf-8") as fh:
                json.dump(m.to_dict(), fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass


# ---------------------------------------------------------------------------
# ReplayBuffer
# ---------------------------------------------------------------------------

class ReplayBuffer:
    """
    In-memory bounded experience replay buffer.

    Supports deterministic random sampling when a seed is supplied.

    Parameters
    ----------
    capacity
        Maximum number of experiences to hold.  When full, the oldest
        entry (FIFO) is discarded before adding a new one.

    seed
        Optional random seed for deterministic sampling.
        If None, sampling is non-deterministic.

    Public methods
    --------------
    push(experience)        Add one experience.  Oldest discarded when full.
    sample(n, seed)         Return a random sample of up to n experiences.
    sample_all()            Return all experiences (shallow copy).
    __len__()               Number of stored experiences.
    is_full                 True when at capacity.
    clear()                 Empty the buffer.
    """

    def __init__(self, capacity: int = 10_000, seed: Optional[int] = None) -> None:
        if capacity < 1:
            raise ValueError(f"ReplayBuffer capacity must be >= 1; got {capacity}")
        self._capacity = capacity
        self._buffer: list[ExperienceRecord] = []
        self._rng = random.Random(seed)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def is_full(self) -> bool:
        return len(self._buffer) >= self._capacity

    def __len__(self) -> int:
        return len(self._buffer)

    def push(self, experience: ExperienceRecord) -> None:
        """
        Add one experience.  If at capacity, discard the oldest entry first.
        No validation is performed here — assume caller has validated.
        """
        if len(self._buffer) >= self._capacity:
            self._buffer.pop(0)  # FIFO eviction
        self._buffer.append(experience)

    def push_batch(self, experiences: list[ExperienceRecord]) -> None:
        """Add multiple experiences."""
        for exp in experiences:
            self.push(exp)

    def sample(
        self,
        n: int,
        seed: Optional[int] = None,
    ) -> list[ExperienceRecord]:
        """
        Return a random sample of up to n experiences (without replacement).

        Parameters
        ----------
        n    : number of experiences to sample
        seed : if provided, overrides the buffer's RNG seed for this call only,
               making this specific sample reproducible regardless of prior calls.
               If None, uses the buffer's existing RNG state.

        Returns an empty list if the buffer is empty.
        """
        if not self._buffer:
            return []
        n = min(n, len(self._buffer))
        if n <= 0:
            return []
        if seed is not None:
            rng = random.Random(seed)
        else:
            rng = self._rng
        return rng.sample(self._buffer, n)

    def sample_all(self) -> list[ExperienceRecord]:
        """Return a shallow copy of all experiences."""
        return list(self._buffer)

    def clear(self) -> None:
        """Empty the buffer."""
        self._buffer.clear()

    def load_from_store(
        self,
        store: "ExperienceStore",
        *,
        max_records: Optional[int] = None,
    ) -> int:
        """
        Load experiences from an ExperienceStore into this buffer.

        If max_records is specified, only the most recent records are loaded
        (up to min(max_records, capacity)).

        Returns the number of records loaded.
        """
        all_records = store.load_all()
        if max_records is not None and max_records > 0:
            all_records = all_records[-max_records:]
        self.clear()
        for exp in all_records:
            self.push(exp)
        return len(self._buffer)
