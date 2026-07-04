# discbag

A command-line **disc golf bag intelligence engine**. It manages your bag, looks up
disc flight numbers, and reasons about *roles* and *your game* to tell you what your bag
covers, what it's missing, which discs overlap, which to throw, and what to buy next —
with a reason for every recommendation.

It's not just a disc database. It reasons about **how discs fly**, **what jobs they
perform**, and **how you actually throw** — and its advice evolves as you gain distance.

```
$ discbag recommend --next
Best Next Purchase

  Utility driver
  Priority: Low

  Reason:
    at your power most of your discs already behave overstable, so a utility driver
    adds few new shot shapes today — re-evaluate as your distance grows
```

---

## Install

Requires Python 3.9+.

```bash
git clone https://github.com/erimar77/discbag.git
cd discbag
python -m venv .venv && . .venv/bin/activate
pip install -e .
```

This installs the `discbag` command. A snapshot of the disc database ships bundled, so it
works offline out of the box.

## Quick start

```bash
discbag add mako3                       # look up and add a disc (auto-fills flight numbers)
discbag add leopard --plastic Star      # attach your own plastic/weight/color/etc.
discbag profile --typical 250 --max 275 # tell it how you throw
discbag recommend                       # what does my bag cover, and what's worth adding?
discbag chart                           # a Braille-dot flight chart of your bag
```

---

## How it thinks

### Roles, not speed classes

Players don't think "I need another 7-speed" — they think "I need something that always
fades" or "a straight tunnel disc." `discbag` defines **roles** by flight characteristics
(turn/fade) and intended use, not by speed. The standard roles are:

Putting · Straight approach · Overstable approach · Straight mid · Overstable mid ·
Understable fairway · Control fairway · Utility driver · Distance driver.

A role is **Covered** when one or more of your discs fly the way it needs; multiple discs
can share a role. Every verdict is explained.

### Goals: what a bag is *for*

`build-bag` still covers roles, but different players ask different questions, so a
`--goal` decides *what to optimize* within each role:

- **coverage** (default) — the best-fitting disc per role; fewest discs, most roles.
- **development** — discs you can power and that reward clean form; avoids specialized molds.
- **confidence** — the discs you throw most and trust; predictable and comfortable.
- **tournament** — proven, reliable, low-risk molds; minimal experimentation.
- **fun** — favorites and variety.

Scenarios (`--windy`, `--woods`, `--rain`, `--minimal`, `--travel`) are **environmental
modifiers** that narrow *which conditions* the bag is for — orthogonal to the goal, so
they compose: `discbag build-bag --woods --goal development`.

Add `--rotate` for controlled variety: when several discs fill a role comparably well, it
picks among them instead of always the single top disc — exposing you to more of your
collection while never choosing a notably worse disc.

### Player-aware priority

The same missing role matters differently to different players. A ~250 ft thrower whose
discs already all fade left gains little from a dedicated utility driver, even though it's
*technically* missing. So on top of coverage, every role gets a practical **priority**:

- **Satisfied** — covered.
- **High / Medium** — missing and worth filling for you now.
- **Low** — missing but low value today (needs more arm speed, or your bag already behaves
  that way), with a note to re-evaluate as you improve.

Set a player profile and the engine adapts. As your distance grows, low-priority roles
(utility drivers, high-speed distance drivers) climb on their own — **the recommendations
evolve without any change to the engine.**

### The player dashboard

`discbag profile` is your development dashboard. It groups everything into sections
(Experience, Throwing, Performance, Preferences, Comfort Zone, Estimated Arm Power) and
records your throwing hand, a separate **putting hand** if you putt with the other hand,
distances, spin rate, and **preferred brands**. From your estimated arm power it derives a
**Comfort Zone** — the speeds you throw comfortably today, are developing, and can grow
into — so the engine's ability-based decisions are easy to understand. Estimated arm power
is the single metric the recommendation engine reads.

Your **preferred brands** shape purchase suggestions softly: `recommend` still surfaces
the best-fitting discs, but when a preferred-brand disc fits nearly as well as another it
is bumped up. A clearly better disc from any brand still wins. Use
`recommend --preferred-only` to restrict suggestions to your preferred brands entirely.

