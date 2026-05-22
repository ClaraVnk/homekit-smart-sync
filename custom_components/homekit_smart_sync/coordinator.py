"""Coordinator — the only module that talks to the HA runtime.

Responsibilities:

1. Listen to registry events (filtered).
2. Debounce sync calls (``SYNC_DEBOUNCE_SECONDS``) so a startup burst or
   rapid UI edits collapse into a single bridge reload.
3. Snapshot every targeted HomeKit bridge's original ``entry.options``
   the first time we touch it, persisted in our own ConfigEntry — so an
   uninstall via :func:`async_unload_entry` restores the bridge cleanly.
4. Diff the computed options against the bridge's current options; only
   update + reload when the dict actually differs. Required to keep the
   loop closed (registry change → sync → no diff → no reload → no event).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.debounce import Debouncer

from .const import (
    CONF_BRIDGE_ENTRY_IDS,
    CONF_ENABLE_FILTER,
    CONF_ENABLE_NAMING,
    CONF_EXTRA_EXCLUDED_DOMAINS,
    CONF_ORIGINAL_OPTIONS_SNAPSHOT,
    HOMEKIT_DOMAIN,
    SYNC_DEBOUNCE_SECONDS,
)
from .filtering import compute_filter, compute_linked_sensors
from .naming import clean_entity_name
from .registry_resolver import (
    area_name_map,
    collect_entity_facts,
    entity_friendly_name,
    resolve_entity_area_id,
)

_LOGGER = logging.getLogger(__name__)

_RELEVANT_ENTITY_CHANGES = frozenset(
    {"name", "area_id", "disabled_by", "hidden_by", "entity_category", "device_id"}
)


class SmartSyncCoordinator:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._bridge_entry_ids: list[str] = []
        self._enable_naming: bool = True
        self._enable_filter: bool = True
        self._extra_excluded_domains: list[str] = []
        self._debouncer: Debouncer | None = None

    async def async_initial_setup(self) -> None:
        self.refresh_options_from_entry()
        self._debouncer = Debouncer(
            self._hass,
            _LOGGER,
            cooldown=SYNC_DEBOUNCE_SECONDS,
            immediate=False,
            function=self._async_perform_sync,
        )

    def refresh_options_from_entry(self) -> None:
        opts = self._entry.options
        self._bridge_entry_ids = list(opts.get(CONF_BRIDGE_ENTRY_IDS, []))
        self._enable_naming = bool(opts.get(CONF_ENABLE_NAMING, True))
        self._enable_filter = bool(opts.get(CONF_ENABLE_FILTER, True))
        self._extra_excluded_domains = list(opts.get(CONF_EXTRA_EXCLUDED_DOMAINS, []))

    # ------------------------------------------------------------------ events

    @callback
    def handle_entity_registry_event(self, event: Event) -> None:
        data = event.data
        action = data.get("action")
        if action == "update":
            changes = data.get("changes") or {}
            if not (set(changes.keys()) & _RELEVANT_ENTITY_CHANGES):
                return
        self.schedule_sync(reason=f"entity_registry_{action}")

    @callback
    def handle_area_registry_event(self, event: Event) -> None:
        self.schedule_sync(reason=f"area_registry_{event.data.get('action')}")

    @callback
    def schedule_sync(self, *, reason: str) -> None:
        if self._debouncer is None:
            return
        _LOGGER.debug("Sync scheduled (debounced %.1fs): %s", SYNC_DEBOUNCE_SECONDS, reason)
        self._hass.async_create_task(self._debouncer.async_call())

    # ------------------------------------------------------------------ sync

    async def _async_perform_sync(self) -> None:
        if not self._bridge_entry_ids:
            return
        if not (self._enable_naming or self._enable_filter):
            return

        facts = collect_entity_facts(self._hass)
        areas = area_name_map(self._hass)
        ent_reg = er.async_get(self._hass)
        dev_reg = dr.async_get(self._hass)

        # entity_id → cleaned alias (only entries where we actually rename).
        name_overrides: dict[str, str] = {}
        if self._enable_naming:
            for entry in ent_reg.entities.values():
                if entry.disabled_by or entry.hidden_by:
                    continue
                area_id = resolve_entity_area_id(entry, dev_reg)
                if not area_id:
                    continue
                friendly = entity_friendly_name(entry, self._hass)
                cleaned = clean_entity_name(friendly, areas.get(area_id))
                if cleaned:
                    name_overrides[entry.entity_id] = cleaned

        # filter + linked sensors (filter is the user's main exposure control)
        if self._enable_filter:
            filter_dict = compute_filter(facts, extra_excluded_domains=self._extra_excluded_domains)
            linked = compute_linked_sensors(facts)
        else:
            filter_dict = None
            linked = {}

        # Persist snapshots before mutating anything.
        snapshots = dict(self._entry.options.get(CONF_ORIGINAL_OPTIONS_SNAPSHOT, {}))
        snapshots_changed = False

        for bridge_entry_id in self._bridge_entry_ids:
            bridge = self._hass.config_entries.async_get_entry(bridge_entry_id)
            if bridge is None or bridge.domain != HOMEKIT_DOMAIN:
                _LOGGER.warning(
                    "Configured HomeKit bridge %s is missing or not a homekit entry",
                    bridge_entry_id,
                )
                continue

            if bridge_entry_id not in snapshots:
                snapshots[bridge_entry_id] = dict(bridge.options)
                snapshots_changed = True

            base = snapshots[bridge_entry_id]
            new_options = self._compose_options(
                base=base,
                name_overrides=name_overrides,
                linked_sensors=linked,
                filter_dict=filter_dict,
            )

            if _options_equal(bridge.options, new_options):
                continue

            _LOGGER.info(
                "Pushing updated options to HomeKit bridge %s "
                "(%d name overrides, %d linked-sensor hosts)",
                bridge.title or bridge_entry_id,
                len(name_overrides),
                len(linked),
            )
            self._hass.config_entries.async_update_entry(bridge, options=new_options)
            await self._hass.config_entries.async_reload(bridge_entry_id)

        if snapshots_changed:
            self._hass.config_entries.async_update_entry(
                self._entry,
                options={
                    **self._entry.options,
                    CONF_ORIGINAL_OPTIONS_SNAPSHOT: snapshots,
                },
            )

    def _compose_options(
        self,
        *,
        base: dict[str, Any],
        name_overrides: dict[str, str],
        linked_sensors: dict[str, dict[str, str]],
        filter_dict: dict | None,
    ) -> dict[str, Any]:
        """Layer our overlays on top of the bridge's original options.

        We start from the *snapshot* (not the bridge's current options) so
        successive syncs are deterministic and never accumulate stale
        overrides. The user's manual edits in the original config are
        preserved; we only add/override our own keys.
        """
        new_options: dict[str, Any] = dict(base)

        # entity_config: deep-merge per entity. Don't blow away unrelated
        # keys the user may have set.
        existing_entity_config = dict(base.get("entity_config", {}))
        for entity_id, alias in name_overrides.items():
            cfg = dict(existing_entity_config.get(entity_id, {}))
            cfg["name"] = alias
            existing_entity_config[entity_id] = cfg
        for host_entity_id, link_keys in linked_sensors.items():
            cfg = dict(existing_entity_config.get(host_entity_id, {}))
            cfg.update(link_keys)
            existing_entity_config[host_entity_id] = cfg
        if existing_entity_config:
            new_options["entity_config"] = existing_entity_config

        if filter_dict is not None:
            # Union with the user's manual excludes; never narrow them away.
            base_filter = base.get("filter", {}) or {}
            merged_excl_entities = sorted(
                set(filter_dict["exclude_entities"]) | set(base_filter.get("exclude_entities", []))
            )
            merged_excl_domains = sorted(
                set(filter_dict["exclude_domains"]) | set(base_filter.get("exclude_domains", []))
            )
            new_options["filter"] = {
                "include_domains": filter_dict["include_domains"],
                "include_entities": base_filter.get("include_entities", []),
                "exclude_domains": merged_excl_domains,
                "exclude_entities": merged_excl_entities,
            }

        return new_options

    # ----------------------------------------------------------------- restore

    async def async_restore_and_teardown(self) -> None:
        if self._debouncer is not None:
            # ``Debouncer.async_shutdown`` is a synchronous ``@callback`` in
            # modern HA — do not await it.
            self._debouncer.async_shutdown()
            self._debouncer = None

        snapshots = self._entry.options.get(CONF_ORIGINAL_OPTIONS_SNAPSHOT, {})
        if not isinstance(snapshots, dict):
            _LOGGER.warning(
                "Snapshot store is malformed (got %s) — skipping bridge restoration",
                type(snapshots).__name__,
            )
            return

        for bridge_entry_id, original_options in snapshots.items():
            if not isinstance(original_options, dict):
                _LOGGER.warning("Snapshot for bridge %s is malformed — skipping", bridge_entry_id)
                continue
            bridge = self._hass.config_entries.async_get_entry(bridge_entry_id)
            if bridge is None:
                _LOGGER.debug("Bridge %s no longer exists — nothing to restore", bridge_entry_id)
                continue
            if _options_equal(bridge.options, original_options):
                continue
            self._hass.config_entries.async_update_entry(bridge, options=original_options)
            try:
                await self._hass.config_entries.async_reload(bridge_entry_id)
            except Exception:
                _LOGGER.exception("Restore: failed to reload HomeKit bridge %s", bridge_entry_id)


def _options_equal(a: dict, b: dict) -> bool:
    """Deep equality on the subset of options we care about.

    Using ``a == b`` directly works because HA stores options as plain
    JSON-serializable dicts/lists/scalars. Kept as a named helper so we
    can swap in a canonical-form comparison later if needed.
    """
    return a == b
