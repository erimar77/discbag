# `discbag compare` redesign — design

**Date:** 2026-07-13
**Status:** Approved, pre-implementation

## Purpose

Today `discbag compare <a> <b>` prints a bare side-by-side of Speed/Glide/Turn/Fade
plus a Role row, using stock manufacturer numbers. For an intermediate player
comparing two similar discs (the motivating case: `compare wave wraith`, two speed-11
distance drivers), that table hides the thing you actually compare them for — how their
flights differ in practice — and leaves you to translate `-2/2` vs `-1/3` yourself.

This redesign keeps the command surface and the stock-number table, adds a derived
**Stability** row, and appends a rule-derived **bottom line** that describes overlap,
the key difference, and how to use each disc — in relative, honest wording. When both
discs are owned, a light ownership footer reports real usage.

Non-goal: no "how it flies for me" / `personal_flight` input. The player does not
reliably self-assess per-disc flight and would attribute deviations to their own form,
so a "for-you" column is dropped entirely (the player is an intermediate who does not
reliably self-assess per-disc flight).

## Command surface

Unchanged: `discbag compare <name…>` — two or more discs, each resolved from the bag or
the database (existing `_resolve_disc`). We enrich the output only.

## Part 1 — richer table (stock numbers)

Add a **Stability** row to the existing table; keep Role; drop nothing else. No
"for-you" column. No absolute distance estimate (false precision, and identical for two
same-speed discs).

```
                 Wave      Wraith
Speed              11          11
Glide               5           5
Turn               -2          -1
Fade                2           3
Stability      neutral   overstable
Role        Dist driver  Dist driver
```

- Stability is derived as **turn + fade**, mapped to a word by the existing
  `_stability_word` thresholds (Wave `0` → neutral, Wraith `2` → overstable).
- **Stability is broad-category shorthand, not absolute truth.** turn + fade ignores
  speed, plastic, wear, and where in the flight the turn and fade actually happen. The
  table shows the category as a quick label; the bottom line (below) never leans on the
  absolute label — it speaks in relative terms.

## Part 2 — bottom line (exactly two discs)

Rule-derived prose, rendered only when exactly two discs are compared. Three labeled
sections, in this order and tone (target wording):

```
Bottom line

Overlap:
These occupy the same broad distance-driver slot, but their flights are
meaningfully different.

Key difference:
The Wave has more high-speed turn and a gentler finish. The Wraith resists
turning more and fades harder.

How to use them:
Reach for the Wave when you want easier distance and more movement before the
fade. Reach for the Wraith when you want a stronger finish or more resistance to
wind. Expect the Wraith to finish left more strongly than the Wave. That
difference is built into the discs, although an unusually early fade can still
reflect the throw.
```

### Overlap (neutral framing)

Labeled **"Overlap:"** — not "Do you need both?" Overlap is described, not judged;
owning similar discs is a legitimate choice for a hobby. Computed from flight similarity
plus shared primary role: same slot with similar flights → high overlap; same slot with
meaningfully different flights → "same slot, but meaningfully different"; different roles
→ distinct/complementary.

### Key difference (relative wording)

Describe how the two discs differ across the axes that meaningfully differ, always as a
**relative** comparison between the two discs — never an absolute declaration:

- "The Wraith is **more** overstable **than** the Wave," not "the Wraith is overstable."
- turn → high-speed turn / movement before the fade; fade → how hard it finishes;
  speed → distance ceiling. Mention each axis that differs (Wave vs Wraith differ on both
  turn and fade, so both are named), not a single forced axis.

### How to use them

When to reach for each, phrased by shot intent and wind, in relative terms. Closes with
the softened expectation note when the discs differ in fade/stability: state that the
more-overstable disc finishes left more strongly and that this is built into the discs,
**while acknowledging an unusually early fade can still reflect the throw** — teaches
without claiming every left finish is automatically a correct throw.

## Ownership footer (only when both discs are owned)

When both compared discs are in the bag, append one light line from real, recorded data —
usage counts and favorite flag — so the player sees which they actually throw. No invented
"confidence" metric.

```
You've thrown the Wraith 12 rounds, the Wave 2. The Wave is a favorite.
```

Skipped entirely when either disc is database-only (a copy you don't own has no usage).

## Three or more discs

The table (including Stability) renders for all discs, as today. The three-part bottom
line is **not** produced — it only makes sense pairwise. Instead, a short degraded note:
flag the most-similar pair as the highest overlap and name the most-distinct disc. The
ownership footer still applies if every compared disc is owned.

## Structure

- Extend `analysis.compare(discs)` to include the Stability row.
- Add a pure, testable verdict builder in `analysis` (e.g.
  `analysis.compare_verdict(discs)`) returning the bottom-line text (Overlap / Key
  difference / How to use them), and the degraded note for 3+.
- `cmd_compare` assembles: render table, then verdict, then — if both discs are owned —
  the ownership footer (rendered from `OwnedDisc.user` usage/favorite).
- Reuse `roles.primary_role` and the existing overlap/similarity logic for the overlap
  determination rather than a new similarity metric.
- Keep logic in `analysis`/`roles`, rendering in `cli` — matches the current split.

## Refactor: consolidate the stability helper (narrow, behavior-preserving)

While touching this code, remove the duplication rather than adding a fourth copy:

- `braille._stability`, `chart.stability`, and `recommend._stability` are byte-identical
  (`float(disc.turn) + float(disc.fade)`). Replace all three with a single shared
  helper (e.g. `stability_number(disc)` in a shared module such as `roles`), and have
  `cli._stability_word` live alongside it or import from there. The new compare code uses
  the same shared helper.
- **Leave `OwnedDisc.stability` untouched** — it returns the manufacturer's stability
  *string* (`cached.stability`), a different concept from the turn+fade number.
- Preserve existing behavior exactly; this is a de-duplication, not a semantics change.
  Existing tests for chart/braille/recommend must stay green.

## Testing

- `analysis.compare` includes a Stability row with the correct derived word per disc.
- Overlap classification: two same-role, similar-flight discs → high overlap wording;
  same-role, meaningfully-different flights → "same slot but different"; different roles
  → distinct/complementary.
- Key difference names each axis that meaningfully differs, in relative comparative
  wording; asserts no absolute "is overstable"-style declaration for the two-disc verdict.
- How-to-use includes the softened early-fade caveat when the discs differ in
  fade/stability.
- Ownership footer present only when both discs are owned; uses real usage/favorite;
  absent when either disc is DB-only.
- 3+ discs: table renders for all; no three-part verdict; degraded note names most-similar
  pair and most-distinct disc.
- Refactor: one shared stability-number helper; `chart`/`braille`/`recommend` behavior
  unchanged (existing tests pass); `OwnedDisc.stability` still returns the manufacturer
  string.
