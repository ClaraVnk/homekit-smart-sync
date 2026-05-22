"""Constants for HomeKit Smart Sync."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "homekit_smart_sync"
HOMEKIT_DOMAIN: Final = "homekit"

# Options keys (persisted in ConfigEntry.options)
CONF_BRIDGE_ENTRY_IDS: Final = "bridge_entry_ids"
CONF_ENABLE_NAMING: Final = "enable_naming"
CONF_ENABLE_FILTER: Final = "enable_filter"
CONF_EXTRA_EXCLUDED_DOMAINS: Final = "extra_excluded_domains"
CONF_ORIGINAL_OPTIONS_SNAPSHOT: Final = "_original_options_snapshot"

# Debounce window before pushing options into the HomeKit bridge.
# Long enough to coalesce a startup burst of registry events,
# short enough to feel "live" when the user edits an area in the UI.
SYNC_DEBOUNCE_SECONDS: Final = 8.0

# Default smart filter rules.
EXCLUDED_ENTITY_CATEGORIES: Final = frozenset({"diagnostic", "config"})

# Sensor device_classes that pollute Siri/Home and should be hidden by default.
EXCLUDED_SENSOR_DEVICE_CLASSES: Final = frozenset(
    {
        "battery",
        "power",
        "energy",
        "voltage",
        "current",
        "apparent_power",
        "reactive_power",
        "power_factor",
        "signal_strength",
        "data_rate",
        "data_size",
        "frequency",
    }
)

# Domains we consider "voice-actionable" by default. Everything else
# is filtered out unless the user explicitly re-adds it.
VOICE_ACTIONABLE_DOMAINS: Final = frozenset(
    {
        "light",
        "switch",
        "cover",
        "lock",
        "climate",
        "fan",
        "media_player",
        "scene",
        "script",
        "vacuum",
        "humidifier",
        "input_boolean",
    }
)

# Sensor/binary_sensor are kept conditionally (temperature, humidity, motion…).
CONDITIONAL_DOMAINS: Final = frozenset({"sensor", "binary_sensor"})

KEEP_SENSOR_DEVICE_CLASSES: Final = frozenset(
    {"temperature", "humidity", "co2", "co", "pm25", "illuminance"}
)
