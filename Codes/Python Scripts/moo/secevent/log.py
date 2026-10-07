"""
moo.secevent.log — In-Memory and JSONL Resilient Security Event Log.

Invariants:
- Events are always stored in-memory in strict deterministic sequence order.
- Optional JSONL file persistence.
- Persistence failure NEVER loses the in-memory event and NEVER raises an exception.
- Exposes `persist_ok` flag indicating persistence status.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterator, Optional

from .schema import SecurityEvent


class SecurityEventLog:
    """
    Append-only security event log with in-memory retention and optional JSONL file output.
    """

    def __init__(self, log_path: Optional[str] = None) -> None:
        self._log_path = log_path
        self._events: list[SecurityEvent] = []
        self._next_sequence: int = 1
        self._persist_ok: bool = True

    @property
    def persist_ok(self) -> bool:
        """True if all persistence writes have succeeded, False if any failed."""
        return self._persist_ok

    @property
    def next_sequence(self) -> int:
        """Current sequence number for the next event."""
        return self._next_sequence

    def append(self, event: SecurityEvent) -> SecurityEvent:
        """
        Record a SecurityEvent in memory and attempt optional JSONL persistence.
        Never raises on persistence error (fails closed to in-memory).
        """
        self._events.append(event)
        self._next_sequence = max(self._next_sequence, event.sequence + 1)

        if self._log_path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self._log_path)), exist_ok=True)
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict()) + "\n")
            except Exception:
                # Security events must never silently disappear from memory,
                # but log persistence failure must never crash the pipeline.
                self._persist_ok = False

        return event

    def get_events(self) -> list[SecurityEvent]:
        """Return a copy of all recorded security events in sequence order."""
        return list(self._events)

    def count(self) -> int:
        return len(self._events)

    def count_blocked(self) -> int:
        return sum(1 for e in self._events if e.blocked)

    def clear(self) -> None:
        """Clear the in-memory log (for testing only)."""
        self._events.clear()
        self._next_sequence = 1
        self._persist_ok = True

    def __iter__(self) -> Iterator[SecurityEvent]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)
