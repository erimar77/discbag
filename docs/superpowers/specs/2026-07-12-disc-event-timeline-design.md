# A disc's history as an event timeline

**Date:** 2026-07-12
**Status:** Approved for planning

## Problem

`history <disc>` prints a summary (status, use counts, first/last used) but not *what
happened when*. A "full story" wants a chronological timeline of the disc's real events:

```
History

2026-07-12  Added
2026-07-13  Practice session (+1)
2026-07-15  Round (+1)
2026-09-18  Lost (hole 7 water)
```

## Approach: a real event log, seeded and grown incrementally

This is **not** derive-on-read. The event log is the destination from day one — a persisted
list of structured events that is the source of truth for the timeline. "Phased" refers to
*which event sources are wired in over time*, not to rebuilding the foundation later.

Principles:

- **Ship useful output now** from data we already trust (added, usage, lifecycle).
- **Record new events immediately** as those mutations happen.
- **Seed existing discs** once, from known timestamps only.
- **Never invent** events that were never stored — no timestamp, no event.
- **Keep the output format stable** as fidelity grows.

## Data model

Add to `UserData` (`discbag/inventory.py`):

```python
events: Optional[List] = None   # None = never seeded; [] = seeded, legitimately empty
```

Each event is a structured dict (not a pre-baked string, so the renderer can evolve):

| type | fields | example |
|------|--------|---------|
| `added` | `date` | disc entered the bag |
| `use` | `date`, `session_type` (`round`\|`practice`) | a recorded round/practice |
| `status` | `date`, `status`, `reason` | lost / retired / broken / sold / gifted / active |
| `damaged` | `date`, `reason` | plain damage flag set |
| `damaged_retired` | `date`, `reason` | atomic `damaged --retire` |

`date` is the date portion (`YYYY-MM-DD`) of the source timestamp. The `None` sentinel
distinguishes a disc that predates the feature (needs seeding) from one seeded with no
derivable events (`[]`). Accessors guard with `self.events or []`. `to_dict` always writes a
list once seeded, so persisted files never carry `None`.

## Seeding (one-time backfill at load)

Mirror the existing `_backfill_ids` mechanism: `Inventory._load` calls `_seed_events()`,
which for every disc whose `events is None` synthesizes events from trusted timestamps and
then sets `events` to the resulting list (possibly empty). Persist only if anything changed.
Idempotent — a disc with a non-`None` `events` is never reseeded.

Seed sources (real timestamps only):

- `added` from `date_added` (omit if absent).
- one `use` per `use_dates` entry.
- one `status` event from `status_date` when `status != "active"` (omit if no `status_date`).
- one `damaged` event when `damaged and is_active and status_date` (rare; effectively no
  pre-existing damaged discs).

Deliberately **not** seeded: favorite, flight, role, tag — no timestamp was ever stored.

## Live recording (this phase)

The mutations that already carry a timestamp record their event as they happen:

- `add()` → `added` (from `date_added`; undated if none).
- `record_use()` → `use` with the session type.
- `set_status()` → `status` (covers `remove`, `lost`, `replace`'s archive-of-old, and
  `restore` → `active`, which renders as **Restored**).
- `set_damaged(True)` → `damaged`.
- **`retire_damaged()`** — a NEW atomic inventory operation for `damaged --retire`: sets
  `damaged=True`, `status="broken"`, `in_bag=False`, and records **one** `damaged_retired`
  event. It does *not* route through `set_status`, so no duplicate `Broken` event is logged.

`set_damaged(False)` (the `--unset` mistake-fix) records **no** event.

`cmd_damaged --retire` is rewired to call `retire_damaged()` instead of
`set_damaged()` + `set_status()`.

Deferred to the richer phase (hooks only, no seed): favorite, flight, role, tag events.

## Rendering

New module `discbag/history.py`:

```python
def timeline(user) -> list[tuple[str, str]]:
    """(date, label) pairs for a disc's events, oldest-first. Stable sort on date
    keeps insertion order for same-day events."""
```

Label mapping:

| event | label |
|-------|-------|
| added | `Added` |
| use round | `Round (+1)` |
| use practice | `Practice session (+1)` |
| status lost/retired/broken/sold/gifted | `Lost` / `Retired` / `Broken` / `Sold` / `Gifted` |
| status active | `Restored` |
| damaged | `Damaged` |
| damaged_retired | `Damaged and retired` |

A `reason`, when present, is appended as ` (reason)` — e.g. `Lost (hole 7 water)`.
Undated events (no `date`) are omitted from the rendered timeline.

`cmd_history` prints the existing summary unchanged, then, when the timeline is non-empty:

```
History

<date>  <label>
...
```

## Testing

**`tests/test_history.py`** (new) — `timeline()` in isolation:
- one label per event type, including reason suffixes and `Restored`.
- oldest-first ordering; same-day events keep insertion order.
- `damaged_retired` renders as the single combined line.
- undated events are dropped.

**`tests/test_inventory.py`**:
- `add` / `record_use` / `set_status` / `set_damaged(True)` each append the right event;
  `set_damaged(False)` appends none.
- `retire_damaged` sets `damaged`+`broken`+`in_bag=False` and logs exactly one
  `damaged_retired` event.
- seeding: an old disc (`events` absent, with `date_added`/`use_dates`/archived status) is
  seeded from those timestamps; reload does not reseed or duplicate; favorite/flight/role
  are not seeded.

**`tests/test_cli.py`**:
- `history` prints the summary *and* a timeline including a use and a lifecycle event.
- `damaged --retire` produces a single `Damaged and retired` timeline entry.

## Docs

README `history` blurb gains the timeline; CHANGELOG entry describes the event log, seeding,
and the phase-1 event set (added, usage, status, damaged/retired), noting favorite/flight/
role/tag are deferred.

## Out of scope (YAGNI / later phases)

- favorite, flight, role, tag events (hooks added in later commits).
- Running/cumulative counts in timeline lines — the summary owns totals.
- Reverse order, filtering, or per-event times — date-granularity, oldest-first only.
- Editing or deleting individual events.
