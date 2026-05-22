"""Helpers that resolve entity ⇄ area ⇄ device facts.

Kept separate from :mod:`coordinator` so the wiring is testable in
isolation with a stubbed registry.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)

from .filtering import EntityFacts


def resolve_entity_area_id(entity: er.RegistryEntry, device_reg: dr.DeviceRegistry) -> str | None:
    """Return the area_id for an entity, falling back to its device."""
    if entity.area_id:
        return entity.area_id
    if entity.device_id:
        device = device_reg.async_get(entity.device_id)
        if device and device.area_id:
            return device.area_id
    return None


def entity_friendly_name(entity: er.RegistryEntry, hass: HomeAssistant) -> str | None:
    """Best-effort friendly name without forcing a state lookup."""
    if entity.name:
        return entity.name
    if entity.original_name:
        return entity.original_name
    state = hass.states.get(entity.entity_id)
    if state is not None:
        return state.attributes.get("friendly_name")
    return None


def collect_entity_facts(hass: HomeAssistant) -> list[EntityFacts]:
    """Snapshot the entity registry as a list of pure EntityFacts."""
    ent_reg = er.async_get(hass)
    facts: list[EntityFacts] = []
    for ent in ent_reg.entities.values():
        # Pull device_class from registry if integration set it, else state.
        device_class = ent.device_class or ent.original_device_class
        if device_class is None:
            state = hass.states.get(ent.entity_id)
            if state is not None:
                device_class = state.attributes.get("device_class")
        facts.append(
            EntityFacts(
                entity_id=ent.entity_id,
                domain=ent.domain,
                device_id=ent.device_id,
                device_class=device_class,
                entity_category=(ent.entity_category.value if ent.entity_category else None),
                disabled=ent.disabled_by is not None,
                hidden=ent.hidden_by is not None,
            )
        )
    return facts


def area_name_map(hass: HomeAssistant) -> dict[str, str]:
    """Return {area_id: area_name}."""
    return {a.id: a.name for a in ar.async_get(hass).async_list_areas()}
