"""Config flow integration tests."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_smart_sync.const import (
    CONF_BRIDGE_ENTRY_IDS,
    CONF_ENABLE_FILTER,
    CONF_ENABLE_NAMING,
    DOMAIN,
    HOMEKIT_DOMAIN,
)


@pytest.mark.asyncio
async def test_aborts_when_no_homekit_bridge(hass: HomeAssistant) -> None:
    """No bridge configured → flow aborts before showing a form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "no_homekit_bridges"


@pytest.mark.asyncio
async def test_aborts_for_accessory_mode_only(hass: HomeAssistant) -> None:
    """Accessory-mode bridges are filtered out; if those are the only entries,
    the flow aborts the same way."""
    MockConfigEntry(
        domain=HOMEKIT_DOMAIN,
        data={"mode": "accessory", "port": 21064},
        title="Single Accessory",
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "no_homekit_bridges"


@pytest.mark.asyncio
async def test_happy_path(hass: HomeAssistant, homekit_bridge: MockConfigEntry) -> None:
    """Bridge selected → entry created with the chosen options."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            CONF_BRIDGE_ENTRY_IDS: [homekit_bridge.entry_id],
            CONF_ENABLE_NAMING: True,
            CONF_ENABLE_FILTER: True,
        },
    )
    assert result["type"] == "create_entry"
    assert result["options"][CONF_BRIDGE_ENTRY_IDS] == [homekit_bridge.entry_id]
    assert result["options"][CONF_ENABLE_NAMING] is True
    assert result["options"][CONF_ENABLE_FILTER] is True


@pytest.mark.asyncio
async def test_singleton(hass: HomeAssistant, homekit_bridge: MockConfigEntry) -> None:
    """A second instance is refused — two coordinators would race on the same
    bridge options."""
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_error_when_no_bridge_selected(
    hass: HomeAssistant, homekit_bridge: MockConfigEntry
) -> None:
    """Submitting with an empty bridge selection re-shows the form with an error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_BRIDGE_ENTRY_IDS: []},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "no_bridge_selected"}
