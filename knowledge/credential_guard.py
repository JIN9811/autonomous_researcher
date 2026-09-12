"""Bounded credential admission; pattern detection is not exhaustive DLP."""
import re

# Same common token/private-key families as the publication guard, plus explicit
# credential assignments. Never return the matching value to a caller.
_TOKEN = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
_ASSIGNMENT = re.compile(r'(?i)\b(?:api[ _-]?key|password|access[ _-]?token|secret[ _-]?key)\s*(?:is\s+|[:=]\s*)\S+')


def admit_credential_free_text(value: str, *, limit: int = 16_000) -> None:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError('Content exceeds the bounded admission limit.')
    if _TOKEN.search(value) or _ASSIGNMENT.search(value):
        raise ValueError('Credential-like content is not accepted for memory or model transmission. Remove credentials and retry.')
