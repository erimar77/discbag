# Mark discs lost or damaged — lifecycle verbs

**Date:** 2026-07-12
**Status:** Approved for planning

## Problem

You can already archive a disc with a lifecycle status (`lost`, `broken`, etc.) via
`discbag remove <disc> --status lost`, but nobody guesses that "mark as lost" lives under
`remove`. There is also no way to say *"this disc is beat up but I'm still throwing it"* —
`remove` only archives. This feature adds first-class, discoverable verbs for the two
things that actually happen to a disc: it gets **lost**, or it gets **damaged** (either
still-carried-but-worn, or worn beyond use).

The plumbing already exists (`UserData.status`, `Inventory.set_status`, `restore`,
`history`). This is a UX layer over that engine plus one new orthogonal flag — not a new
subsystem.

## Domain facts that shaped the design

- **Discs are plastic and only replaceable, never repaired.** So there is no `repaired`
  verb. A damaged disc does not get better; it stays flagged until it leaves the bag.
- **A fresh disc of the same mold flies differently from a beat one.** So a replacement
  deserves its own identity and its own empty history, not the old disc's history.
- The end-state of a lost/worn disc is **replacement** (add a new copy), not restore.
  `restore` stays available for the rare "found my lost disc" case but is not the focus.

## Data model

Add one field to `UserData` (`discbag/inventory.py`):

```python
damaged: bool = False
```

`damaged` is **orthogonal** to `status`:

- An **active** disc can be `damaged=True` (worn but still carried, still counted in
  recommendations).
- An archived disc (`broken`, `lost`) can also carry `damaged=True` — the truth is
  preserved.

Lost / broken reuse the existing `status`, `status_reason`, `status_date` fields. No other
schema change. `from_dict` already ignores unknown keys and fills defaults, so old
inventory files load unchanged (a disc with no `damaged` key defaults to `False`).

New inventory method:

```python
def set_damaged(self, name, value, reason=None, when=None):
    """Set the damaged flag on the targeted disc(s). Orthogonal to status —
    does not archive. Returns count updated."""
```

It sets `damaged`, and when `value` is True records `status_reason`/`status_date` if a
reason is given (so `history` can show why). Follows the existing `_mutate` pattern and
targets an `OwnedDisc` (one copy) or a mold-name string (all copies), like the other
setters.

## Commands

All are thin wrappers over `set_status` / `set_damaged`, resolving the target the same way
`remove` does (active discs, disambiguating when you own two of the same mold).

### `discbag lost <disc> [--reason "..."]`
Archive with `status=lost`. Leaves the active bag, keeps history. (Same code path as
`remove --status lost`, just discoverable.)

### `discbag damaged <disc> [--reason "..."]`
Set `damaged=True`. **Stays active and in the bag.** Still counted in recommendations,
now visibly flagged.

### `discbag damaged <disc> --retire [--reason "..."]`
Set `damaged=True` **and** archive with `status=broken`. For a disc worn beyond use.

### `discbag damaged <disc> --unset`
Clear the flag. Mistake-correction only, mirroring `favorite --unset` — **not** "repair."
Operates on the flag; does not un-archive (use `restore` for that, rarely).

`--retire` and `--unset` are mutually exclusive.

### `discbag replace <disc> [--status retired|broken|lost] [--reason "..."] [--plastic P] [--weight W] [--color C]`
Two actions in one command:

1. **Archive the old copy** with `--status` (default `retired`), preserving its full
   history — same as `remove`.
2. **Add a new copy** of the same brand + mold with a fresh id and empty history.

**Carryover split (the one judgment call):**

- **Identity persists** (the replacement fills the same slot): plastic, weight, color,
  role, favorite, in-bag, tags. `--plastic/--weight/--color` override the carried-over
  values for a different run/rebuy.
- **Life story resets**: use history (`use_count`, `use_dates`, `last_used`), condition,
  notes, and `damaged` all start clean; `status=active`.

Prints both actions, e.g.:

```
Replaced Innova Firebird.
  Old copy archived (Retired), history kept.
  New copy added — fresh history.
```

## Display

Plain text, no emoji, degrades cleanly under `NO_COLOR`/pipe (matches existing style).

- **`list`** — an active-but-damaged disc shows `damaged` in its descriptor line
  (`discbag/cli.py` ~line 269, alongside condition/status bits).
- **`show`** — add a `Damaged` line when the flag is set.
- **`history`** — note the damaged flag alongside the existing status/reason output.
- Dashboard: no new section required; damaged actives still appear in normal counts. (A
  future "worn discs" nudge is out of scope.)

## Help / discoverability

- Register `lost`, `damaged`, `replace` as subparsers grouped with the other
  organization/lifecycle commands (near `remove`/`restore`/`history` in the grouped
  `--help`).
- No change to the `_ARCHIVE_STATUSES` list: `damaged` is a flag, not a status;
  `damaged --retire` archives with the existing `broken` status.

## Testing

**`tests/test_inventory.py`**
- `set_damaged` sets/clears the flag without changing `status` or removing the disc from
  `list_discs()` (active-but-damaged still listed).
- `lost` → `status=lost`, excluded from active `list_discs()`, present in `all_discs()`.
- `damaged --retire` path → `damaged=True` and `status=broken`.
- Old inventory file without a `damaged` key loads with `damaged=False`.
- `replace`: old copy archived with chosen status and history intact; new copy has a
  distinct id, empty history, `status=active`, `damaged=False`, and carried-over
  identity fields; overrides apply.

**`tests/test_cli.py`**
- Each of `lost`, `damaged`, `damaged --retire`, `damaged --unset`, `replace` end to end,
  including `--reason`, `--status`, override flags.
- Disambiguation when two copies of a mold are owned (targets one copy).
- `list`/`show` surface the `damaged` marker for an active flagged disc.
- `--retire` + `--unset` together is rejected.

## Docs

Short lifecycle blurb in `README.md` and a `CHANGELOG.md` entry covering `lost`,
`damaged` (with `--retire`/`--unset`), and `replace`.

## Out of scope (YAGNI)

- No `repaired` verb (discs aren't repaired).
- No damaged-disc nudges/suggestions on the dashboard.
- No change to `restore`, `delete`, `remove` behavior.
- No structured `condition` overhaul — it stays free-text.
