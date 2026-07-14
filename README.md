# discbag

**Know your bag. Track its history. Throw smarter.**

`discbag` is a command-line companion for your disc golf bag. It's three tools in one:

- **Inventory** — track every disc you own: plastic, weight, color, wear, and how it flies.
- **Career tracker** — log every round and practice; each disc keeps its story for life, even
  after it's lost, sold, or retired.
- **Decision-support engine** — build smarter bags, compare discs, spot overlap, and get a
  *reasoned* answer to what to throw, practice, or buy next.

It isn't just a flight-number lookup. `discbag` learns what **your** collection actually does —
how each disc flies for your arm, which ones you trust, and where your bag has gaps — and every
recommendation comes with a reason.

```text
$ discbag recommend --next
Best Next Purchase

  Overstable approach
  Priority: High

  Reason:
    Your bag already covers putting, straight approach, straight mid, understable fairway,
    and control fairway. No overstable approach disc that reliably fades in wind.

  Suggested discs:
    Prodigy A3  (4 / 3 / 0 / 3)  Overstable
    Wild Discs Angler  (4 / 3 / 0 / 3)  Very Overstable
    Lone Star Discs Artemis  (4 / 4 / 0 / 3)  Very Overstable
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

This installs the `discbag` command. A snapshot of the disc database ships bundled, so it works
offline out of the box.

## Quick start

```bash
discbag add mako3                       # look up and add a disc (auto-fills flight numbers)
discbag add leopard --plastic Star      # attach your own plastic/weight/color/etc.
discbag profile --name Eric --max 275   # tell it who you are and how far you throw
discbag                                 # your home screen — inventory, player, activity, ideas
discbag --help                          # the full, grouped command reference
```

---

## Three ideas

`discbag` grew from a simple bag list into three complementary pieces. Understanding them is the
whole mental model.

**Inventory — what a disc _is_.** Every disc separates **manufacturer data** (mold, flight
numbers, category — from the database) from your **metadata** (plastic, weight, color, condition,
notes, favorite, tags, personal role). Your metadata gets more accurate over time: `edit` fixes or
fills it in whenever you learn something new. Crucially, correcting metadata is **not** an event in
the disc's life — `edit` never writes to its history.

**History — what a disc _has done_.** Rounds, practice sessions, and lifecycle changes are recorded
as they happen, in a persisted event log. A disc's story outlives the disc: when one is lost, sold,
or retired it leaves your bag but keeps its record forever, because a beat-in disc you threw for
three seasons is part of your development. Metadata is corrected; history is only ever appended.

**Analysis — what to do next.** From your inventory and history, `discbag` reasons about **roles**
(the jobs a bag needs filled), how each disc flies **for you**, and which discs you actually trust —
then helps you build a bag, compare two discs, find overlap, and decide what to throw or buy. Nothing
is a black box; every verdict is explained.

A note on words: a **mold** is a product (Roadrunner); a **disc** (or **copy**, when you own several
of a mold) is one physical object; your **inventory** is everything you own; your **bag** is the
subset you currently carry; **metadata** is your editable data about a disc; **history** is its
event log.

---

## The home screen

Run `discbag` with no arguments for a glanceable dashboard — not documentation. Every line is real
engine output, pulled from the same functions the individual commands use.

```text
Eric's Disc Bag
────────────────────────────────────

Inventory
  Active discs   13
  In bag         13
  Favorites       2

Player
  Max distance   320 ft
  Arm power      Speed ~10.0
  Throw hand     Right
  Putt hand      Left

Recent Activity
  Last round     13 days ago
  Last practice  11 days ago

Suggestions
  Practice       Aviar Classic, Mako3, Wizard
  Missing roles  Overstable approach, Overstable mid
  Neglected      Wizard, Classic Roc, Leopard

Quick Commands
  discbag build-bag
  discbag choose --distance 300
  discbag practice
  discbag usage
  discbag list

