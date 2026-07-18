# Collection Maturity — design

**Date:** 2026-07-14
**Status:** Approved, pre-implementation

## Purpose

Most bag tools answer "what should I buy next?" `discbag` already does that with `recommend`.
Collection Maturity answers the more valuable, rarely-asked question: **"Do I actually need
anything — or is my collection already mature, and my gains now come from throwing what I own?"**

It is a **coaching** feature, not a recommendation engine. It tells a player where their
collection sits today — still worth exploring, or settled enough that another disc is unlikely to
help — and explains *why* in plain, observable signals.

It answers "where is your collection today, and why?" — a single read of the present. Tracking
*when* a player moved between phases is deliberately **out of scope** (see Deferred).

## Core principles

- **Qualitative, never numeric.** No score, no percentage, no star rating. A rating reads as
  precision the estimate can't honestly carry. The output is a **phase label** plus an explicit
  **why** list of `✓`/`•` signals, so every conclusion is explainable rather than mathematical.
- **Only grounded signals.** Every statement derives from data discbag actually has (coverage,
  usage, favorites, dates, flight numbers, brand). Nothing is invented. Where the source proposal
  asked for signals discbag can't back (plastic tier, rim width), those are excluded, not faked.
- **Read-only, no new persistence.** The command computes from current state each run.

## Command

```
discbag maturity
```

New command in the **Analysis** group. Read-only. No flags in v1.

## The model — two steps

### Step 1: the coverage gate

Reuse `roles.assess(bag, profile)`, which already returns each role's coverage and a practical
**priority** (`Satisfied` / `High` / `Medium` / `Low`).

A **meaningful gap** is a role that is:
- **missing** (`not covered`), **and**
- **not optional** (`not role.optional`), **and**
- **High or Medium priority** for this player.

Missing *Low*-priority roles do **not** count — the engine already judges them low-value for the
player right now — and optional roles never count. A useful consequence: as a player's distance
grows and a Low role climbs to High, the gate can legitimately re-open. Maturity evolves with the
player, with no change to this feature.

- **Any meaningful gap → phase `Discovery`.** Encourage it; the "why" lists the gaps and points to
  `recommend`. (A nearly-empty bag lands here naturally, since most roles are missing.)

### Step 2: behavior (only once the gate is passed)

With coverage in place, maturity turns on whether the collection actually **supports the player's
game** — proven by how they throw, not by whether they've resisted curiosity. Two signals are
**required** for `Developed`; the rest are **supporting** context that enriches the "why" but never
flips the phase.

**Required** (both must hold for `Developed`):

1. **Sufficient, real usage** — enough recorded throws to judge (`total recorded uses ≥ MIN_USES`)
   **and** thrown recently (`last activity within ACTIVE_WINDOW`). Without it we can't claim
   anything is settled, so the phase is at most `Developing`.
2. **Demonstrably settled usage** — a small core carries most throws: the fewest active discs whose
   combined `use_count` reaches `CONCENTRATION` of all recorded uses is at most `CORE_FRACTION` of
   the active bag. This is the real test of "the player has found what works."

**Supporting** (shown in the "why" for context; they color the picture but never change the phase):

