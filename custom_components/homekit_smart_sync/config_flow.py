"""Config and options flow for HomeKit Smart Sync."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BRIDGE_ENTRY_IDS,
    CONF_ENABLE_FILTER,
    CONF_ENABLE_NAMING,
    CONF_EXTRA_EXCLUDED_DOMAINS,
    CONF_FILTER_BRIDGES,
    CONF_NAMING_BRIDGES,
    DOMAIN,
    HOMEKIT_DOMAIN,
)


def _available_homekit_bridges(hass) -> dict[str, str]:
    """Return {entry_id: human label} for every loaded HomeKit bridge entry.

    We intentionally surface only bridges (not accessory-mode entries),
    because Smart Sync's value proposition — coalescing many entities
    behind clean Siri-friendly names — does not apply to single-accessory
    setups.
    """
    bridges: dict[str, str] = {}
    for entry in hass.config_entries.async_entries(HOMEKIT_DOMAIN):
        mode = entry.data.get("mode", "bridge")
        if mode != "bridge":
            continue
        name = entry.title or entry.data.get("name") or entry.entry_id
        port = entry.data.get("port")
        label = f"{name} (port {port})" if port else name
        bridges[entry.entry_id] = label
    return bridges


class HomeKitSmartSyncConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Single-instance flow. Pick which HomeKit bridges to manage."""
        # Singleton: it never makes sense to run two coordinators in parallel —
        # they would race on the same bridge options.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        bridges = _available_homekit_bridges(self.hass)
        if not bridges:
            return self.async_abort(reason="no_homekit_bridges")

        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input[CONF_BRIDGE_ENTRY_IDS]
            if not selected:
                errors["base"] = "no_bridge_selected"
            else:
                return self.async_create_entry(
                    title="HomeKit Smart Sync",
                    data={},
                    options={
                        CONF_BRIDGE_ENTRY_IDS: selected,
                        CONF_ENABLE_NAMING: user_input.get(CONF_ENABLE_NAMING, True),
                        CONF_ENABLE_FILTER: user_input.get(CONF_ENABLE_FILTER, True),
                        CONF_EXTRA_EXCLUDED_DOMAINS: [],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_BRIDGE_ENTRY_IDS): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=eid, label=label)
                            for eid, label in bridges.items()
                        ],
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(CONF_ENABLE_NAMING, default=True): bool,
                vol.Optional(CONF_ENABLE_FILTER, default=True): bool,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return HomeKitSmartSyncOptionsFlow(entry)


class HomeKitSmartSyncOptionsFlow(OptionsFlow):
    """Options flow — tune the sync after initial setup."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # Validate per-bridge subsets against the selected bridges so the
            # coordinator never has to defend against drift between the keys.
            selected_bridges = set(user_input.get(CONF_BRIDGE_ENTRY_IDS, []))
            user_input[CONF_NAMING_BRIDGES] = [
                b for b in user_input.get(CONF_NAMING_BRIDGES, []) if b in selected_bridges
            ]
            user_input[CONF_FILTER_BRIDGES] = [
                b for b in user_input.get(CONF_FILTER_BRIDGES, []) if b in selected_bridges
            ]
            return self.async_create_entry(title="", data=user_input)

        current = self._entry.options
        bridges = _available_homekit_bridges(self.hass)
        bridge_options = [
            selector.SelectOptionDict(value=eid, label=label) for eid, label in bridges.items()
        ]

        # Defaults for per-bridge feature lists: prefer stored value, fall
        # back to the legacy bool (True → all bridges, False → none).
        currently_selected = list(current.get(CONF_BRIDGE_ENTRY_IDS, []))
        legacy_naming_on = bool(current.get(CONF_ENABLE_NAMING, True))
        legacy_filter_on = bool(current.get(CONF_ENABLE_FILTER, True))
        naming_default = current.get(
            CONF_NAMING_BRIDGES,
            currently_selected if legacy_naming_on else [],
        )
        filter_default = current.get(
            CONF_FILTER_BRIDGES,
            currently_selected if legacy_filter_on else [],
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BRIDGE_ENTRY_IDS,
                    default=currently_selected,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=bridge_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_NAMING_BRIDGES,
                    default=naming_default,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=bridge_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_FILTER_BRIDGES,
                    default=filter_default,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=bridge_options,
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Optional(
                    CONF_EXTRA_EXCLUDED_DOMAINS,
                    default=current.get(CONF_EXTRA_EXCLUDED_DOMAINS, []),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            "sensor",
                            "binary_sensor",
                            "scene",
                            "script",
                            "media_player",
                            "fan",
                        ],
                        multiple=True,
                        custom_value=True,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
