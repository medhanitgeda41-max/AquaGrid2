"""Pure Python deterministic regex prompt-injection filter.

Enforces Layer 0 defense: all incoming text alerts, field crew messages,
and external inputs are scanned and neutralized before any LLM ever sees them.
"""
import re

# Comprehensive compiled regex patterns targeting known prompt-injection vectors
INJECTION_PATTERNS = [
    re.compile(r"system\s+override", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+|previous\s+|prior\s+|safety\s+|system\s+)*(instructions|rules|constraints|prompts?|safeguards?|floors?)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+|an?\s+|operating\s+as\s+)*(unrestricted|admin|god|root|jailbreak)", re.IGNORECASE),
    re.compile(r"(admin|root|developer|maintenance|god)\s+mode", re.IGNORECASE),
    re.compile(r"bypass\s+(gateway|safety|checks?|authorization|approval)", re.IGNORECASE),
    re.compile(r"(drop|delete|truncate|alter)\s+(table|database|from)\b", re.IGNORECASE),
    re.compile(r"<\s*script\b", re.IGNORECASE),
    re.compile(r"\{\{.*?\}\}", re.IGNORECASE),  # Template injection attempts
]


def detect_injection(text: str) -> tuple[bool, list[str]]:
    """
    Scan input text against deterministic regex injection patterns.
    
    Returns:
        (is_injection: bool, matched_patterns: list[str])
    """
    if not text or not isinstance(text, str):
        return False, []

    matches = []
    for pattern in INJECTION_PATTERNS:
        found = pattern.findall(text)
        if found:
            matches.append(pattern.pattern)

    return len(matches) > 0, matches


# Replacement placeholder when an entire alert is quarantined
QUARANTINED_ALERT_PLACEHOLDER = "[QUARANTINED ALERT: content withheld - injection detected]"


def sanitize_text(text: str) -> tuple[bool, str]:
    """
    Sanitize text input by detecting prompt injection attempts and quarantining
    the ENTIRE alert text so no part of a malicious instruction reaches the LLM.

    Returns:
        (is_injection: bool, sanitized_text: str)
    """
    if not text or not isinstance(text, str):
        return False, ""

    is_inj, _ = detect_injection(text)
    if not is_inj:
        return False, text.strip()

    # Quarantine the entire alert text — withhold all original content
    return True, QUARANTINED_ALERT_PLACEHOLDER
