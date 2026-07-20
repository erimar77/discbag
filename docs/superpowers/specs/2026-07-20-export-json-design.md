# `discbag export` — Portable JSON Snapshot (schema v1.0)

**Date:** 2026-07-20
**Status:** Approved design, not yet implemented
**Scope:** The `discbag` CLI only. The consuming dashboard is a separate project with its own spec.

---

## Purpose

Add a single command, `discbag export`, that emits a complete, deterministic, portable JSON
snapshot of the user's collection and every analysis `discbag` already computes.

This snapshot is the **public contract** between `discbag` and `discbag-dashboard`. The dashboard
consumes it and never reads `~/.discbag` or imports `discbag` internals. The CLI knows nothing
about how the dashboard presents anything.

> `discbag` computes knowledge. The dashboard visualizes knowledge.

### The governing rule

The export layer is intentionally boring:

> **It serializes existing discbag knowledge. It does not create new knowledge.**

If `export.py` decides what is *true* rather than merely serializing an existing result, that logic
belongs elsewhere. A threshold, comparison, classification, or scoring rule appearing in
`export.py` is a defect, not a feature.

### The layering rule

> The engine returns meaning. The CLI renders prose. The export serializes structure.

---

## Non-goals

Explicitly out of scope for this project:

- **New per-disc analysis.** Wind suitability, effective distance ranges, shot shapes, and
  strengths/weaknesses do not exist in the engine. They are not invented here. See
  *Deferred work*.
- **A relationship taxonomy.** `similar`, `backup`, `more_stable`, `complement` do not exist in
  the engine. They are not invented here. See *Deferred work*.
- **The shot picker (`choose`).** Its inputs are continuous and cannot be honestly enumerated.
- **Rotation.** `--rotate` is RNG-driven and would break reproducibility.
- **Redaction.** See *Privacy*.
- **Relationship filtering, truncation, or top-N policies.** Any such policy belongs in the
  engine, applied consistently everywhere — never in the export.

---

## Architecture

### New module: `discbag/export.py`

A **leaf module** exposing one public function:

```python
def build_export(
    inventory,
    profile,
    catalog,
    *,
    analysis_date,
    generated_at,
) -> dict:
```

Pure: takes already-loaded state, returns a plain JSON-safe `dict`. No file I/O, no printing.

**Both time values are injected. `export.py` must never call `datetime.now()`.**

- `analysis_date` — drives date-sensitive analysis (maturity, usage recency, neglect).
- `generated_at` — provenance metadata only; never influences analysis.

This split is what makes `build_export()` deterministic and lets tests assert byte-identical
output.

### Import boundary

- `export.py` **may** import: `roles`, `analysis`, `recommend`, `maturity`, `player`, `db`,
  `inventory`, `history`, plus the standard library.
- Those modules **must never** import `export`.

Mechanically enforced by test (see *Testing*, group 3).

`export.py` may reshape engine results into JSON-safe structures and rename fields for schema
clarity. It may not interpret them.

### CLI: `discbag export`

```bash
discbag export [--output PATH] [--indent N]
```

The command produces JSON by definition, so there is **no `--json` flag** — a flag that is always
required carries no information.

The CLI layer is responsible for:

1. loading inventory, profile, and catalog
2. determining the current analysis date
3. generating the UTC `generated_at` timestamp
4. calling `build_export()`
5. serializing JSON (`sort_keys=True`, fixed default indent)
6. writing to stdout or `--output`

---

## Prerequisite refactor: structured comparison verdict

`analysis.compare_verdict()` currently conflates two responsibilities: determining the comparison
result, and formatting it for a terminal. It returns one pre-formatted blob with embedded
newlines and literal English headings (`Bottom line`, `Overlap:`, `Key difference:`,
`How to use them:`).

That must be separated **before** the result enters a public schema — otherwise the dashboard has
to string-parse CLI prose, and any future wording change silently breaks it.

### Engine returns meaning

```python
@dataclass(frozen=True)
class CompareVerdict:
    overlap_text: str | None
    key_difference: str | None
    how_to_use: str | None
    degraded_note: str | None
```

Field names should follow the real semantic sections currently produced; the shape above is
illustrative, not binding. The engine result carries plain semantic content — no ANSI codes, no
terminal-only indentation, no decorative headings, no final string assembly.

Existing `None` semantics are preserved exactly: `None` for fewer than two discs, `None` when
manufacturer flight data is incomplete, and the degraded one-liner for three or more discs.

### CLI renders prose

```python
def render_compare_verdict(verdict: CompareVerdict) -> str: ...
```

**The rendered CLI output must remain byte-identical.** Existing comparison tests are retained or
adapted to prove it.

