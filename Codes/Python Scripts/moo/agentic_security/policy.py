"""
moo.agentic_security.policy — Default-deny ActionCategory authorization policy (L2).
"""

from __future__ import annotations

from typing import Tuple

from .schema import ActionCategory

ALLOWED_ACTIONS: frozenset[ActionCategory] = frozenset({
    ActionCategory.READ_EVIDENCE,
    ActionCategory.EMIT_FINDING,
    ActionCategory.EMIT_ADVISORY_ALTERNATIVE,
    ActionCategory.REQUEST_EXPLANATION,
})

FORBIDDEN_ACTIONS: frozenset[ActionCategory] = frozenset({
    ActionCategory.MODIFY_STRATEGY,
    ActionCategory.MODIFY_COMPILER_CONFIG,
    ActionCategory.DISABLE_VALIDATION,
    ActionCategory.SET_SECURITY_VERDICT,
    ActionCategory.SUPPRESS_FINDING,
    ActionCategory.WRITE_FILE,
    ActionCategory.READ_FILE_OUTSIDE_SCOPE,
    ActionCategory.READ_ENV_SECRET,
    ActionCategory.ACCESS_PII,
    ActionCategory.NETWORK_ACCESS,
    ActionCategory.EXEC_COMMAND,
    ActionCategory.MODIFY_POLICY,
    ActionCategory.CLEAR_LOG,
})


def check_action_allowed(action: ActionCategory | str) -> Tuple[bool, str]:
    """
    Enforce default-deny action category check.
    Returns (is_allowed, reason).
    """
    if isinstance(action, str):
        try:
            action = ActionCategory(action)
        except ValueError:
            return False, f"Unknown action category: {action!r} (default-deny blocked)"

    if action in ALLOWED_ACTIONS:
        return True, f"Action {action.value} is permitted under advisory-only policy"

    if action in FORBIDDEN_ACTIONS:
        return False, f"Action {action.value} violates advisory-only boundary and is strictly forbidden"

    return False, f"Action {action} is not in the allowed policy whitelist (default-deny blocked)"
