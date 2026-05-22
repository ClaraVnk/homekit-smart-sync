"""Services for managing per-entity alias overrides.

We expose two services rather than a UI editor:

- ``homekit_smart_sync.set_alias`` — set or update an alias for one entity.
- ``homekit_smart_sync.clear_alias`` — remove a previously set alias so the
  auto-cleaned name resumes.

This approach lets users script overrides from automations (e.g. "rename
this device based on its room template") and keeps the options flow free
of the dynamic key/value editor a UI implementation would require.
"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ALIAS,
    ATTR_TERM,
    ATTR_TRANSLATION,
    DOMAIN,
    SERVICE_CLEAR_ALIAS,
    SERVICE_CLEAR_TRANSLATION,
    SERVICE_SET_ALIAS,
    SERVICE_SET_TRANSLATION,
)

_LOGGER = logging.getLogger(__name__)

SET_ALIAS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): cv.entity_id,
        vol.Required(ATTR_ALIAS): vol.All(cv.string, vol.Length(min=1, max=64)),
    }
)

CLEAR_ALIAS_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})

SET_TRANSLATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TERM): vol.All(cv.string, vol.Length(min=1, max=64)),
        vol.Required(ATTR_TRANSLATION): vol.All(cv.string, vol.Length(min=1, max=64)),
    }
)

CLEAR_TRANSLATION_SCHEMA = vol.Schema(
    {vol.Required(ATTR_TERM): vol.All(cv.string, vol.Length(min=1, max=64))}
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register set_alias / clear_alias. Safe to call multiple times."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_ALIAS):
        return

    async def _set_alias(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("Cannot set alias: HomeKit Smart Sync is not configured yet")
            return
        coordinator.record_manual_name(
            entity_id=call.data[ATTR_ENTITY_ID],
            alias=call.data[ATTR_ALIAS],
        )

    async def _clear_alias(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass)
        if coordinator is None:
            return
        coordinator.clear_manual_name(call.data[ATTR_ENTITY_ID])

    async def _set_translation(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass)
        if coordinator is None:
            _LOGGER.warning("Cannot set translation: HomeKit Smart Sync is not configured yet")
            return
        coordinator.record_term_translation(
            term=call.data[ATTR_TERM],
            translation=call.data[ATTR_TRANSLATION],
        )

    async def _clear_translation(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass)
        if coordinator is None:
            return
        coordinator.clear_term_translation(call.data[ATTR_TERM])

    hass.services.async_register(DOMAIN, SERVICE_SET_ALIAS, _set_alias, schema=SET_ALIAS_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_ALIAS, _clear_alias, schema=CLEAR_ALIAS_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TRANSLATION,
        _set_translation,
        schema=SET_TRANSLATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CLEAR_TRANSLATION,
        _clear_translation,
        schema=CLEAR_TRANSLATION_SCHEMA,
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the services. Called from async_unload_entry."""
    for service in (
        SERVICE_SET_ALIAS,
        SERVICE_CLEAR_ALIAS,
        SERVICE_SET_TRANSLATION,
        SERVICE_CLEAR_TRANSLATION,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)


def _resolve_coordinator(hass: HomeAssistant):
    """Return the (singleton) coordinator instance, or None if not set up."""
    bucket = hass.data.get(DOMAIN, {})
    for coordinator in bucket.values():
        return coordinator
    return None
