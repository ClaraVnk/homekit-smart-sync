"""Tests for the Smart Filter and linked-sensor resolution."""

from __future__ import annotations

import pytest


def _make_facts(filtering, **overrides):
    """Build an EntityFacts with sensible defaults."""
    defaults = {
        "entity_id": "light.example",
        "domain": "light",
        "device_id": "dev_1",
        "device_class": None,
        "entity_category": None,
        "disabled": False,
        "hidden": False,
    }
    defaults.update(overrides)
    return filtering.EntityFacts(**defaults)


class TestExposureRules:
    def test_voice_actionable_light_is_kept(self, filtering):
        facts = [_make_facts(filtering, entity_id="light.kitchen", domain="light")]
        result = filtering.compute_filter(facts)
        assert "light.kitchen" not in result["exclude_entities"]
        assert "light" in result["include_domains"]

    def test_diagnostic_category_is_excluded(self, filtering):
        facts = [
            _make_facts(
                filtering,
                entity_id="switch.fw_update",
                domain="switch",
                entity_category="diagnostic",
            )
        ]
        result = filtering.compute_filter(facts)
        assert "switch.fw_update" in result["exclude_entities"]

    def test_config_category_is_excluded(self, filtering):
        facts = [
            _make_facts(
                filtering,
                entity_id="switch.led_indicator",
                domain="switch",
                entity_category="config",
            )
        ]
        result = filtering.compute_filter(facts)
        assert "switch.led_indicator" in result["exclude_entities"]

    @pytest.mark.parametrize(
        "device_class",
        ["power", "energy", "voltage", "current", "battery", "signal_strength"],
    )
    def test_noise_sensors_are_excluded(self, filtering, device_class):
        facts = [
            _make_facts(
                filtering,
                entity_id=f"sensor.fridge_{device_class}",
                domain="sensor",
                device_class=device_class,
            )
        ]
        result = filtering.compute_filter(facts)
        assert f"sensor.fridge_{device_class}" in result["exclude_entities"]

    @pytest.mark.parametrize("device_class", ["temperature", "humidity", "co2"])
    def test_useful_sensors_are_kept(self, filtering, device_class):
        facts = [
            _make_facts(
                filtering,
                entity_id=f"sensor.bedroom_{device_class}",
                domain="sensor",
                device_class=device_class,
            )
        ]
        result = filtering.compute_filter(facts)
        assert f"sensor.bedroom_{device_class}" not in result["exclude_entities"]

    def test_binary_motion_sensor_is_kept(self, filtering):
        facts = [
            _make_facts(
                filtering,
                entity_id="binary_sensor.hall_motion",
                domain="binary_sensor",
                device_class="motion",
            )
        ]
        result = filtering.compute_filter(facts)
        assert "binary_sensor.hall_motion" not in result["exclude_entities"]

    def test_binary_sensor_without_device_class_is_excluded(self, filtering):
        facts = [
            _make_facts(
                filtering,
                entity_id="binary_sensor.weird",
                domain="binary_sensor",
                device_class=None,
            )
        ]
        result = filtering.compute_filter(facts)
        assert "binary_sensor.weird" in result["exclude_entities"]

    def test_disabled_entity_is_not_listed(self, filtering):
        # No point excluding what HA already hides.
        facts = [
            _make_facts(
                filtering,
                entity_id="light.unused",
                domain="light",
                disabled=True,
            )
        ]
        result = filtering.compute_filter(facts)
        assert "light.unused" not in result["exclude_entities"]

    def test_extra_excluded_domain_removed_from_includes(self, filtering):
        result = filtering.compute_filter([], extra_excluded_domains=["scene"])
        assert "scene" not in result["include_domains"]
        assert "scene" in result["exclude_domains"]


