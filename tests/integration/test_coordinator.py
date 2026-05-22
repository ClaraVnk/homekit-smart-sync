"""Coordinator + sync + restore integration tests.

We patch ``hass.config_entries.async_reload`` since no real HomeKit integration
is loaded — Smart Sync's job is to write the right options into the bridge's
ConfigEntry, and reload is the bridge integration's responsibility.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_smart_sync.const import (
    CONF_BRIDGE_ENTRY_IDS,
    CONF_ENABLE_FILTER,
    CONF_ENABLE_NAMING,
    CONF_ORIGINAL_OPTIONS_SNAPSHOT,
    DOMAIN,
)


async def _setup_smart_sync(
    hass: HomeAssistant,
    bridge: MockConfigEntry,
    *,
    enable_naming: bool = True,
    enable_filter: bool = True,
) -> MockConfigEntry:
    """Install Smart Sync with the given bridge selected. Returns its entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="HomeKit Smart Sync",
        data={},
        options={
            CONF_BRIDGE_ENTRY_IDS: [bridge.entry_id],
            CONF_ENABLE_NAMING: enable_naming,
            CONF_ENABLE_FILTER: enable_filter,
        },
    )
    entry.add_to_hass(hass)
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def _run_sync(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Trigger the coordinator's sync directly, bypassing the 8 s debounce."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()


# ---------------------------------------------------------------- naming sync


async def test_sync_writes_clean_name_overrides(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """Entities whose friendly_name starts with their area name get a clean alias."""
    entry = await _setup_smart_sync(hass, homekit_bridge)
    await _run_sync(hass, entry)

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    entity_config = bridge.options.get("entity_config", {})

    ceiling = populated_registries["entities"]["ceiling"]
    lamp = populated_registries["entities"]["lamp"]
    spot = populated_registries["entities"]["spot"]

    assert entity_config[ceiling]["name"] == "Ceiling Light"
    assert entity_config[lamp]["name"] == "Floor Lamp"
    assert entity_config[spot]["name"] == "Spotlight"


async def test_sync_skips_name_when_disabled(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """With enable_naming=False, no name overrides are pushed."""
    entry = await _setup_smart_sync(hass, homekit_bridge, enable_naming=False)
    await _run_sync(hass, entry)

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    entity_config = bridge.options.get("entity_config", {})
    for cfg in entity_config.values():
        assert "name" not in cfg


# ---------------------------------------------------------------- filter sync


async def test_sync_excludes_noise_sensors(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """The power sensor should land in filter.exclude_entities."""
    entry = await _setup_smart_sync(hass, homekit_bridge)
    await _run_sync(hass, entry)

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    excluded = bridge.options["filter"]["exclude_entities"]

    power_id = populated_registries["entities"]["power"]
    assert power_id in excluded


async def test_sync_links_battery_sensor(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """A battery sensor with a single voice-actionable sibling on the same device
    is re-attached via linked_battery_sensor instead of being silently dropped."""
    entry = await _setup_smart_sync(hass, homekit_bridge)
    await _run_sync(hass, entry)

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    entity_config = bridge.options.get("entity_config", {})

    lock_id = populated_registries["entities"]["lock"]
    battery_id = populated_registries["entities"]["battery"]

    assert entity_config[lock_id]["linked_battery_sensor"] == battery_id


async def test_sync_links_humidity_and_temperature_to_climate(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """A thermostat with sibling humidity + temperature sensors should get
    both ``linked_humidity_sensor`` and ``linked_temperature_sensor`` set."""
    entry = await _setup_smart_sync(hass, homekit_bridge)
    await _run_sync(hass, entry)

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    entity_config = bridge.options.get("entity_config", {})

    hvac_id = populated_registries["entities"]["hvac"]
    humidity_id = populated_registries["entities"]["hvac_humidity"]
    temp_id = populated_registries["entities"]["hvac_temp"]

    assert entity_config[hvac_id]["linked_humidity_sensor"] == humidity_id
    assert entity_config[hvac_id]["linked_temperature_sensor"] == temp_id


# --------------------------------------------------------- idempotency / diff


async def test_second_sync_is_a_noop_when_state_unchanged(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """A re-sync without registry changes must not call update_entry or reload —
    that's what keeps the registry-event → reload loop closed."""
    entry = await _setup_smart_sync(hass, homekit_bridge)
    await _run_sync(hass, entry)

    coordinator = hass.data[DOMAIN][entry.entry_id]
    with (
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ) as reload,
        patch.object(
            hass.config_entries,
            "async_update_entry",
            wraps=hass.config_entries.async_update_entry,
        ) as update,
    ):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()

    reload.assert_not_called()
    # We may still update our own entry to refresh the snapshot block, but
    # we must never touch the bridge entry when nothing changed.
    bridge_updates = [
        call for call in update.call_args_list if call.args[0].entry_id == homekit_bridge.entry_id
    ]
    assert bridge_updates == []


# ----------------------------------------------------------- snapshot/restore


async def test_snapshot_captured_on_first_sync(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """First sync persists the bridge's original options under our own
    entry — that's what lets us restore on uninstall."""
    entry = await _setup_smart_sync(hass, homekit_bridge)
    await _run_sync(hass, entry)

    smart_sync = hass.config_entries.async_get_entry(entry.entry_id)
    snapshots = smart_sync.options.get(CONF_ORIGINAL_OPTIONS_SNAPSHOT, {})
    assert homekit_bridge.entry_id in snapshots
    # Bridge started with no options, so the snapshot is an empty dict.
    assert snapshots[homekit_bridge.entry_id] == {}


async def test_unload_restores_original_options(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
) -> None:
    """Unloading Smart Sync reverts the bridge's options to their pre-sync state."""
    # Give the bridge a pre-existing manual override so we have something to restore.
    hass.config_entries.async_update_entry(
        homekit_bridge,
        options={"entity_config": {"light.user_set": {"name": "User Choice"}}},
    )

    entry = await _setup_smart_sync(hass, homekit_bridge)
    await _run_sync(hass, entry)

    # After sync, the bridge has our overlays merged on top of the user's manual override.
    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    assert "light.user_set" in bridge.options["entity_config"]
    assert len(bridge.options["entity_config"]) > 1

    # Unload — bridge must return to exactly the user's original.
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    assert bridge.options == {"entity_config": {"light.user_set": {"name": "User Choice"}}}


async def test_unload_handles_malformed_snapshot(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    populated_registries: dict,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A corrupted snapshot store must log a warning and abort gracefully — never
    crash hass.config_entries.async_update_entry with a non-dict payload."""
    entry = await _setup_smart_sync(hass, homekit_bridge)
    # Inject a malformed snapshot.
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_ORIGINAL_OPTIONS_SNAPSHOT: "definitely_not_a_dict",
        },
    )
    await hass.async_block_till_done()

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert any("Snapshot store is malformed" in record.message for record in caplog.records)
