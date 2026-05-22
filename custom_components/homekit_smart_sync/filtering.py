"""Smart Filter for voice — pure functions, no Home Assistant imports.

Produces the ``filter`` and partial ``entity_config`` dicts consumed by
the ``homekit`` integration. Inputs are plain data (dicts, dataclasses
of primitive fields) so the module is trivially unit-testable.

Linked-sensor awareness: rather than dropping helper sensors outright,
we attempt to attach each one to its host device's primary entity via
the HomeKit ``linked_*_sensor`` keys. That preserves Apple Home's
richer accessory tiles — e.g. "Low Battery" notifications on locks
and humidity/temperature graphs on thermostats — which would otherwise
disappear if we filtered the sensors away blindly.
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


@dataclass(frozen=True, slots=True)
class _LinkRule:
    """Recipe for attaching one class of helper sensor to its host.

    Kept private — the public API is :func:`compute_linked_sensors`.
    Adding a new linked-sensor type is a one-line tuple entry below; the
    coordinator and entity_config merge logic are rule-agnostic.
    """

    sensor_device_class: str
    host_domains: frozenset[str]
    config_key: str


# Order is not significant — each rule applies independently. Battery
# stays first only for readability (it's the most universally useful).
_LINK_RULES: tuple[_LinkRule, ...] = (
    _LinkRule("battery", VOICE_ACTIONABLE_DOMAINS, "linked_battery_sensor"),
    _LinkRule(
        "humidity",
        frozenset({"climate", "humidifier"}),
        "linked_humidity_sensor",
    ),
    # Linking an external temperature sensor to a climate entity overrides
    # the value Apple Home displays. Worthwhile when the user has a
    # dedicated room sensor more accurate than the thermostat's own probe.
    _LinkRule("temperature", frozenset({"climate"}), "linked_temperature_sensor"),
)


@dataclass(frozen=True, slots=True)
class AmbiguousLink:
    """A link case the auto-resolver refused to commit to.

    Currently only the "one sensor, many host candidates" shape is reported —
    that's by far the most common in the wild (a battery sensor on a device
    that exposes both a lock and a switch entity, for example). The reverse
    case ("many sensors, one host") is less common and left to a future
    Repairs flow extension.
    """

    device_id: str
    config_key: str  # e.g. "linked_battery_sensor"
    sensor_class: str  # e.g. "battery" — used as a stable issue-id slug
    sensor_entity_id: str
    host_candidates: tuple[str, ...]


def compute_linked_sensors(
    entities: Iterable[EntityFacts],
    *,
    manual_links: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    """Return host_entity_id → {linked_*_sensor: sensor_entity_id} mappings.

    Each rule in :data:`_LINK_RULES` is applied independently, so a
    thermostat with both a humidity and a temperature sensor on the same
    device gets both linked. The same conservative invariant applies as
    before: a link is only added when the device has exactly one sensor
    of the relevant class and exactly one eligible host — under-link
    rather than mis-link.

    ``manual_links`` (``{device_id: {config_key: host_entity_id}}``) lets
    the caller resolve previously ambiguous cases — typically populated
    from the Repairs flow. Manual entries take precedence over auto
    detection and are honored even when the auto rule would have skipped.
    """
    entities = list(entities)
    manual_links = manual_links or {}
    result: dict[str, dict[str, str]] = {}

    for rule in _LINK_RULES:
        by_device_sensors: dict[str, list[str]] = {}
        by_device_hosts: dict[str, list[str]] = {}

        for ent in entities:
            if ent.disabled or ent.hidden or not ent.device_id:
                continue
            if ent.domain == "sensor" and ent.device_class == rule.sensor_device_class:
                by_device_sensors.setdefault(ent.device_id, []).append(ent.entity_id)
            elif ent.domain in rule.host_domains:
                by_device_hosts.setdefault(ent.device_id, []).append(ent.entity_id)

        for device_id, sensors in by_device_sensors.items():
            hosts = by_device_hosts.get(device_id, [])
            manual_host = manual_links.get(device_id, {}).get(rule.config_key)

            if manual_host and manual_host in hosts and len(sensors) == 1:
                result.setdefault(manual_host, {})[rule.config_key] = sensors[0]
            elif len(sensors) == 1 and len(hosts) == 1:
                result.setdefault(hosts[0], {})[rule.config_key] = sensors[0]

    return result


def compute_link_ambiguities(
    entities: Iterable[EntityFacts],
    *,
    manual_links: dict[str, dict[str, str]] | None = None,
) -> list[AmbiguousLink]:
    """Detect (device, rule) combos where exactly one sensor exists but
    multiple hosts qualify — the case a Repairs flow should ask about.

    Already-resolved ambiguities (the user picked a host via the flow and
    that host still exists) are not reported again. If the manual choice
    references a host that has since disappeared, the ambiguity resurfaces.
    """
    entities = list(entities)
    manual_links = manual_links or {}
    ambiguities: list[AmbiguousLink] = []

    for rule in _LINK_RULES:
        by_device_sensors: dict[str, list[str]] = {}
        by_device_hosts: dict[str, list[str]] = {}

        for ent in entities:
            if ent.disabled or ent.hidden or not ent.device_id:
                continue
            if ent.domain == "sensor" and ent.device_class == rule.sensor_device_class:
                by_device_sensors.setdefault(ent.device_id, []).append(ent.entity_id)
            elif ent.domain in rule.host_domains:
                by_device_hosts.setdefault(ent.device_id, []).append(ent.entity_id)

        for device_id, sensors in by_device_sensors.items():
            hosts = by_device_hosts.get(device_id, [])
            if len(sensors) != 1 or len(hosts) < 2:
                continue
            manual_host = manual_links.get(device_id, {}).get(rule.config_key)
            if manual_host and manual_host in hosts:
                continue  # user already resolved this case
            ambiguities.append(
                AmbiguousLink(
                    device_id=device_id,
                    config_key=rule.config_key,
                    sensor_class=rule.sensor_device_class,
                    sensor_entity_id=sensors[0],
                    host_candidates=tuple(sorted(hosts)),
                )
            )

    return ambiguities


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