Run 'discbag --help' for the full command reference.
```

In an interactive terminal it's colorized, keyed by section and icon; piped or redirected (or with
`NO_COLOR` set) it degrades to the plain text above. Set `discbag profile --name <you>` to
personalize the title.

---

## How it thinks

**Roles, not speed classes.** Players don't think "I need another 7-speed" — they think "I need
something that always fades." `discbag` defines **roles** by flight (turn/fade) and intended use:
putting, straight/overstable approach, straight/overstable mid, understable/control fairway, utility
driver, distance driver. A role is *covered* when one or more of your discs fly the way it needs, and
multiple discs can share one.

**Goals and scenarios.** `build-bag` covers roles, but a `--goal` decides what to optimize within
each: `coverage` (fewest discs, most roles), `development` (discs you can power and grow into),
`confidence` (the discs you throw most), `tournament` (proven, low-risk molds), or `fun` (favorites
and variety). Scenario flags (`--windy`, `--woods`, `--rain`, `--minimal`, `--travel`) narrow the
conditions and compose with any goal. Add `--rotate` to vary among comparably-good discs instead of
always picking the single top one.

**Player-aware priority.** The same missing role matters differently to different players. A shorter
thrower whose discs already all fade gains little from a dedicated utility driver, so beyond
coverage every role gets a practical priority — **High/Medium** (worth filling for you now) or
**Low** (technically missing but low value today). Set a profile and, as your distance grows,
low-priority roles climb on their own — **the advice evolves without any change to the engine.**

**Power-aware, and personal.** Each disc has an estimated power requirement from speed *and* turn
*and* fade, so `show` can report how a disc plays **for you** at your current arm speed. Record how a
disc actually flies for you with `flight`, and those numbers override the model everywhere. Refreshing
the database never touches any of your personal data.

---

## Command reference

The reference mirrors `discbag --help`, which groups commands by purpose: **Common**, **Organization**,
**Analysis**, and **Advanced**. Run `discbag <command> --help` for any command's full options.

### Common Commands

```bash
discbag add <name> [--plastic --weight --color --condition --location --notes --yes]
discbag list [--tag <t>] [--favorite] [--in-bag] [--status <s>] [--all] [--ids]
discbag show <name>                 # your metadata + flight + role + how it plays for you
discbag build-bag [--goal coverage|development|confidence|tournament|fun] [--rotate]
                  [--size N | -n N] [--windy|--woods|--rain|--minimal|--travel]
discbag recommend [--gaps] [--next] [--preferred-only] [--per-slot N]
discbag profile [ ... ]             # show or set your player profile (see below)
```

`add` looks the disc up in the database and auto-fills its flight numbers; the flags attach your own
metadata. `list --all` (or `--status lost`) includes archived discs; `list --ids` reveals each disc's
id. `recommend` reports role coverage with a priority and reason for each; `--next` names the single
most valuable purchase, `--gaps` shows only missing roles, and `--per-slot N` sets how many candidate
discs to suggest (default 3).

`profile` is your development dashboard. With no arguments it prints your stats; with flags it sets
them:

```bash
discbag profile [--name Eric --experience beginner|intermediate|advanced|elite
                 --hand right|left --putt-hand right|left --style backhand|forehand|both
                 --typical N --max N --fairway-speed N --driver-speed N --release-speed N
                 --spin N --brand Innova --brand "Latitude 64" | --clear-brands]
```

`--putt-hand` (alias `--putt`) records a separate putting hand; `--brand` is repeatable and softly
favors those brands in purchase suggestions (`recommend --preferred-only` restricts to them entirely).
From your distances the engine derives an estimated **arm power** — the one number the recommendation
engine reads — and a **Comfort Zone** of the speeds you throw today, are developing, and can grow into.

```text
$ discbag profile
Player Profile

Experience
----------
Experience:               Intermediate

Throwing
--------
Throwing hand:            Right
Putting hand:             Left

Performance
-----------
Typical distance:         280 ft
Max distance:             320 ft
Comfortable driver speed: 10
Spin rate:                20 rpm

Preferences
-----------
Preferred brands:         Innova, Discraft

