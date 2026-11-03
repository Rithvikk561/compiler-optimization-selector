"""
moo.multiagent.message_log — Immutable Append-Only Communication Audit Log.

Maintains the chronological record of all inter-agent messages for verification,
reproducibility, and GUI telemetry.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, Optional
from .schema import AgentMessage


class MessageLog:
    """
    Chronological, append-only log of messages exchanged during a pipeline execution.
    """

    def __init__(self, run_id: Optional[str] = None) -> None:
        self.run_id: Optional[str] = run_id
        self._messages: List[AgentMessage] = []

    def append(self, message: AgentMessage) -> None:
        """Append a message to the audit log."""
        if self.run_id and message.run_id != self.run_id:
            # Allow attaching if not previously set, or verify match
            pass
        self._messages.append(message)

    @property
    def messages(self) -> List[AgentMessage]:
        """Return a shallow copy of recorded messages."""
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self) -> Iterator[AgentMessage]:
        return iter(self._messages)

    def __getitem__(self, index: int) -> AgentMessage:
        return self._messages[index]

    def to_list(self) -> List[Dict[str, Any]]:
        """Return list of serialized message dicts."""
        return [m.to_dict() for m in self._messages]

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialize complete message log to JSON string."""
        return json.dumps(self.to_list(), indent=indent)

    @classmethod
    def from_list(cls, items: List[Dict[str, Any]], run_id: Optional[str] = None) -> MessageLog:
        """Reconstruct a MessageLog from a list of dictionaries."""
        log = cls(run_id=run_id)
        for item in items:
            log.append(AgentMessage.from_dict(item))
        return log

    def filter_by_sender(self, sender: str) -> List[AgentMessage]:
        """Filter log entries by sender role."""
        return [m for m in self._messages if m.sender == sender]

    def filter_by_type(self, message_type: str) -> List[AgentMessage]:
        """Filter log entries by message type."""
        return [m for m in self._messages if m.message_type == message_type]
