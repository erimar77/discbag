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
events: Optional[List] = None   # None = legacy disc needing seeding; list = seeded
```

Each event is a structured dict (not a pre-baked string, so the renderer can evolve). The
expected schema, documented as an internal `TypedDict` (`total=False`) for clarity even
though persistence stays plain dicts:

| type | fields | example |
|------|--------|---------|
| `added` | `date` | disc entered the bag |
| `use` | `date`, `session_type` (`round`\|`practice`) | a recorded round/practice |
| `status` | `date`, `status`, `reason` | lost / retired / broken / sold / gifted / active |
| `damaged` | `date`, `reason` | plain damage flag set |
| `damaged_retired` | `date`, `reason` | atomic `damaged --retire` |

`date` is the date portion (`YYYY-MM-DD`) of the source timestamp.

**Event initialization — `None` means exactly "needs seeding":**

- **Newly created discs always start with `events=[]`** — `add()` initializes the list (and
  appends the `added` event), so a disc created through the code never carries `None`.
- **Only legacy discs loaded from pre-feature data may have `events=None`**, which the loader
  treats as the signal to seed. After seeding, `events` is a list (possibly empty).

Accessors guard with `self.events or []`. `to_dict` always writes a list once seeded, so
persisted files never carry `None`.

**Forward compatibility:** the renderer **ignores unknown event types** (and unknown fields)
rather than failing, so a newer event kind written by a later version degrades gracefully in
an older one.

## Seeding (one-time backfill at load)

Mirror the existing `_backfill_ids` mechanism: `Inventory._load` calls `_seed_events()`,
which for every disc whose `events is None` synthesizes events from trusted timestamps and
then sets `events` to the resulting list (possibly empty). Persist only if anything changed.
Idempotent — a disc with a non-`None` `events` is never reseeded.

Seed sources (real timestamps only):

- `added` from `date_added` (omit if absent).
- one `use` per `use_dates` entry.
- one `status` event from `status_date` when `status != "active"` (omit if no `status_date`).
  A seeded `status` event represents the **last known transition into the current status**,
  not a complete historical record — legacy data only ever stored the latest one.

Deliberately **not** seeded:

- **Damage.** A pre-feature disc's `status_date` was not necessarily written when the damage
  occurred, so seeding a `damaged` event from it would invent a timestamp — forbidden. An
  existing damaged disc simply stays "currently damaged" in the summary; no historical damage
  event is synthesized. Damage is recorded normally from the first live mutation onward.
- **favorite, flight, role, tag** — no timestamp was ever stored.

## Live recording (this phase)

**Ownership: `Inventory` methods are the sole recorders of events.** CLI commands never append
events directly — they call inventory methods, which append. This keeps recording in one place
and avoids duplicate events when an inventory method is reused elsewhere (e.g. `replace` reuses
`set_status` and `add`).

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

Every status value `set_status()` can persist has a label: `active`, `lost`, `retired`,
`broken`, `sold`, `gifted` (the `_ARCHIVE_STATUSES` list plus `active`). A test asserts this
mapping stays exhaustive, so adding a status without a label fails loudly. An unknown status —
or an unknown event `type` — is skipped rather than rendered as a crash or a raw value.

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
- undated events are dropped; unknown event `type` and unknown status are skipped, not raised.
- every status in `_ARCHIVE_STATUSES` + `active` has a label (guards against a future status
  slipping through unlabelled).

**`tests/test_inventory.py`**:
- `add` / `record_use` / `set_status` / `set_damaged(True)` each append the right event;
  `set_damaged(False)` appends none.
- `retire_damaged` sets `damaged`+`broken`+`in_bag=False` and logs exactly one
  `damaged_retired` event.
- seeding: an old disc (`events` absent, with `date_added`/`use_dates`/archived status) is
  seeded from those timestamps; reload does not reseed or duplicate; damage, favorite, flight,
  role, and tag are **not** seeded (a legacy damaged disc gets no historical damage event).

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
