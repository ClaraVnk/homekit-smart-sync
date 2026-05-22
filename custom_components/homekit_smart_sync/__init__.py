"""HomeKit Smart Sync integration.

This integration does not expose entities of its own. It observes the
area and entity registries and pushes a computed ``entity_config`` /
``filter`` payload into the user-selected ``homekit`` bridge config
entries, then triggers a reload. The official ``homekit`` integration
remains the sole owner of the HAP bridge — we only steer its options.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import SmartSyncCoordinator
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HomeKit Smart Sync from a config entry."""
    coordinator = SmartSyncCoordinator(hass, entry)
    await coordinator.async_initial_setup()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # React to options changes (user toggling features in the UI).
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # React to registry mutations. We schedule a debounced sync rather
    # than computing inline — startup emits dozens of events and reloading
    # the HomeKit bridge per event would thrash the HAP connection.
    entry.async_on_unload(
        hass.bus.async_listen(
            er.EVENT_ENTITY_REGISTRY_UPDATED, coordinator.handle_entity_registry_event
        )
    )
    entry.async_on_unload(
        hass.bus.async_listen(
            ar.EVENT_AREA_REGISTRY_UPDATED, coordinator.handle_area_registry_event
        )
    )

    # Trigger a first sync once HA has finished starting so registries
    # are settled and we don't reload the bridge mid-boot.
    coordinator.schedule_sync(reason="initial")

    # Services are domain-scoped (not per-entry). Since the integration is
    # a singleton, registering here and de-registering when the entry
    # unloads is correct.
    async_register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and restore the HomeKit bridge to its prior state."""
    coordinator: SmartSyncCoordinator | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if coordinator is not None:
        await coordinator.async_restore_and_teardown()

    if not hass.data.get(DOMAIN):
        async_unregister_services(hass)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Re-run the sync when the user changes our options."""
    coordinator: SmartSyncCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return
    coordinator.refresh_options_from_entry()
    coordinator.schedule_sync(reason="options_updated")
