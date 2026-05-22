"""Integration tests for the Repairs flow (ambiguous sensor links)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    issue_registry as ir,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_smart_sync.const import (
    CONF_BRIDGE_ENTRY_IDS,
    CONF_ENABLE_FILTER,
    CONF_ENABLE_NAMING,
    CONF_MANUAL_LINKS,
    DOMAIN,
)
from custom_components.homekit_smart_sync.repairs import async_create_fix_flow


@pytest.fixture
def ambiguous_topology(hass: HomeAssistant, homekit_bridge: MockConfigEntry) -> dict:
    """A device exposing both a lock and a switch with a shared battery sensor.

    This is the canonical ambiguous case: compute_linked_sensors refuses to
    pick a host, the Repairs flow should surface a fixable issue.
    """
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    device = dev_reg.async_get_or_create(
        config_entry_id=homekit_bridge.entry_id,
        identifiers={("test", "ambig_device")},
    )
    lock = ent_reg.async_get_or_create(
        "lock", "test", "ambig_lock", suggested_object_id="ambig_lock", device_id=device.id
    )
    switch = ent_reg.async_get_or_create(
        "switch",
        "test",
        "ambig_switch",
        suggested_object_id="ambig_switch",
        device_id=device.id,
    )
    battery = ent_reg.async_get_or_create(
        "sensor",
        "test",
        "ambig_battery",
        suggested_object_id="ambig_battery",
        device_id=device.id,
        original_device_class="battery",
    )
    return {
        "device_id": device.id,
        "lock_id": lock.entity_id,
        "switch_id": switch.entity_id,
        "battery_id": battery.entity_id,
    }


async def _setup(hass: HomeAssistant, bridge: MockConfigEntry) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        title="HomeKit Smart Sync",
        data={},
        options={
            CONF_BRIDGE_ENTRY_IDS: [bridge.entry_id],
            CONF_ENABLE_NAMING: True,
            CONF_ENABLE_FILTER: True,
        },
    )
    entry.add_to_hass(hass)
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _expected_issue_id(device_id: str) -> str:
    return f"ambiguous_link::battery::{device_id}"


async def test_ambiguous_link_raises_issue(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    ambiguous_topology: dict,
) -> None:
    entry = await _setup(hass, homekit_bridge)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, _expected_issue_id(ambiguous_topology["device_id"])
    )
    assert issue is not None
    assert issue.is_fixable is True
    assert ambiguous_topology["lock_id"] in issue.data["host_candidates"]
    assert ambiguous_topology["switch_id"] in issue.data["host_candidates"]
    assert issue.data["sensor_entity_id"] == ambiguous_topology["battery_id"]


async def test_repair_flow_persists_choice_and_clears_issue(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    ambiguous_topology: dict,
) -> None:
    entry = await _setup(hass, homekit_bridge)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()

    issue_id = _expected_issue_id(ambiguous_topology["device_id"])
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None

    # Drive the fix flow as if the user picked the lock as the host.
    flow = await async_create_fix_flow(hass, issue_id, dict(issue.data))
    flow.hass = hass
    result = await flow.async_step_init()
    assert result["type"] == "form"
    assert result["step_id"] == "pick_host"

    result = await flow.async_step_pick_host({"host": ambiguous_topology["lock_id"]})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    # Choice persisted in our options.
    entry = hass.config_entries.async_get_entry(entry.entry_id)
    manual = entry.options.get(CONF_MANUAL_LINKS, {})
    assert (
        manual[ambiguous_topology["device_id"]]["linked_battery_sensor"]
        == ambiguous_topology["lock_id"]
    )

    # Next sync honors the choice → the issue is gone and the battery is now
    # linked to the chosen host in the bridge's entity_config.
    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    bridge = hass.config_entries.async_get_entry(homekit_bridge.entry_id)
    entity_config = bridge.options["entity_config"]
    assert (
        entity_config[ambiguous_topology["lock_id"]]["linked_battery_sensor"]
        == ambiguous_topology["battery_id"]
    )


async def test_unload_clears_open_issues(
    hass: HomeAssistant,
    homekit_bridge: MockConfigEntry,
    ambiguous_topology: dict,
) -> None:
    entry = await _setup(hass, homekit_bridge)
    coordinator = hass.data[DOMAIN][entry.entry_id]

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        await coordinator._async_perform_sync()
        await hass.async_block_till_done()

    issue_id = _expected_issue_id(ambiguous_topology["device_id"])
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock(return_value=True)):
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
