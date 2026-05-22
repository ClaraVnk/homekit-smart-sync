"""Smart Filter for voice — pure functions, no Home Assistant imports.

Produces the ``filter`` and partial ``entity_config`` dicts consumed by
the ``homekit`` integration. Inputs are plain data (dicts, dataclasses
of primitive fields) so the module is trivially unit-testable.

Linked-battery awareness: rather than dropping every ``device_class=battery``
sensor outright, we attempt to attach it to its host device's primary
voice-actionable entity via ``linked_battery_sensor``. That preserves the
"Low battery" notification in Apple Home — a real regression if we just
filtered the sensor out blindly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .const import (
    CONDITIONAL_DOMAINS,
    EXCLUDED_ENTITY_CATEGORIES,
    EXCLUDED_SENSOR_DEVICE_CLASSES,
    KEEP_SENSOR_DEVICE_CLASSES,
    VOICE_ACTIONABLE_DOMAINS,
)


@dataclass(frozen=True, slots=True)
class EntityFacts:
    """Plain-data view of an entity, decoupled from HA's RegistryEntry."""

    entity_id: str
    domain: str
    device_id: str | None
    device_class: str | None
    entity_category: str | None  # "diagnostic" | "config" | None
    disabled: bool
    hidden: bool


def compute_filter(
    entities: Iterable[EntityFacts],
    *,
    extra_excluded_domains: Iterable[str] = (),
) -> dict:
    """Return the ``filter`` dict expected by the homekit integration."""
    extra_excluded = set(extra_excluded_domains)
    exclude_entities: list[str] = []

    for ent in entities:
        if ent.disabled or ent.hidden:
            continue  # already hidden — no need to list explicitly
        if not _should_expose(ent, extra_excluded):
            exclude_entities.append(ent.entity_id)

    include_domains = sorted(VOICE_ACTIONABLE_DOMAINS | CONDITIONAL_DOMAINS)
    include_domains = [d for d in include_domains if d not in extra_excluded]

    return {
        "include_domains": include_domains,
        "include_entities": [],
        "exclude_domains": sorted(extra_excluded),
        "exclude_entities": sorted(set(exclude_entities)),
    }


def compute_linked_batteries(
    entities: Iterable[EntityFacts],
) -> dict[str, str]:
    """Map host entity_id → battery sensor entity_id, one per device.

    Only assigns a linked battery when a device has exactly one
    voice-actionable host. Ambiguous devices are left untouched — we'd
    rather under-link than mis-link.
    """
    entities = list(entities)

    by_device_battery: dict[str, list[str]] = {}
    by_device_hosts: dict[str, list[str]] = {}

    for ent in entities:
        if ent.disabled or ent.hidden or not ent.device_id:
            continue
        if ent.domain == "sensor" and ent.device_class == "battery":
            by_device_battery.setdefault(ent.device_id, []).append(ent.entity_id)
        elif ent.domain in VOICE_ACTIONABLE_DOMAINS:
            by_device_hosts.setdefault(ent.device_id, []).append(ent.entity_id)

    linked: dict[str, str] = {}
    for device_id, batteries in by_device_battery.items():
        hosts = by_device_hosts.get(device_id, [])
        if len(batteries) == 1 and len(hosts) == 1:
            linked[hosts[0]] = batteries[0]
    return linked


def _should_expose(ent: EntityFacts, extra_excluded_domains: set[str]) -> bool:
    if ent.domain in extra_excluded_domains:
        return False
    if ent.entity_category in EXCLUDED_ENTITY_CATEGORIES:
        return False
    if ent.domain in VOICE_ACTIONABLE_DOMAINS:
        return True
    if ent.domain == "sensor":
        if ent.device_class in EXCLUDED_SENSOR_DEVICE_CLASSES:
            return False
        return ent.device_class in KEEP_SENSOR_DEVICE_CLASSES
    if ent.domain == "binary_sensor":
        # Conservative default: only motion/occupancy/door-style classes
        # are useful in Home. The Watts-style noise lives on regular sensors.
        return ent.device_class in {
            "motion",
            "occupancy",
            "door",
            "window",
            "garage_door",
            "smoke",
            "moisture",
            "leak",
            "gas",
            "co",
            "presence",
        }
    return False
