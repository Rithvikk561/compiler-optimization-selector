"""
moo.agentic_security.input_screen — L1 Input Security Screening.

Includes:
- Unicode NFKC normalization
- Zero-width character removal
- Lowercasing and whitespace collapsing
- Maximum length 4096 truncation
- Clause-anchored attack pattern detection
- Question and negation guards (e.g. "Explain why...", "Never disable...")
- C source comment extraction
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from typing import Optional

from ..secevent.risk import Signal, compute_risk_assessment, assess_decision
from ..secevent.schema import AttackType, ActionAttempted, ActionTaken, RiskLevel

ZERO_WIDTH_CHARS = re.compile(r"[\u200B\u200C\u200D\uFEFF\u00AD\u2060]")
WHITESPACE_COLLAPSE = re.compile(r"\s+")
C_LINE_COMMENT = re.compile(r"//(.*)$", re.MULTILINE)
C_BLOCK_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)

MAX_INPUT_LENGTH = 4096


def normalize_text(text: str) -> str:
    """
    Deterministically normalize input text:
    - Unicode NFKC decomposition
    - Remove zero-width formatting characters
    - Lowercase
    - Collapse repeated whitespace
    - Bounded to MAX_INPUT_LENGTH
    """
    if not text:
        return ""
    # Truncate first to prevent memory exhaustion
    s = text[:MAX_INPUT_LENGTH]
    s = unicodedata.normalize("NFKC", s)
    s = ZERO_WIDTH_CHARS.sub("", s)
    s = s.lower()
    s = WHITESPACE_COLLAPSE.sub(" ", s).strip()
    return s


def extract_c_comments(c_source_code: str) -> list[str]:
    """Extract all single-line and multi-line comments from C source code."""
    if not c_source_code:
        return []
    comments: list[str] = []
    for m in C_LINE_COMMENT.finditer(c_source_code):
        clean = m.group(1).strip()
        if clean:
            comments.append(clean)
    for m in C_BLOCK_COMMENT.finditer(c_source_code):
        clean = m.group(1).strip()
        if clean:
            comments.append(clean)
    return comments


# Clause-anchored detection definitions:
# (rule_id, family, severity, confidence, pattern, attack_type, action_attempted)
INPUT_RULES = [
    # 1. Prompt Injection / Persona override
    (
        "L1_PI_01",
        "prompt_injection",
        9,
        0.95,
        re.compile(r"(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|prompts|guidelines)", re.IGNORECASE),
        AttackType.PROMPT_INJECTION,
        ActionAttempted.INSTRUCTION_INJECTION,
    ),
    (
        "L1_PI_02",
        "prompt_injection",
        9,
        0.95,
        re.compile(r"(?:you\s+are\s+now|act\s+as)\s+(?:in\s+)?(?:unrestricted|jailbreak|developer|dan|god)\s+mode", re.IGNORECASE),
        AttackType.PROMPT_INJECTION,
        ActionAttempted.INSTRUCTION_INJECTION,
    ),
    (
        "L1_PI_03",
        "prompt_injection",
        8,
        0.90,
        re.compile(r"ai-assistant:\s*ignore\s+previous\s+instructions", re.IGNORECASE),
        AttackType.PROMPT_INJECTION,
        ActionAttempted.INSTRUCTION_INJECTION,
    ),

    # 2. Policy Bypass
    (
        "L1_PB_01",
        "policy_bypass",
        9,
        0.95,
        re.compile(r"(?:ignore|override|bypass|disable)\s+(?:the\s+)?(?:security\s+)?policy", re.IGNORECASE),
        AttackType.POLICY_BYPASS,
        ActionAttempted.OVERRIDE_POLICY,
    ),

    # 3. Validation Disable
    (
        "L1_VD_01",
        "validation_disable",
        9,
        0.95,
        re.compile(r"(?:disable|skip|bypass|turn\s+off)\s+(?:the\s+)?(?:correctness\s+)?validation(?:\s+step)?", re.IGNORECASE),
        AttackType.VALIDATION_DISABLE,
        ActionAttempted.DISABLE_VALIDATION,
    ),

    # 4. Verdict Manipulation
    (
        "L1_VM_01",
        "verdict_manipulation",
        9,
        0.95,
        re.compile(r"mark\s+(?:the\s+)?vulnerable\s+code\s+as\s+safe", re.IGNORECASE),
        AttackType.VERDICT_MANIPULATION,
        ActionAttempted.MARK_SAFE,
    ),
    (
        "L1_VM_02",
        "verdict_manipulation",
        8,
        0.90,
        re.compile(r"report\s+(?:the\s+)?verdict\s+as\s+preserved", re.IGNORECASE),
        AttackType.VERDICT_MANIPULATION,
        ActionAttempted.MARK_SAFE,
    ),
    (
        "L1_VM_03",
        "verdict_manipulation",
        8,
        0.90,
        re.compile(r"mark\s+this\s+function\s+as\s+safe", re.IGNORECASE),
        AttackType.VERDICT_MANIPULATION,
        ActionAttempted.MARK_SAFE,
    ),

    # 5. Finding Suppression
    (
        "L1_FS_01",
        "finding_suppression",
        8,
        0.90,
        re.compile(r"(?:ignore|suppress|hide)\s+(?:the\s+)?security\s+findings", re.IGNORECASE),
        AttackType.FINDING_SUPPRESSION,
        ActionAttempted.SUPPRESS_FINDINGS,
    ),
    (
        "L1_FS_02",
        "finding_suppression",
        8,
        0.90,
        re.compile(r"report\s+no\s+hazards", re.IGNORECASE),
        AttackType.FINDING_SUPPRESSION,
        ActionAttempted.SUPPRESS_FINDINGS,
    ),

    # 6. Strategy & Compiler Config Mutation
    (
        "L1_SM_01",
        "strategy_mutation",
        8,
        0.90,
        re.compile(r"(?:switch|change|force)\s+(?:the\s+)?(?:selected\s+)?strategy\s+to\s+-o[0-3]", re.IGNORECASE),
        AttackType.STRATEGY_MUTATION,
        ActionAttempted.MUTATE_STRATEGY,
    ),
    (
        "L1_SM_02",
        "strategy_mutation",
        8,
        0.95,
        re.compile(r"(?:add|use)\s+-fno-stack-protector", re.IGNORECASE),
        AttackType.STRATEGY_MUTATION,
        ActionAttempted.MUTATE_STRATEGY,
    ),

    # 7. Secret Exfiltration
    (
        "L1_SE_01",
        "secret_exfiltration",
        9,
        0.95,
        re.compile(r"(?:print|dump|read|echo|reveal|leak|exfiltrate)\s+(?:the\s+value\s+of\s+)?(?:the\s+)?(?:api_key|secret|token|password|credential|env|environment\s+variables?)", re.IGNORECASE),
        AttackType.SECRET_EXFILTRATION,
        ActionAttempted.READ_SECRET,
    ),

    # 8. Sensitive File Access
    (
        "L1_FA_01",
        "sensitive_file_access",
        9,
        0.95,
        re.compile(r"(?:read|cat|open|dump)\s+(?:/etc/passwd|~/\.ssh|id_rsa|\.aws/credentials)", re.IGNORECASE),
        AttackType.SENSITIVE_FILE_ACCESS,
        ActionAttempted.READ_SENSITIVE_FILE,
    ),

    # 9. Network Exfiltration
    (
        "L1_NE_01",
        "network_exfiltration",
        9,
        0.95,
        re.compile(r"(?:upload|send|post|transmit)\s+(?:the\s+)?(?:.*?)to\s+https?://", re.IGNORECASE),
        AttackType.NETWORK_EXFILTRATION,
        ActionAttempted.NETWORK_CALL,
    ),

    # 10. Command Execution
    (
        "L1_CE_01",
        "command_execution",
        9,
        0.95,
        re.compile(r"(?:run|execute)\s+(?:a\s+)?(?:shell|bash|cmd|powershell)?\s*command(?:\s+to)?", re.IGNORECASE),
        AttackType.COMMAND_EXECUTION,
        ActionAttempted.EXEC_COMMAND,
    ),

    # 11. Log & Policy Tampering
    (
        "L1_LT_01",
        "log_tampering",
        9,
        0.95,
        re.compile(r"(?:delete|clear|erase|truncate)\s+(?:the\s+)?(?:security\s+)?(?:event\s+)?log", re.IGNORECASE),
        AttackType.LOG_TAMPERING,
        ActionAttempted.CLEAR_LOG,
    ),
    (
        "L1_LT_02",
        "policy_bypass",
        9,
        0.95,
        re.compile(r"(?:edit|modify|rewrite)\s+(?:the\s+)?policy(?:\s+file)?\s+to\s+allow", re.IGNORECASE),
        AttackType.POLICY_BYPASS,
        ActionAttempted.OVERRIDE_POLICY,
    ),
]

# Question / Negation guards: benign educational or inquisitive contexts
QUESTION_GUARDS = [
    re.compile(r"^(?:explain|why|how|what|describe|is\s+there)\b", re.IGNORECASE),
    re.compile(r"\?\s*$", re.IGNORECASE),
    re.compile(r"^how\s+does\s+the\s+policy\b", re.IGNORECASE),
]

NEGATION_GUARDS = [
    re.compile(r"\bnever\s+(?:disable|ignore|bypass|skip)\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+(?:disable|ignore|bypass|skip)\b", re.IGNORECASE),
    re.compile(r"\bmust\s+not\s+(?:disable|ignore|bypass|skip)\b", re.IGNORECASE),
]


@dataclasses.dataclass(frozen=True)
class InputScreenResult:
    is_attack: bool
    risk_level: RiskLevel
    score: int
    confidence: float
    attack_types: list[AttackType]
    signals: list[Signal]
    action_attempted: ActionAttempted
    action_taken: ActionTaken
    blocked: bool
    reason: str


def screen_input_text(raw_text: str) -> InputScreenResult:
    """
    Screen text input through L1 normalization, question/negation guards, and pattern matchers.
    """
    norm = normalize_text(raw_text)
    if not norm:
        return InputScreenResult(
            is_attack=False,
            risk_level=RiskLevel.NONE,
            score=0,
            confidence=0.0,
            attack_types=[],
            signals=[],
            action_attempted=ActionAttempted.UNKNOWN_ACTION,
            action_taken=ActionTaken.ALLOW,
            blocked=False,
            reason="Empty input text",
        )

    # Check question / negation guards for benign text
    is_negated = any(g.search(norm) for g in NEGATION_GUARDS)
    is_question = any(g.search(norm) for g in QUESTION_GUARDS)

    # If it is an explicit negated benign prompt ("never disable the validation step"):
    if is_negated:
        return InputScreenResult(
            is_attack=False,
            risk_level=RiskLevel.NONE,
            score=0,
            confidence=0.90,
            attack_types=[],
            signals=[],
            action_attempted=ActionAttempted.UNKNOWN_ACTION,
            action_taken=ActionTaken.ALLOW,
            blocked=False,
            reason="Benign negated security policy directive",
        )

    # If it is an explanatory question ("Explain why validation matters"):
    if is_question and not ("ignore previous" in norm or "unrestricted mode" in norm):
        return InputScreenResult(
            is_attack=False,
            risk_level=RiskLevel.NONE,
            score=0,
            confidence=0.90,
            attack_types=[],
            signals=[],
            action_attempted=ActionAttempted.UNKNOWN_ACTION,
            action_taken=ActionTaken.ALLOW,
            blocked=False,
            reason="Benign educational or explanatory query",
        )

    matched_signals: list[Signal] = []
    matched_attacks: list[AttackType] = []
    primary_action = ActionAttempted.UNKNOWN_ACTION

    for rule_id, family, sev, conf, regex, atk_type, act_att in INPUT_RULES:
        m = regex.search(norm)
        if m:
            matched_signals.append(
                Signal(
                    rule_id=rule_id,
                    family=family,
                    severity=sev,
                    rule_confidence=conf,
                    evidence=m.group(0),
                )
            )
            if atk_type not in matched_attacks:
                matched_attacks.append(atk_type)
            if primary_action == ActionAttempted.UNKNOWN_ACTION:
                primary_action = act_att

    if not matched_signals:
        return InputScreenResult(
            is_attack=False,
            risk_level=RiskLevel.NONE,
            score=0,
            confidence=0.0,
            attack_types=[],
            signals=[],
            action_attempted=ActionAttempted.UNKNOWN_ACTION,
            action_taken=ActionTaken.ALLOW,
            blocked=False,
            reason="No suspicious patterns detected",
        )

    # Assess risk
    risk = compute_risk_assessment(matched_signals, has_forbidden_capability=True)
    decision, blocked = assess_decision(risk, is_hard_rule_violation=True if risk.score >= 60 else False)

    return InputScreenResult(
        is_attack=True,
        risk_level=risk.risk_level,
        score=risk.score,
        confidence=risk.confidence,
        attack_types=matched_attacks,
        signals=matched_signals,
        action_attempted=primary_action,
        action_taken=decision,
        blocked=blocked,
        reason=f"Detected {len(matched_signals)} security signal(s): {', '.join(a.value for a in matched_attacks)}",
    )