class TestLinkedBatteries:
    def test_single_battery_single_host_links(self, filtering):
        facts = [
            _make_facts(filtering, entity_id="lock.front", domain="lock", device_id="d1"),
            _make_facts(
                filtering,
                entity_id="sensor.front_battery",
                domain="sensor",
                device_id="d1",
                device_class="battery",
            ),
        ]
        linked = filtering.compute_linked_sensors(facts)
        assert linked == {"lock.front": {"linked_battery_sensor": "sensor.front_battery"}}

    def test_multiple_hosts_no_link(self, filtering):
        # Ambiguous: which entity should "own" the battery indicator?
        # Better to under-link than mis-link.
        facts = [
            _make_facts(filtering, entity_id="lock.front", domain="lock", device_id="d1"),
            _make_facts(filtering, entity_id="switch.front", domain="switch", device_id="d1"),
            _make_facts(
                filtering,
                entity_id="sensor.front_battery",
                domain="sensor",
                device_id="d1",
                device_class="battery",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}

    def test_multiple_batteries_no_link(self, filtering):
        facts = [
            _make_facts(filtering, entity_id="lock.front", domain="lock", device_id="d1"),
            _make_facts(
                filtering,
                entity_id="sensor.battery_a",
                domain="sensor",
                device_id="d1",
                device_class="battery",
            ),
            _make_facts(
                filtering,
                entity_id="sensor.battery_b",
                domain="sensor",
                device_id="d1",
                device_class="battery",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}

    def test_battery_without_host_no_link(self, filtering):
        facts = [
            _make_facts(
                filtering,
                entity_id="sensor.orphan_battery",
                domain="sensor",
                device_id="d1",
                device_class="battery",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}

    def test_battery_without_device_id_no_link(self, filtering):
        # Can't group without a device_id — no way to find the host.
        facts = [
            _make_facts(filtering, entity_id="lock.front", domain="lock", device_id=None),
            _make_facts(
                filtering,
                entity_id="sensor.front_battery",
                domain="sensor",
                device_id=None,
                device_class="battery",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}

    def test_disabled_battery_ignored(self, filtering):
        facts = [
            _make_facts(filtering, entity_id="lock.front", domain="lock", device_id="d1"),
            _make_facts(
                filtering,
                entity_id="sensor.front_battery",
                domain="sensor",
                device_id="d1",
                device_class="battery",
                disabled=True,
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}


class TestLinkedClimateSensors:
    def test_humidity_links_to_climate(self, filtering):
        facts = [
            _make_facts(filtering, entity_id="climate.hvac", domain="climate", device_id="t1"),
            _make_facts(
                filtering,
                entity_id="sensor.hvac_humidity",
                domain="sensor",
                device_id="t1",
                device_class="humidity",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {
            "climate.hvac": {"linked_humidity_sensor": "sensor.hvac_humidity"}
        }

    def test_humidity_links_to_humidifier(self, filtering):
        facts = [
            _make_facts(
                filtering,
                entity_id="humidifier.bedroom",
                domain="humidifier",
                device_id="h1",
            ),
            _make_facts(
                filtering,
                entity_id="sensor.bedroom_humidity",
                domain="sensor",
                device_id="h1",
                device_class="humidity",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {
            "humidifier.bedroom": {"linked_humidity_sensor": "sensor.bedroom_humidity"}
        }

    def test_temperature_links_to_climate(self, filtering):
        facts = [
            _make_facts(filtering, entity_id="climate.hvac", domain="climate", device_id="t1"),
            _make_facts(
                filtering,
                entity_id="sensor.hvac_room_temp",
                domain="sensor",
                device_id="t1",
                device_class="temperature",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {
            "climate.hvac": {"linked_temperature_sensor": "sensor.hvac_room_temp"}
        }

    def test_climate_with_battery_humidity_and_temperature_all_link(self, filtering):
        # A "fully equipped" thermostat: every applicable rule fires.
        facts = [
            _make_facts(filtering, entity_id="climate.hvac", domain="climate", device_id="t1"),
            _make_facts(
                filtering,
                entity_id="sensor.hvac_battery",
                domain="sensor",
                device_id="t1",
                device_class="battery",
            ),
            _make_facts(
                filtering,
                entity_id="sensor.hvac_humidity",
                domain="sensor",
                device_id="t1",
                device_class="humidity",
            ),
            _make_facts(
                filtering,
                entity_id="sensor.hvac_temp",
                domain="sensor",
                device_id="t1",
                device_class="temperature",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {
            "climate.hvac": {
                "linked_battery_sensor": "sensor.hvac_battery",
                "linked_humidity_sensor": "sensor.hvac_humidity",
                "linked_temperature_sensor": "sensor.hvac_temp",
            }
        }

    def test_humidity_does_not_link_to_light(self, filtering):
        # Humidity is only meaningful on climate/humidifier hosts; lights
        # never get a linked_humidity_sensor even if they share a device.
        facts = [
            _make_facts(filtering, entity_id="light.kitchen", domain="light", device_id="d1"),
            _make_facts(
                filtering,
                entity_id="sensor.kitchen_humidity",
                domain="sensor",
                device_id="d1",
                device_class="humidity",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}

    def test_temperature_does_not_link_to_humidifier(self, filtering):
        # The temperature rule restricts hosts to climate only.
        facts = [
            _make_facts(
                filtering,
                entity_id="humidifier.bedroom",
                domain="humidifier",
                device_id="h1",
            ),
            _make_facts(
                filtering,
                entity_id="sensor.bedroom_temp",
                domain="sensor",
                device_id="h1",
                device_class="temperature",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}

    def test_multiple_humidity_sensors_no_link(self, filtering):
        # Same conservative invariant as battery: ambiguous → skip.
        facts = [
            _make_facts(filtering, entity_id="climate.hvac", domain="climate", device_id="t1"),
            _make_facts(
                filtering,
                entity_id="sensor.h_a",
                domain="sensor",
                device_id="t1",
                device_class="humidity",
            ),
            _make_facts(
                filtering,
                entity_id="sensor.h_b",
                domain="sensor",
                device_id="t1",
                device_class="humidity",
            ),
        ]
        assert filtering.compute_linked_sensors(facts) == {}


class TestLinkAmbiguities:
    def _ambiguous_battery_setup(self, filtering):
        return [
            _make_facts(filtering, entity_id="lock.front", domain="lock", device_id="d1"),
            _make_facts(filtering, entity_id="switch.front", domain="switch", device_id="d1"),
            _make_facts(
                filtering,
                entity_id="sensor.front_battery",
                domain="sensor",
                device_id="d1",
                device_class="battery",
            ),
        ]

    def test_reports_battery_ambiguity(self, filtering):
        facts = self._ambiguous_battery_setup(filtering)
        ambiguities = filtering.compute_link_ambiguities(facts)
        assert len(ambiguities) == 1
        ambig = ambiguities[0]
        assert ambig.device_id == "d1"
        assert ambig.config_key == "linked_battery_sensor"
        assert ambig.sensor_class == "battery"
        assert ambig.sensor_entity_id == "sensor.front_battery"
        # Sorted to keep issue payloads deterministic across runs.
        assert ambig.host_candidates == ("lock.front", "switch.front")

    def test_unambiguous_setup_has_no_ambiguities(self, filtering):
        facts = [
            _make_facts(filtering, entity_id="lock.front", domain="lock", device_id="d1"),
            _make_facts(
                filtering,
                entity_id="sensor.front_battery",
                domain="sensor",
                device_id="d1",
                device_class="battery",
            ),
        ]
        assert filtering.compute_link_ambiguities(facts) == []

    def test_manual_resolution_clears_ambiguity(self, filtering):
        facts = self._ambiguous_battery_setup(filtering)
        manual = {"d1": {"linked_battery_sensor": "lock.front"}}
        assert filtering.compute_link_ambiguities(facts, manual_links=manual) == []

    def test_manual_resolution_referring_to_missing_host_resurfaces(self, filtering):
        # The host the user previously picked has been disabled/removed →
        # ambiguity should re-appear so the user can pick another.
        facts = self._ambiguous_battery_setup(filtering)
        manual = {"d1": {"linked_battery_sensor": "lock.ghost"}}
        ambiguities = filtering.compute_link_ambiguities(facts, manual_links=manual)
        assert len(ambiguities) == 1

    def test_manual_link_applied_in_compute_linked_sensors(self, filtering):
        facts = self._ambiguous_battery_setup(filtering)
        manual = {"d1": {"linked_battery_sensor": "switch.front"}}
        linked = filtering.compute_linked_sensors(facts, manual_links=manual)
        assert linked == {"switch.front": {"linked_battery_sensor": "sensor.front_battery"}}

    def test_manual_link_to_missing_host_is_ignored(self, filtering):
        facts = self._ambiguous_battery_setup(filtering)
        manual = {"d1": {"linked_battery_sensor": "lock.ghost"}}
        # Auto-resolver still skips (because ambiguity) and manual is ignored
        # (because ghost isn't a real candidate) — safer than misattributing.
        assert filtering.compute_linked_sensors(facts, manual_links=manual) == {}