### Power-aware discs

Each disc has an estimated **power requirement** derived from speed **and** turn **and**
fade — an understable 13-speed needs less power than an overstable one; a very overstable
9-speed can need more usable power than an understable 10-speed. Values are labelled
*estimated*; explicit per-mold overrides take precedence when present. `show` reports the
requirement and how the disc *plays for you* at your current power.

### A disc's history outlives the disc

Discs tell the story of a player's development, and a lost disc is still part of that
story. So discbag never throws history away when a disc leaves your bag. Every disc has a
**lifecycle status** — `active`, or an archived state (`retired`, `lost`, `sold`, `gifted`,
`broken`) with an optional reason:

```text
$ discbag remove leopard --status lost --reason "Woodland Park hole 18"
Disc archived.
  Status: Lost
  Reason: Woodland Park hole 18
```

Archived discs drop out of your **active inventory** — `recommend`, `build-bag`, `bag`,
`choose`, `chart`, and `show` only ever reason about discs still in play — but their record
lives on. `history <disc>` recalls it forever (status, reason, uses, rounds, practices,
first and last used), `list --all` (or `--status lost`) surfaces archived discs, and
`restore` brings one back if you find it or trade for it again. Only `delete` truly erases a
disc, and it asks first. `remove` is safe by default; deletion is the deliberate exception.

### Your data stays yours

Each owned disc separates **manufacturer data** (mold, flight numbers, category — from the
database) from **your data** (plastic, weight, color, condition, purchase location, date
added, favorite, tags, personal role, throw count, notes, personal flight numbers).
Refreshing the database never touches your personal data. Recorded personal flight numbers
always override the modelled behavior.

---

## Command reference

### Your bag
```bash
discbag add <name> [--plastic --weight --color --condition --location --notes --yes]
discbag list [--tag <t>] [--favorite] [--in-bag] [--status <s>] [--all]
discbag show <name>                 # your data + flight + role + power + how it plays for you
discbag remove <name> [--status lost|sold|gifted|broken|retired] [--reason "..."]
discbag restore <name>              # bring an archived disc back to the active bag
discbag history <name>              # a disc's full story, even after it leaves the bag
discbag delete <name> [--yes]       # permanently erase a disc and its history (confirms first)
```

`remove` **archives** rather than deletes — see the disc lifecycle below.

### Personalize
```bash
discbag tag <disc> <tag>            # untag <disc> <tag> to remove
discbag role <disc> "hyzer flip"    # a personal role label
discbag favorite <disc> [--unset]
discbag bag add|remove|list         # which owned discs you currently carry
discbag flight <disc> 6/5/-1/2 [--distance 255] [--confidence 5]   # how it flies for YOU
```

### Use tracking
```bash
discbag round-used warlock mako3 leopard    # "I played these in a round today" (timestamped)
discbag practice-used mako3 eagle warlock   # "I practiced with these" (backyard, field, net)
discbag used mako3 warlock leopard eagle    # alias of round-used
discbag round-used mako3 --date 2026-07-03  # backfill a past session
discbag usage [<disc>]                       # per-disc, or overall (most used / neglected)
```
Lightweight, session-level tracking — not throw-by-throw; it just answers *which discs did
I use this session*. Two kinds of session are recorded separately: an actual **round**
(`round-used`; `used` is a documented alias) and **practice** (`practice-used` — backyard,
field work, putting, net sessions). Both bump the same **use count** and set **last used**; only the session
context differs, so `usage` can break it down:

```text
Use count:      2
Rounds:         1
Practices:      1
Last round:     Jul 1
Last practice:  Jul 3
```

This signal feeds the build-bag goals: **confidence** and **tournament** favor discs you use
often and recently, **development** nudges toward under-used discs that deserve reps, and
**fun** revisits discs you haven't thrown lately. (Legacy uses recorded before this split
count as rounds.)

### You
```bash
discbag profile                     # show your profile dashboard
discbag profile [--typical N --max N --experience .. --hand .. --putt-hand ..
                 --style .. --fairway-speed N --driver-speed N --spin N
                 --brand Innova --brand "Latitude 64" | --clear-brands]
```
`--hand` is your dominant throwing hand; `--putt-hand` (alias `--putt`) records a
different putting hand if you putt with the other hand; `--brand` (repeatable) sets your
preferred brands. With no arguments, `profile` prints a sectioned dashboard:

