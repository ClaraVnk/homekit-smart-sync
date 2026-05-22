"""Repairs flow — interactive resolution of ambiguous sensor-link cases.

When the coordinator detects that a device has one helper sensor (battery,
humidity, temperature…) but multiple eligible host entities, it creates an
issue via :func:`homeassistant.helpers.issue_registry.async_create_issue`.
This module hosts the corresponding ``RepairsFlow``: a single-step form that
asks the user which host should own the link, persists that choice in the
integration's options, and dismisses the issue.

The fix flow does not touch the HomeKit bridge directly — saving the choice
mutates our ConfigEntry, the options-update listener wakes the coordinator,
and the debounced sync writes the link to the bridge on the next pass.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """HA entry point — instantiate the right flow for the issue."""
    return AmbiguousLinkRepairFlow(data or {})


class AmbiguousLinkRepairFlow(RepairsFlow):
    """Ask the user which host should own a sensor link.

    ``data`` is the dict passed to ``async_create_issue`` — it carries the
    device id, the link config key, the sensor entity id, the list of host
    candidates, and our own entry id so we can look the coordinator back up.
    """

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_pick_host()

    async def async_step_pick_host(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        candidates: list[str] = list(self._data.get("host_candidates") or [])
        if not candidates:
            # The ambiguity evaporated between issue creation and the user
            # opening the flow (entity removed, device gone). Nothing to do.
            return self.async_create_entry(data={})

        if user_input is not None:
            await self._persist_choice(user_input["host"])
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="pick_host",
            data_schema=vol.Schema(
                {
                    vol.Required("host"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=host, label=host)
                                for host in candidates
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            description_placeholders={
                "sensor": str(self._data.get("sensor_entity_id", "")),
                "config_key": str(self._data.get("config_key", "")),
            },
        )

    async def _persist_choice(self, host_entity_id: str) -> None:
        entry_id = self._data.get("entry_id")
        if not entry_id:
            return
        bucket = self.hass.data.get(DOMAIN, {})
        coordinator = bucket.get(entry_id)
        if coordinator is None:
            # Integration might be unloading. Bail out — without an alive
            # coordinator we have no way to refresh options safely.
            entry = self.hass.config_entries.async_get_entry(entry_id)
            if entry is None or entry.state is ConfigEntryState.NOT_LOADED:
                return
            return
        coordinator.record_manual_link(
            device_id=str(self._data["device_id"]),
            config_key=str(self._data["config_key"]),
            host_entity_id=host_entity_id,
        )
