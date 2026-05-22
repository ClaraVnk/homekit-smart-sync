# Changelog

All notable changes to **HomeKit Smart Sync** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] — 2026-05-22

First feature-complete release.

### Added

- **Siri Name Cleaner**: strips redundant area prefixes/suffixes from the
  per-entity aliases pushed to HomeKit. Idempotent, accent- and case-insensitive,
  supports multi-word area names.
- **Smart Filter for voice**: excludes diagnostic/config entities, `power` /
  `energy` / `voltage` / `current` / `battery` / `signal_strength` sensors,
  and uncategorized binary sensors from the bridge. Keeps motion, door,
  occupancy, smoke and similar useful sensors.
- **Linked sensors**: `battery`, `humidity` and `temperature` helper sensors
  are re-attached to their voice-actionable sibling on the same device via
  `linked_battery_sensor` / `linked_humidity_sensor` / `linked_temperature_sensor`
  instead of being silently dropped — preserves Apple Home's "Low Battery"
  notification and richer climate tile.
- **Repairs flow** for ambiguous link cases: when a device has one sensor
  but multiple eligible hosts, Smart Sync surfaces an issue in
  Settings → Repairs; the interactive fix flow lets the user pick the host
  and persists the choice.
- **Per-bridge enable/disable** in the options flow: `naming_bridges` and
  `filter_bridges` subsets of the managed bridges, so a "production" bridge
  can have everything on while an "experimental" bridge has only the filter.
  Legacy `enable_naming` / `enable_filter` booleans migrate automatically.
- **Custom per-entity aliases** via the `homekit_smart_sync.set_alias` and
  `homekit_smart_sync.clear_alias` services — win over both auto-cleaning
  and term translation.
- **Term translation** via `homekit_smart_sync.set_translation` and
  `homekit_smart_sync.clear_translation`: register multi-word phrase
  substitutions applied to every auto-cleaned alias (longest-match,
  case-insensitive). Useful when HA friendly names are in English but the
  household speaks something else.
- **Snapshot-and-restore**: original bridge options are captured on the
  first sync and restored on `async_unload_entry`, so uninstalling Smart
  Sync returns the bridge exactly to its prior state.
- **Debounced sync** (8 s window) coalescing bursts of registry events
  into a single bridge reload — minimises the "Not Responding" flash in
  Apple Home.
- **HACS-ready packaging**: manifest in canonical key order, brand assets
  shipped in-repo (`custom_components/homekit_smart_sync/brand/`),
  `hacs.json`, `info.md`, `services.yaml` with matching `strings.json`
  translations (English + French).
- **Test suite**: 41 pure-module unit tests (no HA dependency) via an
  importlib shim in `tests/conftest.py`, plus 36 integration tests under
  `tests/integration/` exercising config flow, sync, restore, repairs and
  services against a real HA runtime (`pytest-homeassistant-custom-component`).
- **CI**: hassfest, HACS validation, ruff check + format, pytest on Python
  3.12 and 3.13.
- **Pre-commit hook** wiring ruff so format mistakes can't slip into a
  commit (see `.pre-commit-config.yaml`).

### Documentation

- README with badges, hero SVG (before/after Siri behaviour), Mermaid
  architecture diagram, services reference table.
- `SHOOT_LIST.md` (dev-local, gitignored): priority-ordered checklist for
  the real HA UI screenshots once a test instance is available.

[Unreleased]: https://github.com/ClaraVnk/homekit-smart-sync/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ClaraVnk/homekit-smart-sync/releases/tag/v0.1.0