```text
Player Profile

Throwing
--------
Throwing hand:      Right
Putting hand:       Left

Comfort Zone
------------
Comfortable speeds: 2-7
Developing:         8-9
Future:             10+

Estimated Arm Power
-------------------
~Speed 6.9

Recommendations automatically adapt as your distance and throwing ability improve.
```

### Intelligence
```bash
discbag recommend                   # role coverage: Covered/Missing + Priority + reason
discbag recommend --gaps            # only missing roles
discbag recommend --next            # the single most valuable purchase for you
discbag recommend --preferred-only  # suggest only from your preferred brands
discbag build-bag [--goal coverage|development|confidence|tournament|fun] [--rotate]
                  [-n N] [--windy|--woods|--minimal|--travel|--rain]
discbag overlap                     # near-duplicate discs (by how they fly for you)
discbag compare leopard crave river # side-by-side table (from your bag or the database)
discbag choose --distance 280 --wind head --shape straight   # which disc to throw now
discbag practice                    # form-focused practice discs
discbag chart [--type flight|grid|stability|speed|composition|brands]
```

### Data
```bash
discbag updatedb                    # refresh the disc database from the source
discbag sync                        # refresh your discs' cached stats (keeps your data)
discbag db-info                     # database size and age
```

Charts default to a **Braille-dot scatter** (speed vs stability) for a dense view;
`--type grid` is a labelled letter chart, and `stability`/`speed`/`composition`/`brands`
are distribution histograms.

### Explain & score (developer tools)

Verbose views into *why* the engine chose what it did — useful for tuning heuristics.
The standard commands stay concise; these are intentionally verbose.

```bash
discbag explain build-bag [--goal G] [--minimal|--windy|...] [--rotate]
                                    # per-role: selected disc, score, other candidates,
                                    # and whether --rotate actually rotated
discbag explain role "Control fairway"   # profile + ranked candidate scores + selection
discbag score eagle crave leopard river [--goal G] [--role NAME]
discbag score eagle --goal development --verbose   # full component breakdown
```

Scores are presented as points (higher = better) with a component breakdown — Role fit,
the goal's sub-terms (power mismatch, proven use, recency, favorite, …), and a scenario
adjustment — that sum to the total. Only components the engine actually uses are shown.

---

## Architecture

One reusable engine backs every command — coverage, player ability, and ranking are
decided in one place, not duplicated per command.

| Module | Responsibility |
|--------|----------------|
| `roles.py` | The role engine: role definitions, qualification, coverage, priority, suggestions, `best_next`. |
| `player.py` | The single player profile, the disc power-requirement model, and player-adjusted flight. |
| `recommend.py` | The role-based bag builder (`build-bag`), including situational bags. |
| `analysis.py` | Overlap, compare, choose, practice. |
| `inventory.py` | The bag: `Disc` (mold), `UserData`, `OwnedDisc`, persistence, migration. |
| `db.py` | The disc database: fetch, snapshot, fuzzy lookup. |
| `chart.py` / `braille.py` | Terminal visualizations. |
| `cli.py` | Argument parsing and output. |

Data lives in `~/.discbag/`: `inventory.json` (your bag), `profile.json` (your profile),
and `discs.json` (the database snapshot). None of it is part of this repository.

## Data source

Flight numbers come from the free [DiscIt API](https://discit-api.fly.dev/disc), which
sources from the [Marshall Street Flight Guide](https://www.marshallstreetdiscgolf.com/flightguide)
— roughly 1,200 discs with speed / glide / turn / fade, brand, category, and stability.
Flight databases track the base mold, not plastic/run variants, so `discbag` matches the
base mold (e.g. "Gateway Wizard SS Chalky" → "Wizard") and stores the plastic as your own
metadata.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e . pytest
pytest
```

The project is built test-first; the pure logic (roles, power model, coverage, analysis,
charts, migration) is covered by the test suite in `tests/`.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

[MIT](LICENSE) © 2026 Eric Martin