### Export serializes structure

The export emits the dataclass fields directly. It never parses section labels.

This refactor is narrowly scoped to preserving existing comparison semantics and output. No new
classifications are introduced while doing it.

---

## Schema v1.0

### Top level

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-07-20T14:32:11Z",
  "discbag_version": "0.1.0",
  "analysis_defaults": { "goal": "coverage", "bag_size": null, "rotate": false },
  "reports_included": ["coverage", "gaps", "overlap_groups", "pairwise_comparisons",
                       "goal_bags", "scenario_bags", "maturity", "next_purchase", "exclusions"],
  "profile": {},
  "catalog": {},
  "inventory": [],
  "analysis": {}
}
```

`analysis_defaults` **mirrors the CLI exactly**: goal `coverage` (`cli.py:1930`), and `bag_size`
`null` because `--size` has no default (`cli.py:1909`). A `null` bag size means *no explicit size
override was applied* — the dashboard must not read it as a numeric default.

`analysis_defaults` is limited to defaults that materially affect the exported reports. It is not
a dump of internal configuration.

`reports_included` lets the dashboard detect which sections a snapshot has and degrade gracefully
on older or partial exports. It uses the exact `analysis` key names.

All top-level keys are always present, including for degenerate inputs.

### Identifiers

**`inventory_id`** — the existing 32-character hex `id` already on every inventory record (the
value `list --ids` surfaces). This is purely a public-schema field name for an identifier that
already exists. No migration or ID generation is required.

**`catalog_id`** — catalog records carry no identifier, so one is derived. Ownership of catalog
identity belongs with the catalog, so this lives in **`db.py`**, not `export.py`:

```python
def catalog_id(record) -> str:   # "gateway-wizard"
```

Derived from normalized `brand + name`.

> **Limitation:** Catalog IDs are stable only while the upstream brand and mold name remain
> unchanged. A catalog rename may change the derived ID in schema v1.

No aliases, rename tracking, or persistent catalog-ID storage in this project.

### `catalog` — deduplicated portable summaries

Portability is a hard requirement: an export must visualize on a machine with no `discbag`
installation and no `discs.json`. Recommendations reference discs the user does not own, so those
records must travel inside the snapshot.

A single top-level deduplicated map, keyed by `catalog_id`:

```json
{
  "catalog": {
    "gateway-wizard": {
      "catalog_id": "gateway-wizard",
      "name": "Wizard",
      "brand": "Gateway",
      "category": "Putter",
      "stability": "Stable",
      "flight": { "speed": 2, "glide": 3, "turn": 0, "fade": 2 }
    }
  }
}
```

This is a **deliberate portable summary** defined as part of the public schema — not a blind dump
of the internal catalog object.

It contains **only** catalog records actually referenced by the snapshot, never all 1,189 entries.

### `inventory[]`

The nested shape preserves the engine's own separation of concerns — raw manufacturer data, user
metadata, and engine conclusions stay visibly distinct:

```json
{
  "inventory_id": "1683a68e94dd4d1e913fb05f0fbacf32",
  "catalog_id": "gateway-wizard",
  "mold": "Wizard",
  "manufacturer": { "brand": "Gateway", "category": "Putter", "stability": "Stable",
                    "flight": { "speed": 2, "glide": 3, "turn": 0, "fade": 2 } },
  "user": { "plastic": "Firm", "weight": 175, "color": "red", "condition": "good",
            "status": "active", "in_bag": true, "favorite": false, "tags": [],
            "notes": "...", "personal_flight": null, "role": null },
  "computed": {
    "flight_known": true,
    "effective_flight": { "speed": 2, "glide": 3, "turn": 0, "fade": 2 },
    "behaves_flight":   { "speed": 2, "glide": 3, "turn": 0, "fade": 2 },
    "stability": -0.5,
    "primary_role": "Putting",
    "fit_score": 1.42,
    "required_power": 1.8
  },
  "history_summary": { "rounds": 12, "practices": 4, "last_used": "2026-07-07",
                       "acquired": "2025-03-11" }
}
```

**Only fields backed by current engine output are included.** Where a concept does not apply or
cannot be computed, emit `null` — never a substitute value.

Two `computed` fields require care:

- **`fit_score` is a distance: lower is better.** It is an unbounded weighted distance from a
  role's ideal (`roles.py:186`), always relative to a specific role — here, the disc's
  `primary_role`. The schema documentation must state the direction explicitly, or consumers will
  build inverted visualizations.
- **Both flight values are carried, because the engine uses both.** `effective_flight` is
  personal-numbers-or-manufacturer and drives roles and fit scoring. `behaves_flight` is
  personal-else-*power-adjusted-for-this-player* and drives overlap, choose, and practice.
  Exporting only one would misrepresent whichever reports depend on the other.

### `analysis`

```json
{
  "analysis": {
    "coverage": [],
    "gaps": [],
    "overlap_groups": [],
    "pairwise_comparisons": [],
    "goal_bags": {},
    "scenario_bags": {},
    "scenario_aliases": {},
    "maturity": null,
    "next_purchase": null,
    "exclusions": []
  }
}
```

Each section serializes the corresponding engine result, carrying the engine's own reasoning text
(role priorities and their reasons, `why_qualifies`, coverage/missing reasons, next-purchase
rationale). Reasoning text is never manufactured in `export.py`.

#### Goal bags

All five goals at the default size: `coverage`, `development`, `confidence`, `tournament`, `fun`.

#### Scenario bags and aliases

The engine defines exactly five situations (`roles.py:133`), but only **three are distinct** —
`windy`/`rain` share a role set, as do `minimal`/`travel`. Canonical reports are stored once and
aliases exported separately, avoiding duplicated payloads and keeping canonical behavior explicit
if an alias later becomes distinct:

```json
{
  "scenario_bags":    { "windy": {}, "minimal": {}, "woods": {} },
  "scenario_aliases": { "rain": "windy", "travel": "minimal" }
}
```

There is no `technical` or `open` scenario. The dashboard may present all five names, resolving
them through the alias map.

#### `overlap_groups`

The existing thresholded clusters from `overlap()`, preserving current semantics and membership.

`overlap()` returns **groups of discs only** — it produces no score and no reasoning text.
Therefore neither is exported. Nothing is manufactured to fill those slots.

```json
{
  "overlap_groups": [
    { "group_id": "overlap-<deterministic>",
      "inventory_ids": ["0b5f31d6...", "1683a68e..."] }
  ]
}
```

`group_id` is derived deterministically from the sorted member IDs. It is an **export-local
structural identifier for rendering, not an engine conclusion**, and is documented as such.

#### `pairwise_comparisons`

For every eligible unordered pair of active owned discs, the existing public
`compare_verdict()` is called and its structured result serialized:

```json
{
  "pairwise_comparisons": [
    { "left_inventory_id":  "0b5f31d6...",
      "right_inventory_id": "1683a68e...",
      "verdict": { "overlap_text": "...", "key_difference": "...",
                   "how_to_use": "...", "degraded_note": null } }
  ]
}
```

**The `compare()` table is deliberately omitted.** It returns presentation, not facts — display
headers, `"—"` sentinel strings, and stability as an English word (`analysis.py:91`) — and every
value in it (flight numbers, stability, role) is already present in the disc's `inventory` record.
Exporting it would put terminal formatting into a contract that forbids presentation, and
duplicate data the snapshot already carries.

`degraded_note` is always `null` here, since pairwise comparison is always exactly two discs. The
field is retained so the shape matches the engine's dataclass.

Deterministic endpoint ordering: `left_inventory_id = min(a, b)`, `right_inventory_id = max(a, b)`.
Sorted by `left_inventory_id`, then `right_inventory_id`.

`export.py` does **not** infer a relationship type from comparison output. It may rename fields for
schema clarity; it may not decide that one disc is a backup, complement, or more-stable
counterpart.

#### `exclusions`

Structured and machine-readable, never a bare count or prose message:

```json
{
  "exclusions": [
    { "inventory_id": "1683a68e...",
      "reason": "incomplete_flight_data",
      "excluded_from": ["coverage", "goal_bags", "scenario_bags",
                        "overlap_groups", "pairwise_comparisons"] }
  ]
}
```

Reason codes are stable identifiers; the dashboard derives human-readable text from them. Current
codes: `incomplete_flight_data`, `inactive_status`.

> **A disc is never claimed to be excluded from a report unless the engine actually excludes it
> from that report.** Each entry's `excluded_from` list is verified against real engine behavior.

---

## Eligibility and visibility

The engine's existing eligibility rules are applied unchanged; the export mirrors them and records
the consequences.

**Incomplete flight data** — the subject of the most recent round of engine hardening. Such discs:

- **remain present in `inventory`** with `computed.flight_known: false` and unavailable computed
  fields `null`
- are absent from analyses that already require complete flight data
- are never forced through comparison functions that do not support them
- appear in `exclusions` with reason `incomplete_flight_data`

A dashboard that silently disappears discs the user owns would be lying. They stay visible; only
their *analysis participation* is limited.

**Inactive discs** (`lost`, `sold`, `retired`) — remain present in `inventory` with their actual
status, excluded from active-collection analysis exactly as far as the engine already excludes
them, recorded with reason `inactive_status`. Where different statuses currently behave
differently, that distinction is preserved rather than artificially grouped.

---

## Degenerate inputs

The export must remain **structurally valid and complete** for: empty inventory, absent profile, a
single owned disc, incomplete flight data, and inactive-only inventory.

No required top-level key is ever omitted, and no partially populated export is ever produced.

The `null` vs. empty distinction is semantic:

- **Empty array/object** — the report ran successfully and had no results
  (`"pairwise_comparisons": []` because only one disc exists).
- **`null`** — the concept exists but could not be calculated (`"profile": null` when unset;
  `"maturity": null` if that matches engine behavior for insufficient data).

---

## Testing (`tests/test_export.py`)

### 1. Schema snapshot

Two distinct assertions, so structural changes are distinguishable from formatting changes:

- the returned **dictionary** against a committed structured snapshot
- **serialized JSON determinism** with fixed inputs, `sort_keys=True`, and a fixed indent

Raw pretty-printed bytes are never the only schema test. Any intentional golden-file update
requires an explicit test-fixture update **in the same commit**.

### 2. Determinism

Two calls with identical inputs produce byte-identical output.

`sort_keys=True` stabilizes object keys only — **not array order**. Every list whose order carries
no semantic meaning is explicitly sorted, with its sort key documented:

| Collection | Sort key |
|---|---|
| `inventory` | `inventory_id` |
| `pairwise_comparisons` | `left_inventory_id`, then `right_inventory_id` |
| `overlap_groups` | sorted member IDs |
| `exclusions` | `inventory_id`, then `reason` |
| `next_purchase` suggestions | engine rank, stable secondary key |
| bag entries | **engine recommendation order — never alphabetized** |

Where order is meaningful, engine ranking is preserved.

### 3. Leaf boundary

Enforced in both directions:

- no engine module imports `discbag.export`
- `discbag.export` imports only from the approved allowlist plus the standard library

Implemented via **AST or module-import inspection**, not brittle source-string search.

### 4. Portability

For every `catalog_id` referenced anywhere outside an owned inventory record, a corresponding
entry exists in the top-level `catalog` map. This mechanically enforces the emailability
guarantee across *all* external references, not just recommendations.

### 5. Edge cases

Explicit assertions that:

- incomplete-flight discs remain visible in `inventory`
- excluded discs carry structured reasons
- inactive discs remain visible
- empty inventory produces a complete schema
- missing profile produces a complete schema
- one disc produces an empty `pairwise_comparisons` list
- **no report contains a dangling `inventory_id` or `catalog_id` reference**

### 6. Comparison refactor regression

CLI `compare` output remains byte-identical after the `CompareVerdict` refactor.

---

## Scaling

Pairwise comparison generation and serialized `pairwise_comparisons` count **may grow
quadratically** with the number of eligible owned discs. `overlap_groups` does not — `overlap()`
returns only meaningful thresholded clusters, so its output is bounded by inventory size.

This is acceptable for v1 and documented as a known structural characteristic. No measurement
claim about file size at a given disc count is made here without measuring.

No threshold, truncation, top-N filtering, or pair suppression is added in `export.py`. Any future
filtering policy belongs in the engine, defined once and surfaced consistently.

---

## Privacy

An export may contain profile details, notes, and complete usage history. Portability means those
travel with the file.

**No redaction in v1.** A clear note is added to the command help stating that an export may
contain personal profile details, notes, and complete usage history. No interactive warning or
confirmation.

---

## Deferred work

Each item below is a deliberate future engine feature, not export work. The path for each is:
define semantics → implement in the core engine → expose through a CLI surface → add tests →
add to a later export schema revision.

- **Per-disc shot-picker facts** — wind suitability, effective distance ranges, shot shapes,
  strengths, weaknesses.
- **A typed relationship graph** — `similar`, `backup`, `more_stable`, `complement`. Until then
  the dashboard may visualize overlap clusters and comparison results, but must not label them
  with relationship concepts `discbag` has not actually concluded.
- **An interactive shot picker**, built on exported facts rather than precomputed queries.

Prefer backward-compatible optional field additions when practical. **Never silently change the
semantics of an existing field** — that requires a schema version bump.

---

## Open item for spec review

The `compare()` table is omitted from `pairwise_comparisons` (rationale above: it is presentation,
and its data is already in `inventory`). The approving message included a `"comparison": {}` key in
its illustrative JSON without addressing the omission argument. **Confirm the table should be
omitted**, or state what it should carry if not.
