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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.debounce import Debouncer

from .const import (
    CONF_BRIDGE_ENTRY_IDS,
    CONF_ENABLE_FILTER,
    CONF_ENABLE_NAMING,
    CONF_EXTRA_EXCLUDED_DOMAINS,
    CONF_FILTER_BRIDGES,
    CONF_MANUAL_LINKS,
    CONF_MANUAL_NAMES,
    CONF_NAMING_BRIDGES,
    CONF_ORIGINAL_OPTIONS_SNAPSHOT,
    DOMAIN,
    HOMEKIT_DOMAIN,
    SYNC_DEBOUNCE_SECONDS,
)
from .filtering import (
    AmbiguousLink,
    compute_filter,
    compute_link_ambiguities,
    compute_linked_sensors,
)
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
        # Per-bridge feature sets (subsets of bridge_entry_ids). The
        # legacy bool toggles are migrated into these on refresh.
        self._naming_bridges: set[str] = set()
        self._filter_bridges: set[str] = set()
        self._extra_excluded_domains: list[str] = []
        self._manual_links: dict[str, dict[str, str]] = {}
        self._manual_names: dict[str, str] = {}
        self._debouncer: Debouncer | None = None
        # Issue IDs we have raised this session — used to clean up issues
        # that no longer apply (ambiguity resolved or device removed).
        self._active_issue_ids: set[str] = set()

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
        self._extra_excluded_domains = list(opts.get(CONF_EXTRA_EXCLUDED_DOMAINS, []))

        all_bridges = set(self._bridge_entry_ids)
        self._naming_bridges = _resolve_feature_bridges(
            opts, CONF_NAMING_BRIDGES, CONF_ENABLE_NAMING, all_bridges
        )
        self._filter_bridges = _resolve_feature_bridges(
            opts, CONF_FILTER_BRIDGES, CONF_ENABLE_FILTER, all_bridges
        )

        raw_manual = opts.get(CONF_MANUAL_LINKS, {})
        # Be defensive — storage could be malformed if hand-edited.
        if isinstance(raw_manual, dict):
            self._manual_links = {
                str(dev_id): {str(k): str(v) for k, v in mapping.items()}
                for dev_id, mapping in raw_manual.items()
                if isinstance(mapping, dict)
            }
        else:
            self._manual_links = {}

        raw_names = opts.get(CONF_MANUAL_NAMES, {})
        if isinstance(raw_names, dict):
            self._manual_names = {
                str(eid): str(alias)
                for eid, alias in raw_names.items()
                if isinstance(alias, str) and alias
            }
        else:
            self._manual_names = {}

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
        # If neither feature is enabled on any bridge there is nothing to do.
        if not (self._naming_bridges or self._filter_bridges):
            self._reconcile_repair_issues([])
            return

        facts = collect_entity_facts(self._hass)
        areas = area_name_map(self._hass)
        ent_reg = er.async_get(self._hass)
        dev_reg = dr.async_get(self._hass)

        # entity_id → alias, computed once and re-used per bridge. Bridges
        # that have naming disabled simply receive an empty dict. Manual
        # overrides from the set_alias service take precedence over the
        # automatic Siri Name Cleaner output.
        name_overrides: dict[str, str] = {}
        if self._naming_bridges:
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
            # Manual aliases override the auto-cleaned ones and apply even
            # to entities without an area (which the auto-cleaner skips).
            for entity_id, alias in self._manual_names.items():
                name_overrides[entity_id] = alias

        # Filter + linked-sensor outputs are also bridge-agnostic; per-bridge
        # gating happens at compose time below. We still always recompute
        # ambiguities so the Repairs flow surfaces them whenever filter is
        # enabled on at least one bridge.
        if self._filter_bridges:
            filter_dict = compute_filter(facts, extra_excluded_domains=self._extra_excluded_domains)
            linked = compute_linked_sensors(facts, manual_links=self._manual_links)
            ambiguities = compute_link_ambiguities(facts, manual_links=self._manual_links)
            self._reconcile_repair_issues(ambiguities)
        else:
            filter_dict = None
            linked = {}
            self._reconcile_repair_issues([])

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
            # Per-bridge gating: only push what is enabled for THIS bridge.
            bridge_names = name_overrides if bridge_entry_id in self._naming_bridges else {}
            if bridge_entry_id in self._filter_bridges:
                bridge_linked = linked
                bridge_filter = filter_dict
            else:
                bridge_linked = {}
                bridge_filter = None

            new_options = self._compose_options(
                base=base,
                name_overrides=bridge_names,
                linked_sensors=bridge_linked,
                filter_dict=bridge_filter,
            )

            if _options_equal(bridge.options, new_options):
                continue

            _LOGGER.info(
                "Pushing updated options to HomeKit bridge %s "
                "(%d name overrides, %d linked-sensor hosts)",
                bridge.title or bridge_entry_id,
                len(bridge_names),
                len(bridge_linked),
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

    # ------------------------------------------------------------ repair flow

    @staticmethod
    def issue_id_for(ambig: AmbiguousLink) -> str:
        """Deterministic ID so the same ambiguity does not raise twice."""
        return f"ambiguous_link::{ambig.sensor_class}::{ambig.device_id}"

    def _reconcile_repair_issues(self, ambiguities: list[AmbiguousLink]) -> None:
        """Create issues for newly ambiguous cases, delete stale ones."""
        desired_ids = {self.issue_id_for(a) for a in ambiguities}

        for ambig in ambiguities:
            issue_id = self.issue_id_for(ambig)
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="ambiguous_link",
                translation_placeholders={
                    "sensor_class": ambig.sensor_class,
                    "sensor": ambig.sensor_entity_id,
                    "candidates": ", ".join(ambig.host_candidates),
                },
                data={
                    "device_id": ambig.device_id,
                    "config_key": ambig.config_key,
                    "sensor_entity_id": ambig.sensor_entity_id,
                    "host_candidates": list(ambig.host_candidates),
                    "entry_id": self._entry.entry_id,
                },
            )
            self._active_issue_ids.add(issue_id)

        # Anything previously raised that no longer applies → delete.
        for stale_id in self._active_issue_ids - desired_ids:
            ir.async_delete_issue(self._hass, DOMAIN, stale_id)
        self._active_issue_ids &= desired_ids

    def record_manual_link(self, device_id: str, config_key: str, host_entity_id: str) -> None:
        """Persist a user's repair-flow choice into our entry options.

        Called from ``repairs.py`` after the user picks a host. Triggering a
        re-sync is the listener's responsibility (the options-update event
        fires automatically and is handled by ``_async_options_updated`` in
        :mod:`__init__`).
        """
        existing = dict(self._entry.options.get(CONF_MANUAL_LINKS, {}))
        per_device = dict(existing.get(device_id, {}))
        per_device[config_key] = host_entity_id
        existing[device_id] = per_device
        self._hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_MANUAL_LINKS: existing},
        )

    def record_manual_name(self, entity_id: str, alias: str) -> None:
        """Persist a user-supplied alias from the ``set_alias`` service."""
        existing = dict(self._entry.options.get(CONF_MANUAL_NAMES, {}))
        existing[entity_id] = alias
        self._hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_MANUAL_NAMES: existing},
        )

    def clear_manual_name(self, entity_id: str) -> None:
        """Drop a manual alias so the auto-cleaner resumes for this entity."""
        existing = dict(self._entry.options.get(CONF_MANUAL_NAMES, {}))
        if existing.pop(entity_id, None) is None:
            return
        self._hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_MANUAL_NAMES: existing},
        )

    # ----------------------------------------------------------------- restore

    async def async_restore_and_teardown(self) -> None:
        if self._debouncer is not None:
            # ``Debouncer.async_shutdown`` is a synchronous ``@callback`` in
            # modern HA — do not await it.
            self._debouncer.async_shutdown()
            self._debouncer = None

        # Clear any repair issues we raised — they would otherwise linger in
        # the user's Repairs dashboard after the integration is uninstalled.
        for issue_id in list(self._active_issue_ids):
            ir.async_delete_issue(self._hass, DOMAIN, issue_id)
        self._active_issue_ids.clear()

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


def _resolve_feature_bridges(
    opts: dict[str, Any],
    new_key: str,
    legacy_bool_key: str,
    all_bridges: set[str],
) -> set[str]:
    """Pick the effective bridge set for a feature.

    Reads the per-bridge list at ``new_key`` if present. Otherwise falls
    back to the legacy boolean — ``True`` means all bridges, ``False``
    means none. Unknown bridges (in storage but no longer selected) are
    silently dropped to keep state consistent after the user trims their
    bridge selection.
    """
    raw = opts.get(new_key)
    if isinstance(raw, list):
        return {str(b) for b in raw if b in all_bridges}
    legacy = bool(opts.get(legacy_bool_key, True))
    return set(all_bridges) if legacy else set()


def _options_equal(a: dict, b: dict) -> bool:
    """Deep equality on the subset of options we care about.

    Using ``a == b`` directly works because HA stores options as plain
    JSON-serializable dicts/lists/scalars. Kept as a named helper so we
    can swap in a canonical-form comparison later if needed.
    """
    return a == b
