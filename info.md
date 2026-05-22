# HomeKit Smart Sync

Make Home Assistant the single source of truth for your Apple Home and Siri
setup — no more renaming the same accessory twice.

Smart Sync sits in front of the official `homekit` bridge. It watches your
entity and area registries, computes a clean per-entity name override and a
voice-aware exposure filter, then pushes those into the bridge — automatically.

**What it does**

- **Siri Name Cleaner** — strips redundant area names. `light.living_room_ceiling`
  in *Living Room* becomes simply *Ceiling Light* in Apple Home.
- **Auto-Room Persistent Mapping** — re-syncs whenever HA's areas or
  entities change, with a debounced bridge reload.
- **Smart Filter for Voice** — hides diagnostic entities, power/energy
  sensors, secondary batteries, and other noise. Battery sensors are
  re-attached via `linked_battery_sensor` so Apple's "Low Battery"
  notifications keep working.

After install: *Settings → Devices & Services → Add Integration → HomeKit Smart Sync*,
then pick which bridge(s) to manage.

> ⚠️ Bridge reloads cause a brief (~1–3s) "Not Responding" flash in Apple Home.
> Smart Sync coalesces updates with an 8 s debounce to minimise this.
