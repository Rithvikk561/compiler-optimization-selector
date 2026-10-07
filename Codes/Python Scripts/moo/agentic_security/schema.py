"""
moo.agentic_security.schema — Data models for Agentic AI security layer.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
import hashlib
from typing import Any, Optional


class SimulatedChannel(str, Enum):
    USER_INSTRUCTION = "USER_INSTRUCTION"
    SOURCE_COMMENT = "SOURCE_COMMENT"
    FILENAME = "FILENAME"
    TOOL_OUTPUT = "TOOL_OUTPUT"
    AGENT_REPORT_TEXT = "AGENT_REPORT_TEXT"


class ActionCategory(str, Enum):
    # Allowed
    READ_EVIDENCE = "READ_EVIDENCE"
    EMIT_FINDING = "EMIT_FINDING"
    EMIT_ADVISORY_ALTERNATIVE = "EMIT_ADVISORY_ALTERNATIVE"
    REQUEST_EXPLANATION = "REQUEST_EXPLANATION"

    # Forbidden
    MODIFY_STRATEGY = "MODIFY_STRATEGY"
    MODIFY_COMPILER_CONFIG = "MODIFY_COMPILER_CONFIG"
    DISABLE_VALIDATION = "DISABLE_VALIDATION"
    SET_SECURITY_VERDICT = "SET_SECURITY_VERDICT"
    SUPPRESS_FINDING = "SUPPRESS_FINDING"
    WRITE_FILE = "WRITE_FILE"
    READ_FILE_OUTSIDE_SCOPE = "READ_FILE_OUTSIDE_SCOPE"
    READ_ENV_SECRET = "READ_ENV_SECRET"
    ACCESS_PII = "ACCESS_PII"
    NETWORK_ACCESS = "NETWORK_ACCESS"
    EXEC_COMMAND = "EXEC_COMMAND"
    MODIFY_POLICY = "MODIFY_POLICY"
    CLEAR_LOG = "CLEAR_LOG"

    # Unknown
    UNKNOWN_CATEGORY = "UNKNOWN_CATEGORY"


class ArtifactKind(str, Enum):
    C_SOURCE = "C_SOURCE"
    LLVM_IR = "LLVM_IR"
    PATCH_TEXT = "PATCH_TEXT"


class ArtifactOrigin(str, Enum):
    SIMULATED_HEALED = "SIMULATED_HEALED"
    PIPELINE_OPTIMIZED = "PIPELINE_OPTIMIZED"


class CapabilityClass(str, Enum):
    EXEC = "exec"
    NETWORK = "network"
    SENSITIVE_FILE = "sensitive_file"
    SECRET_ENV = "secret_env"
    PII = "pii"
    URL_LITERAL = "url_literal"


@dataclasses.dataclass(frozen=True)
class SimulatedAgentRequest:
    """
    Deterministic test-double representation of an untrusted incoming request to the Agentic AI.
    """
    request_id: str
    channel: SimulatedChannel
    text: str
    requested_actions: list[ActionCategory] = dataclasses.field(default_factory=list)
    artifact: Optional[str] = None
    trust: str = "UNTRUSTED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "channel": self.channel.value if isinstance(self.channel, SimulatedChannel) else str(self.channel),
            "text": self.text,
            "requested_actions": [a.value if isinstance(a, ActionCategory) else str(a) for a in self.requested_actions],
            "artifact": self.artifact,
            "trust": self.trust,
        }


@dataclasses.dataclass(frozen=True)
class GeneratedArtifact:
    """
    Representation of simulated healed code or candidate generated artifact.
    """
    artifact_id: str
    kind: ArtifactKind
    text: str
    origin: ArtifactOrigin = ArtifactOrigin.SIMULATED_HEALED
    parent_source_hash: Optional[str] = None

    @classmethod
    def from_text(
        cls,
        artifact_id: str,
        kind: ArtifactKind,
        text: str,
        origin: ArtifactOrigin = ArtifactOrigin.SIMULATED_HEALED,
        parent_source_hash: Optional[str] = None,
    ) -> "GeneratedArtifact":
        return cls(
            artifact_id=artifact_id,
            kind=kind,
            text=text,
            origin=origin,
            parent_source_hash=parent_source_hash,
        )

    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value if isinstance(self.kind, ArtifactKind) else str(self.kind),
            "text_sha256": self.sha256(),
            "origin": self.origin.value if isinstance(self.origin, ArtifactOrigin) else str(self.origin),
            "parent_source_hash": self.parent_source_hash,
        }
