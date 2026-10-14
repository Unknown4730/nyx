"""Readable text for enum values that appear in prose, reports and assumptions.

Machine values (``steady_crud``, ``object_storage``) stay as they are in the JSON contract;
this module only changes how they read to a person.
"""

from __future__ import annotations

# Words that read better in upper case when they come from an enum value (steady_crud -> steady CRUD).
_ACRONYMS = {
    "api": "API", "crud": "CRUD", "db": "DB", "ai": "AI", "gpu": "GPU", "sla": "SLA",
    "tls": "TLS", "pdf": "PDF", "kv": "KV", "ttl": "TTL", "rpm": "RPM",
}

# Values that mean "nothing was established from the input".
_NOT_STATED = {"", "unknown", "none", "not_stated"}


def readable(value: object) -> str:
    """Make an enum value readable: object_storage -> object storage, steady_crud -> steady CRUD.

    Accepts plain strings or enum members. Values meaning "nothing was established" read as
    "not stated" rather than "unknown".
    """
    raw = getattr(value, "value", value)
    text = str(raw).strip()
    if text in _NOT_STATED:
        return "not stated"
    return " ".join(_ACRONYMS.get(word, word) for word in text.replace("-", "_").split("_") if word)


def traffic_pattern_phrase(pattern: object) -> str:
    """Phrase used inside assumption sentences, e.g. 'a steady pattern' or 'an unstated traffic pattern'."""
    text = readable(pattern)
    if text == "not stated":
        return "an unstated traffic pattern"
    return f"{text} pattern"
