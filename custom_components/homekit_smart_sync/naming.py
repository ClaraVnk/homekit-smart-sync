"""Siri Name Cleaner — pure functions, no Home Assistant imports.

The single public entry point is :func:`clean_entity_name`. It strips an
entity's area name from its friendly name when the area appears as a
prefix or suffix (case-insensitive, accent-insensitive), so Siri does
not have to disambiguate "Living Room Ceiling Light in the Living Room".

Design rules:
- Idempotent: ``clean(clean(x)) == clean(x)``. Required to break the
  registry-event → sync → reload → ??? loop.
- Never returns an empty string. Falls back to the original name.
- Never mutates the entity registry. The cleaned form is an alias only.
"""

from __future__ import annotations

import unicodedata


def clean_entity_name(friendly_name: str | None, area_name: str | None) -> str | None:
    """Return a cleaned alias suitable for HomeKit, or ``None`` to keep default.

    ``None`` means "do not override" — the HomeKit bridge will use the
    entity's own friendly name. We return ``None`` whenever cleaning
    would be a no-op, so we don't bloat ``entity_config`` with identity
    overrides (which also makes diffing cheaper in the coordinator).
    """
    if not friendly_name or not area_name:
        return None

    name_tokens = friendly_name.split()
    area_tokens = area_name.split()
    if not name_tokens or not area_tokens:
        return None

    # Refuse to reduce the name to nothing (or to a single token equal
    # to the area). "Kitchen" in area "Kitchen" stays "Kitchen".
    if len(name_tokens) <= len(area_tokens):
        return None

    norm_area = [_normalize(t) for t in area_tokens]
    norm_name = [_normalize(t) for t in name_tokens]
    n = len(area_tokens)

    if norm_name[:n] == norm_area:
        cleaned_tokens = name_tokens[n:]
    elif norm_name[-n:] == norm_area:
        cleaned_tokens = name_tokens[:-n]
    else:
        return None

    cleaned = " ".join(cleaned_tokens).strip(" -_")
    if not cleaned or cleaned == friendly_name:
        return None
    return cleaned


def _normalize(token: str) -> str:
    """Lowercase + strip accents for comparison only."""
    nfd = unicodedata.normalize("NFD", token)
    stripped = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    return stripped.casefold()
