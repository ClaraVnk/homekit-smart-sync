"""Integration test fixtures.

Uses a real Home Assistant runtime via ``pytest-homeassistant-custom-component``.
Unlike the unit tests in ``tests/`` (which use an importlib shim to avoid
loading HA at all), this directory exercises the full registry → coordinator →
bridge options pipeline.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homekit_smart_sync.const import HOMEKIT_DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> Generator[None, None, None]:
    """Allow Home Assistant to discover our custom_components package."""
    yield


@pytest.fixture
def homekit_bridge(hass: HomeAssistant) -> MockConfigEntry:
    """A loaded HomeKit bridge config entry, ready to be steered by Smart Sync.

    We do not actually start the HAP bridge — Smart Sync only needs the
    ConfigEntry to exist so it can patch its ``options`` and (in real life)
    trigger a reload. Tests patch ``async_reload`` where relevant.
    """
    entry = MockConfigEntry(
        domain=HOMEKIT_DOMAIN,
        data={"mode": "bridge", "name": "Test Bridge", "port": 21063},
        title="Test Bridge",
        options={},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def populated_registries(hass: HomeAssistant, homekit_bridge: MockConfigEntry):
    """Create a small but realistic registry topology.

    - One "Living Room" area, one "Bathroom" area.
    - A ceiling light + a floor lamp in Living Room, a spotlight in Bathroom.
    - A door lock with a battery sensor (eligible for linked_battery_sensor).
    - A power sensor that should be filtered out.

    Returns a dict so tests can grab whichever ids they need.
    """
    area_reg = ar.async_get(hass)
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    living_room = area_reg.async_create("Living Room")
    bathroom = area_reg.async_create("Bathroom")

    def _mk_device(identifier: str, area_id: str) -> str:
        device = dev_reg.async_get_or_create(
            config_entry_id=homekit_bridge.entry_id,
            identifiers={("test", identifier)},
        )
        dev_reg.async_update_device(device.id, area_id=area_id)
        return device.id

    light_dev = _mk_device("light_device", living_room.id)
    lamp_dev = _mk_device("lamp_device", living_room.id)
    spot_dev = _mk_device("spot_device", bathroom.id)
    lock_dev = _mk_device("lock_device", living_room.id)
    power_dev = _mk_device("power_device", living_room.id)

    ceiling = ent_reg.async_get_or_create(
        "light",
        "test",
        "ceiling",
        suggested_object_id="living_room_ceiling",
        original_name="Living Room Ceiling Light",
        device_id=light_dev,
    )
    lamp = ent_reg.async_get_or_create(
        "light",
        "test",
        "lamp",
        suggested_object_id="living_room_lamp",
        original_name="Living Room Floor Lamp",
        device_id=lamp_dev,
    )
    spot = ent_reg.async_get_or_create(
        "light",
        "test",
        "spot",
        suggested_object_id="bathroom_spot",
        original_name="Bathroom Spotlight",
        device_id=spot_dev,
    )
    lock = ent_reg.async_get_or_create(
        "lock",
        "test",
        "front_door",
        suggested_object_id="front_door",
        original_name="Front Door",
        device_id=lock_dev,
    )
    battery = ent_reg.async_get_or_create(
        "sensor",
        "test",
        "lock_battery",
        suggested_object_id="front_door_battery",
        original_name="Front Door Battery",
        device_id=lock_dev,
        original_device_class="battery",
    )
    power = ent_reg.async_get_or_create(
        "sensor",
        "test",
        "power",
        suggested_object_id="living_room_power",
        original_name="Living Room Power",
        device_id=power_dev,
        original_device_class="power",
    )

    return {
        "areas": {"living_room": living_room.id, "bathroom": bathroom.id},
        "entities": {
            "ceiling": ceiling.entity_id,
            "lamp": lamp.entity_id,
            "spot": spot.entity_id,
            "lock": lock.entity_id,
            "battery": battery.entity_id,
            "power": power.entity_id,
        },
    }
