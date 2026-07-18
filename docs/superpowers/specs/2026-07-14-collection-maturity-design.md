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

If there are no meaningful gaps, examine settledness signals (each a boolean with a plain reason):

1. **Consistent, real usage** — enough recorded throws to judge (`total recorded uses ≥ MIN_USES`)
   **and** thrown recently (`last activity within ACTIVE_WINDOW`). This is the data-sufficiency
   gate: without it we can't claim "settled," so the phase can be at most `Developing`.
2. **Settled core** — a small handful of discs accounts for most throws: the fewest active discs
   whose combined `use_count` reaches `CONCENTRATION` of all recorded uses is at most
   `CORE_FRACTION` of the active bag.
3. **Not chasing new molds — refining, not exploring.** The behavior that signals immaturity is
   still *searching for what works* — bringing in genuinely **new molds** — not simply buying
   something similar to what you own. Count the distinct molds whose **first** acquisition
   (earliest `date_added` across all your copies of that mold, active or archived) falls within
   `RECENT_WINDOW`; the signal is met when that count is at most `MAX_RECENT_NEW_MOLDS`.

   Crucially, another copy of a mold you **already own** introduces no new mold, so it never counts
   against you: a backup of a favorite, a same-mold replacement (what `replace` produces), another
   plastic or weight, cycling a fresh Roc or Wizard. Those are refinement — the mark of a settled
   player who knows what they like — not exploration. No recent acquisitions at all also counts as
   met.

**Established favorites** (`favorites ≥ MIN_FAVORITES`) is shown as a **supporting** signal in the
"why" list but is **not required** for `Developed` — marking favorites is a manual action, and its
absence doesn't prove a player is unsettled.

**Phase resolution:**
- **`Developed`** — no meaningful gaps **and** all three behavioral signals (1, 2, 3) met.
  Message: *"Another disc is unlikely to improve your game right now — your gains are in reps."*
- **`Developing`** — no meaningful gaps, but at least one behavioral signal is unmet (throws still
  spread out, still bringing in new molds, or **not enough usage history to judge**). A
  freshly-stocked full-coverage bag with no rounds logged lands here, never `Developed`.

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
you something — keep exploring"); a `Developing` example shows which behavioral signal is `•`
not-yet and what would move it.

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
| `MAX_RECENT_NEW_MOLDS` | 1 | New molds first acquired within `RECENT_WINDOW` allowed while still "settled" (backups/replacements/plastic/weight variants of owned molds never count). |
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
- **Behavior:** full coverage + all three behavioral signals → `Developed`; full coverage but
  spread-out usage, or a recent new mold beyond `MAX_RECENT_NEW_MOLDS`, or usage below `MIN_USES`
  → `Developing`.
- **Refinement is not exploration:** a settled `Developed` bag stays `Developed` after buying a
  backup of an owned mold, a same-mold `replace`, or another plastic/weight of a mold it owns
  (no new mold introduced). Rebuying a mold you previously owned and archived also counts as
  refinement, not a new mold. Adding a genuinely new mold beyond the threshold does move it to
  `Developing`.
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
