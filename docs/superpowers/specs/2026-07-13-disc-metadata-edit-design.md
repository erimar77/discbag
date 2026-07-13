# Disc metadata editing (`discbag edit`) — design

**Date:** 2026-07-13
**Status:** Approved, pre-implementation

## Purpose

Let a physical disc's inventory metadata become more accurate over time without
touching its career or history. Adding a disc captures plastic, color, weight, etc.,
but until now those were fixed at `add` time with no way to correct them. Primary
motivating case: two copies of the same mold (a clear Champion Roadrunner and an
orange Star Roadrunner) that were added without their distinguishing metadata.

This is **metadata correction, not lifecycle modification**. It is deliberately *not*
a general "edit anything" command:

- `role`, `favorite`, `tag`/`untag`, and `flight` keep their own dedicated commands
  and do not move into `edit`.
- Lifecycle (`remove`/`lost`/`damaged`/`replace`/`restore`) is untouched.

## Hard guarantee: no history events

Editing metadata is not part of a disc's career, so `edit` **MUST NOT** create any
timeline/history event. Concretely, `update_metadata()` never calls `log_event`. All
existing history, usage log, favorite flag, tags, lifecycle status, and the event log
are preserved exactly; only the requested fields change.

## Command shape

Flags mirror `add`, and any subset may be set in a single invocation:

```
discbag edit <name…> [--manufacturer M] [--mold M] [--plastic P] \
                     [--weight N] [--color C] [--condition C] [--notes N]

discbag edit --id <id> [same flags]      # power-user / scripting: target one copy
```

Example (the Roadrunner case):

```
discbag edit roadrunner --plastic Champion --weight 171 --color Orange
```

Rules:

- **At least one field flag is required.** With none, print a clear error and make no
  changes.
- Text fields accept `""` to clear a wrong value. `--weight` takes an integer.
- **`--location` is intentionally omitted** in this first iteration to keep the command
  focused on the disc's physical identity. Adding it later is a purely additive change.

## Editable fields

Two categories:

**Pure metadata** (on `UserData`, simply overwritten):
`plastic`, `weight`, `color`, `condition`, `notes`.

**Identity** (on `OwnedDisc`): `manufacturer` (stored as `brand`) and `mold`. The
manufacturer+mold pair *is* the disc's identity; the cached flight numbers
(speed/glide/turn/fade) are derived from it, not independent data. So changing either
one re-derives the cached snapshot (see below).

## Cached flight data follows the corrected identity

When `edit` changes `manufacturer` and/or `mold`, the cached flight snapshot is
refreshed so the cache always represents "what we currently believe this disc is." This
also repairs any fuzzy/fallback stats that may have been stored when the disc was first
added under a typo.

- The refresh reuses the **same resolver `add` uses** (`db.find_disc`) and the same
  `Disc.from_db_record` construction — one code path responsible for populating cached
  flight data, no duplication.
- **Match found:** replace `cached` with the canonical values and report it
  (`Matched: Innova Roadrunner (9/4/-4/3)`).
- **No match:** still apply the identity string edit, leave `cached` unchanged, and warn
  that the lookup could not be completed (mirrors `add`'s unknown-mold behavior).

**The inventory layer owns this.** `update_metadata()` detects whether the identity
changed and, if so, performs the lookup and cache refresh **internally**. The CLI simply
calls `update_metadata(...)` and passes `db_discs`; it does not reason about whether the
identity changed. This keeps all metadata-mutation logic in one place and prevents future
callers from forgetting to refresh the cache after an identity change.

## Targeting and disambiguation

Reuses the existing `_resolve` flow, consistent with every other command:

- **Unique match:** edit it in place.
- **Ambiguous name:** show the existing **interactive numbered prompt** (the default UX),
  and error out non-interactively — never guess which physical copy was meant.
- `include_archived=True`, so a typo on an archived disc can also be corrected.
- **`--id <id>`** targets one copy directly, skipping the prompt, for scripting and
  deterministic behavior. When `--id` is given, the positional name is optional.

### Prompt formatting — reuse, don't duplicate

The ambiguity prompt reuses the existing shared `_disc_descriptor`, which already renders
all available distinguishing metadata (plastic, weight, color, condition, location,
date-added, status, damaged, notes), omitting whatever is missing. This already is the
single reusable short-description formatter, so no new formatter is introduced and no
per-command formatting duplication is created.

## id discovery

ids stay hidden by default. To make `--id` usable without exposing ids everywhere, add:

```
discbag list --ids
```

which prints each copy's id. Most users never need this — the interactive prompt remains
the default. Power users and scripts opt in explicitly, then target with
`discbag edit --id <id> ...`.

## Inventory API

```python
Inventory.update_metadata(
    disc,                 # a single resolved OwnedDisc
    *,
    brand=None, mold=None,           # identity (None = leave unchanged)
    plastic=None, weight=None,       # metadata (None = leave unchanged)
    color=None, condition=None, notes=None,
    db_discs=None,        # DB records, for the internal cache refresh
)
```

- `None` for any field means "leave unchanged"; a provided value (including `""` for text)
  is applied.
- Operates on the one resolved `OwnedDisc`, saves once, and **logs no event**.
- Detects an identity change internally; if the identity changed and `db_discs` is
  provided, performs the `db.find_disc` lookup and refreshes `cached`.
- Returns the identity-lookup outcome (e.g. matched record / no-match / no identity
  change) so the CLI can report `Matched: …` or the no-match warning.

## Testing (TDD)

**Inventory (`update_metadata`):**

- Each field updates as requested.
- **The events list length is unchanged after an edit** — the core no-history guarantee.
- History, usage log, favorite, tags, and lifecycle status are all preserved.
- Changing manufacturer/mold refreshes `cached` from the DB (canonical values).
- No DB match: `cached` is left as-is, and the identity strings are still applied.
- `None` fields leave their values untouched.

**CLI (`edit`, `list --ids`):**

- Single match applies the edit in place.
- Ambiguous name, non-interactive: errors out (no guess).
- `--id` targets a copy directly.
- No field flags: clear error, no changes.
- `list --ids` prints copy ids.
