"""Integration tests for the set_alias / clear_alias services."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_smart_sync.const import (
    ATTR_ALIAS,
    CONF_BRIDGE_ENTRY_IDS,
    CONF_MANUAL_NAMES,
    DOMAIN,
    SERVICE_CLEAR_ALIAS,
    SERVICE_SET_ALIAS,
)


async def _setup(hass: HomeAssistant, bridge: MockConfigEntry) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="HomeKit Smart Sync",
        options={CONF_BRIDGE_ENTRY_IDS: [bridge.entry_id]},
    )
    entry.add_to_hass(hass)
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_services_registered_on_setup(
    hass: HomeAssistant, homekit_bridge: MockConfigEntry
) -> None:
    await _setup(hass, homekit_bridge)
    assert hass.services.has_service(DOMAIN, SERVICE_SET_ALIAS)
    assert hass.services.has_service(DOMAIN, SERVICE_CLEAR_ALIAS)


async def test_set_alias_persists_and_overrides_auto_naming(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    entry = await _setup(hass, homekit_bridge)
    ceiling_id = populated_registries["entities"]["ceiling"]

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_ALIAS,
        {ATTR_ENTITY_ID: ceiling_id, ATTR_ALIAS: "Lustre"},
        blocking=True,
    )
    await hass.async_block_till_done()

    # Persisted under our options.
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert entry.options[CONF_MANUAL_NAMES][ceiling_id] == "Lustre"

    # And honored by the next sync — overrides the auto-cleaned "Ceiling Light".
    coordinator = hass.data[DOMAIN][entry.entry_id]
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    assert bridge.options["entity_config"][ceiling_id]["name"] == "Lustre"


async def test_clear_alias_restores_auto_naming(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    entry = await _setup(hass, homekit_bridge)
    ceiling_id = populated_registries["entities"]["ceiling"]

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_ALIAS,
        {ATTR_ENTITY_ID: ceiling_id, ATTR_ALIAS: "Lustre"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEAR_ALIAS,
        {ATTR_ENTITY_ID: ceiling_id},
        blocking=True,
    )
    await hass.async_block_till_done()

    entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert ceiling_id not in entry.options.get(CONF_MANUAL_NAMES, {})

    coordinator = hass.data[DOMAIN][entry.entry_id]
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    # Auto-cleaner resumes.
    assert bridge.options["entity_config"][ceiling_id]["name"] == "Ceiling Light"


async def test_services_unregistered_on_unload(
    hass: HomeAssistant, homekit_bridge: MockConfigEntry
) -> None:
    entry = await _setup(hass, homekit_bridge)
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, SERVICE_SET_ALIAS)
    assert not hass.services.has_service(DOMAIN, SERVICE_CLEAR_ALIAS)