- **Not chasing new molds** — distinct molds whose **first** acquisition (earliest `date_added`
  across all copies of that mold, active or archived) falls within `RECENT_WINDOW`, counted against
  `MAX_RECENT_NEW_MOLDS`. A backup, same-mold `replace`, plastic/weight variant, cycling a fresh
  Roc, or rebuying a mold you once owned introduces **no** new mold and never counts. When a mature
  player *does* add a new mold or two out of curiosity, this surfaces as a `•` note ("a little
  experimenting") — it does **not** demote them, because their settled usage already proves the
  collection supports their game. And there's a natural backstop: if new molds ever genuinely take
  over their throwing, the required *settled usage* signal drops on its own.
- **Established favorites** — `favorites ≥ MIN_FAVORITES`. Marking favorites is a manual action; its
  absence proves nothing, so it only ever supports.

**Phase resolution:**
- **`Developed`** — no meaningful gaps **and** both required signals (sufficient usage, settled
  usage) met. Message: *"Another disc is unlikely to improve your game right now — your gains are in
  reps."*
- **`Developing`** — no meaningful gaps, but usage is still spread across the bag, or there's not
  enough usage history to judge. A freshly-stocked full-coverage bag with no rounds logged lands
  here, never `Developed`.

Phase labels are **Discovery → Developing → Developed** (a three-state refinement of the proposal's
Discovery/Development framing, produced naturally by the gate + behavior split).

### Example output

```
Collection Maturity
  Developed

Why:
  ✓ No meaningful coverage gaps
  ✓ 84% of your throws use just 4 discs — you've settled on a core
  ✓ Recent additions refine molds you already own, not new experiments
  ✓ 6 established favorites

Another disc is unlikely to improve your game right now.
Your biggest gains will come from throwing the discs you already own.
```

A `Discovery` example leads with the gaps and an encouraging note ("every new disc still teaches
you something — keep exploring"); a `Developing` example shows which **required** signal is `•`
not-yet and what would move it. A mature player who's recently bought a new mold or two still reads
`Developed`, with a supporting `•` line noting the experimenting rather than a demotion.

## Usage insights

Grounded observations from usage history, shown beneath the phase. Compute all, render only the
**most salient** (cap at `MAX_INSIGHTS`, default 4) to avoid a wall of text.

- **Concentration** — for a category with enough discs and usage: "You own 15 drivers; 84% of your
  throws use 4 of them."
- **Neglected disc** — an active, in-bag disc unused for longer than `NEGLECT_DAYS` (or never used
  and added more than `NEGLECT_DAYS` ago): "You haven't thrown your Boss in 6+ months — it may not
  need a bag spot."
- **Primary + backup nudge** — a disc holding a dominant share (`DOMINANT_SHARE`) of a category's
  throws with no near-duplicate backup in the bag (checked via `overlap`): "Your Wave is your
  most-thrown distance driver — consider a backup before a new mold."
- **Category leader** — the most-thrown disc in a major category: "Your Crave leads your fairways
  in rounds."

Each insight is skipped when its threshold isn't met (no forcing). If there's too little usage to
say anything, the section is omitted and the phase's "why" already notes insufficient history.

## Observed preferences

Grounded tendencies, phrased as **observations, not recommendations** ("You reach for…", "You
rarely throw…"). Rendered only when a clear tendency exists.

- **Stability tendency** — bucket the bag (usage-weighted where usage exists) by `stability_word`;
  report a dominant lean: "You gravitate to neutral-to-stable flights."
- **Speed tendency** — the speed band your throws cluster in / rarely exceed: "Your throws cluster
  around speed 5–9; you rarely reach for speed 12+."
- **Brand concentration** — if two or three brands dominate the bag: "Most of your bag is Innova
  and Discraft."

**Explicitly excluded:** plastic tier (premium vs baseline) and rim width — discbag stores plastic
as free text with no tier taxonomy and does not track rim width. These are not inferred or faked.

## Tunable constants

Written as named module constants so they can be tuned without touching logic:

| Constant | Default | Meaning |
|----------|---------|---------|
| `MIN_USES` | 10 | Minimum recorded uses before "settled" can be judged. |
| `ACTIVE_WINDOW` | 90 days | "Thrown recently" for the consistent-usage signal. |
| `CONCENTRATION` | 0.80 | Share of throws that a "core" must cover. |
| `CORE_FRACTION` | 1/3 | Max size of that core, as a fraction of the active bag. |
| `RECENT_WINDOW` | 180 days | Window for a "recently introduced" new mold. |
| `MAX_RECENT_NEW_MOLDS` | 1 | New molds first acquired within `RECENT_WINDOW` before the supporting "not chasing new molds" note flips from refinement to "experimenting" (backups/replacements/plastic/weight variants of owned molds never count). Supporting only — never gates the phase. |
| `MIN_FAVORITES` | 3 | Threshold for the supporting "established favorites" signal. |
| `NEGLECT_DAYS` | 180 | Age past which an unused in-bag disc is "neglected". |
| `DOMINANT_SHARE` | 0.50 | Category-usage share that makes a disc the clear primary. |
| `MAX_INSIGHTS` | 4 | Cap on rendered usage insights. |

## Architecture

New pure module **`maturity.py`** (analysis layer), fully unit-testable:

- `report(active_discs, all_discs, profile, catalog, today)` → a `MaturityReport` dataclass holding
  `phase` (str), `signals` (list of `Signal{met: bool, text: str}`), `insights` (list of str), and
  `preferences` (list of str). Most logic reasons about `active_discs`; the "not chasing new molds"
  signal needs `all_discs` (active **and** archived) so a rebought mold you once owned counts as
  refinement, not a new mold. `today` (a `date`) is injected for deterministic age math (mirrors
  the injectable `now` in `db.update_db`).
- Internal helpers per concern: the gate (over `roles.assess`), each behavior signal, the usage
  insights, the preferences — each independently testable.

`cli.py` gets `cmd_maturity`, which builds the report and renders it — colorized in a terminal,
plain when piped or under `NO_COLOR`, consistent with the dashboard. **No logic in the CLI.**

Reuses: `roles.assess`, `roles.stability_number`/`stability_word`, `analysis.overlap`, and the
`OwnedDisc.user` usage properties (`use_count`, `round_count`, `last_used`, `first_used`,
`favorite`, `date_added`, `in_bag`, `is_active`).

## Testing

- **Gate:** a meaningful (High/Medium, non-optional) missing role → `Discovery`; a missing *Low*
  role or an optional role does **not** force Discovery; empty/tiny bag → `Discovery`.
- **Required signals gate the phase:** full coverage + sufficient usage + settled core →
  `Developed`; full coverage but usage spread across the bag, or usage below `MIN_USES` →
  `Developing`.
- **New molds are supporting, not required:** a settled `Developed` bag stays `Developed` after
  adding one or more genuinely **new** molds (they surface only as a supporting `•` note), as long
  as its usage stays concentrated. Buying a backup, a same-mold `replace`, a plastic/weight variant,
  or rebuying a previously-owned/archived mold introduces no new mold at all.
- **Settled usage is the real backstop:** if new molds actually take over throwing (concentration
  drops below `CONCENTRATION`), the required settled-usage signal fails and the phase falls to
  `Developing` on its own — no separate new-mold gate needed.
- **Favorites are supporting, not required:** a settled bag with zero favorites still reaches
  `Developed`.
- **Usage insights:** each insight fires at its threshold and is absent below it; the render cap is
  respected.
- **Preferences:** a clearly stability-leaning / speed-clustered / brand-concentrated bag yields the
  observation; a mixed bag yields none. Plastic/rim are never mentioned.
- **Determinism:** age-based logic uses the injected `today`, no wall-clock reads.

## Deferred / out of scope

- **Progression over time** (phase-transition timeline). A follow-up once the phase model proves
  stable and useful. discbag stores **no** analysis snapshots today, and this feature adds none —
  so progression, when built, must record **observed evaluations going forward** (persist a phase
  snapshot from that point on) and report those, rather than reconstructing the past retroactively.
  A reconstructed history would be a guess; an observed one is trustworthy. Starting that recording
  is itself the deferred work, and it raises questions this spec intentionally avoids (can a
  collection move backward? what counts as a transition?).
- **Plastic-tier and rim-width preferences** — no supporting data; excluded, not faked.
- **Home-screen maturity line** — possible later; not in v1.