Comfort Zone
------------
Comfortable speeds:       2-10
Developing:               11-12
Future:                   13+

Estimated Arm Power
-------------------
Speed ~10.0

Recommendations automatically adapt as your distance and throwing ability improve.
```

### Organization

```bash
discbag bag add|remove|list <name>  # which discs you currently carry
discbag remove <name> [--status retired|lost|sold|gifted|broken] [--reason "..."]
discbag lost <name> [--reason "..."]                        # archive as lost
discbag damaged <name> [--reason "..."] [--retire | --unset] # flag (kept in bag), archive, or clear
discbag replace <name> [--status <s>] [--reason "..."] [--plastic --weight --color]
discbag restore <name>              # bring an archived disc back to the bag
discbag delete <name> [--yes]       # permanently erase a disc and its history (confirms first)
discbag history <name>              # a disc's full story, even after it leaves your bag
discbag favorite <disc> [--unset] [--all]
discbag tag <disc> <tag> [--all]    # untag <disc> <tag> [--all] to remove
discbag role <disc> "hyzer flip"    # a personal role label
discbag edit <name> [--plastic --weight --color --condition --notes --manufacturer --mold]
                    [--id <id>]     # correct metadata in place; never logs a history event
```

**A disc's life is tracked, not erased.** Every disc has a lifecycle status — `active`, or an
archived state (`retired`, `lost`, `sold`, `gifted`, `broken`) with an optional reason. `lost`,
`sold`, and friends archive a disc out of your active inventory but keep its history; `restore`
brings one back; only `delete` truly erases, and it asks first.

`damaged` is subtler, because a beat-in disc is often still in play: it flags the disc but **keeps it
in your bag** and in every recommendation, just visibly marked. When it's finally worn out,
`damaged <disc> --retire` archives it as broken; a mistaken flag clears with `--unset` (a disc is
plastic — replaced, never repaired). When you buy a fresh copy, `replace <disc>` archives the old one
and adds a brand-new copy of the same mold with a **clean** history — a new disc flies differently
from a beat one, so it earns its own story.

`edit` fixes or fills in a disc's metadata after adding it — including a typo in the manufacturer or
mold, which re-derives the cached flight numbers from the database. Because it's a **correction, not
an event**, it never touches the disc's history.

`history` shows a summary followed by the persisted event timeline. For a disc you played a few
times and later sold, it reads like this (illustrative):

```text
Innova Leopard
  Status: Sold
  ...

History

  2026-05-01  Added
  2026-05-10  Round (+1)
  2026-06-02  Practice session (+1)
  2026-06-20  Sold (traded to a friend)
```

**Two of the same mold are two different discs.** Each copy keeps its own wear, history, and personal
flight, so two Roadrunners can legitimately earn different advice. You rarely think about the id
behind them — single-disc commands just ask which copy you mean, using whatever tells them apart
(plastic, weight, color). For scripting, `list --ids` reveals those ids and `edit --id` targets one
directly. And the bulk-friendly commands (`tag`, `untag`, `favorite`, `sync`) take `--all` to act on
every copy at once.

### Analysis

```bash
discbag round-used <disc...> [--date YYYY-MM-DD]   # "I played these in a round" (used = alias)
discbag practice-used <disc...> [--date ...]        # "I practiced with these"
discbag usage [<disc>]                              # per-disc, or overall (most used / neglected)
discbag practice [--count N]                        # form-focused practice discs
discbag choose --distance N --wind head|tail|none --shape straight|hyzer|anhyzer|turnover
discbag overlap                                     # near-duplicate discs (by how they fly for you)
discbag compare <disc...>                           # side-by-side table + verdict (bag or database)
discbag chart [--type flight|grid|stability|speed|composition|brands]
discbag flight <disc> 6/5/-1/2 [--distance N] [--confidence 1-5] [--clear]
```

Use tracking is session-level, not throw-by-throw — it just answers *which discs did I use this
session*. Rounds and practice are recorded separately but both bump the same **use count**, so
`usage` can break either down:

```text
$ discbag usage buzzz
Discraft Buzzz

  Use count: 2
  Last used: 2026-07-03 (11 days ago)
  Recently used: Yes
  Rounds: 1
  Practices: 1
  Last round: 2026-07-01
  Last practice: 2026-07-03
