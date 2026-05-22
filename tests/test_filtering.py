"""Tests for the Smart Filter and linked-battery resolution."""

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
        linked = filtering.compute_linked_batteries(facts)
        assert linked == {"lock.front": "sensor.front_battery"}

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
        linked = filtering.compute_linked_batteries(facts)
        assert linked == {}

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
        linked = filtering.compute_linked_batteries(facts)
        assert linked == {}

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
        linked = filtering.compute_linked_batteries(facts)
        assert linked == {}

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
        linked = filtering.compute_linked_batteries(facts)
        assert linked == {}

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
        linked = filtering.compute_linked_batteries(facts)
        assert linked == {}