```

This signal feeds the build-bag goals: `confidence` and `tournament` favor discs you use often and
recently, `development` nudges toward under-used discs, and `fun` revisits ones you've neglected.

`flight` records how a disc actually flies **for you** (`--clear` removes it). `compare` shows
speed/glide/turn/fade plus a derived **Stability** and **Role** row; for exactly two discs it adds a
plain-language bottom line, and if both are in your bag, how many rounds you've thrown each:

```text
$ discbag compare wave wraith
                       Wave            Wraith
Speed                    11                11
Glide                     5                 5
Turn                     -2                -1
Fade                      2                 3
Stability           neutral        overstable
Role        Distance driver   Distance driver

Bottom line

Overlap:
These occupy the same broad distance driver slot, but their flights are meaningfully different.

Key difference:
The Wave has more high-speed turn and a gentler finish. The Wraith resists turning more and
fades harder.

How to use them:
Reach for the Wave when you want easier distance and more movement before the fade. Reach for the
Wraith when you want a stronger finish or more resistance to wind. Expect the Wraith to finish left
more strongly than the Wave. That difference is built into the discs, although an unusually early
fade can still reflect the throw.
```

Charts default to a Braille-dot scatter (speed vs stability); `--type grid` is a labelled letter
chart, and `stability`/`speed`/`composition`/`brands` are distribution histograms.

### Advanced

```bash
discbag explain build-bag [--goal G] [--rotate] [--windy|--woods|...]  # why each role's disc won
discbag explain role "Control fairway"                                  # ranked candidate scores
discbag score <disc...> [--goal G] [--role NAME] [--situation S] [--verbose|-v]
discbag sync [<disc>] [--all]       # refresh cached stats (keeps your metadata)
discbag updatedb                    # refresh the whole disc database from the source
discbag db-info                     # database size and age
```

`explain` and `score` are verbose views into *why* the engine chose what it did — useful for tuning.
`score` breaks a total into components (role fit, the goal's sub-terms, a scenario adjustment) that
sum to the points shown, and only lists components the engine actually used.

---

## Architecture

One reusable engine backs every command — coverage, player ability, and ranking are decided in one
place, not duplicated per command.

| Module | Responsibility |
|--------|----------------|
| `roles.py` | The role engine: definitions, qualification, coverage, priority, suggestions, `best_next`. |
| `player.py` | The player profile, the disc power-requirement model, and player-adjusted flight. |
| `recommend.py` | The role-based bag builder (`build-bag`), including situational bags. |
| `analysis.py` | Overlap, compare, choose, practice. |
| `inventory.py` | The inventory: `Disc` (mold), `UserData`, `OwnedDisc`, persistence, the event log. |
| `db.py` | The disc database: fetch, snapshot, fuzzy lookup. |
| `chart.py` / `braille.py` | Terminal visualizations. |
| `history.py` | Renders the persisted event timeline. |
| `cli.py` | Argument parsing and output. |

Data lives in `~/.discbag/`: `inventory.json` (your discs), `profile.json` (your profile), and
`discs.json` (the database snapshot). None of it is part of this repository.

## Data source

Flight numbers come from the free [DiscIt API](https://discit-api.fly.dev/disc), which sources from
the [Marshall Street Flight Guide](https://www.marshallstreetdiscgolf.com/flightguide) — roughly
1,200 discs with speed / glide / turn / fade, brand, category, and stability. Flight databases track
the base mold, not plastic/run variants, so `discbag` matches the base mold (e.g. "Gateway Wizard SS
Chalky" → "Wizard") and stores the plastic as your own metadata.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e . pytest
pytest
```

The project is built test-first; the pure logic (roles, power model, coverage, analysis, charts,
migration) is covered by the suite in `tests/`.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

[MIT](LICENSE) © 2026 Eric Martin
