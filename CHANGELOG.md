# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `discbag maturity` — a qualitative read of where your collection sits (Discovery / Developing /
  Developed) and why, with grounded usage insights and observed preferences. Answers "do I actually
  need anything?" rather than "what should I buy?"
- `discbag compare` now adds a derived Stability row and, for two discs, a
  rule-derived bottom line (overlap, key difference in relative terms, and how to
  use each), plus an ownership footer when both discs are in your bag.
- `discbag edit` corrects a disc's inventory metadata (plastic, weight, color, condition,
  notes, manufacturer, mold) in place, without creating a history event. Changing the
  manufacturer/mold refreshes cached flight numbers from the database.
- `discbag list --ids` prints each disc's internal id, for targeting a specific copy with
  `discbag edit --id`.
- A history timeline. `history <disc>` now prints its summary followed by a chronological
  list of what happened to the disc — when it was added, each round and practice, and every
  lifecycle change (lost, retired, broken, sold, gifted, restored, damaged, and the atomic
  "damaged and retired"). It is backed by a real persisted per-disc **event log** recorded as
  each mutation happens. Discs that predate the log are seeded once from timestamps already on
  file (added, uses, the last known status transition); damage, favorite, flight, role, and
  tag are never seeded — no timestamp was stored and history is never invented. Favorite,
  flight, role, and tag events join the timeline in a later phase.
- First-class verbs for marking discs lost or damaged. `lost <disc>` archives a disc as lost
  (keeping its history, `restore`-able if found). `damaged <disc>` flags a disc as damaged but
  **keeps it active and in your bag** — a beat-in disc is often still in play — and it still
  counts in every recommendation, just visibly marked in `list`/`show`. `damaged --retire`
  archives it (as broken) once it's worn beyond use; `damaged --unset` clears a mistaken flag
  (discs are plastic — replaced, never repaired). `replace <disc>` archives the old copy and
  adds a fresh copy of the same mold with a **clean** history, carrying over its
  plastic/weight/color/role/favorite/tags (`--plastic`/`--weight`/`--color` override), because
  a new disc flies differently from a beat one and deserves its own story. A new `damaged`
  wear flag on user data is orthogonal to lifecycle status and defaults off; older inventory
  files load unchanged.
- Individual disc identity. Every disc gets a permanent internal id when added (existing
  inventories are migrated automatically, no interaction needed), so two copies of the same
  mold keep separate histories, lifecycle, favorites, notes, and flight. Single-disc commands
  (`show`, `remove`, `delete`, `restore`, `history`, `role`, `flight`, `usage`,
  `round-used`/`practice-used`) resolve a typed name to one physical disc: a single match runs
  as before, multiple matches prompt (showing plastic/weight/color/etc. to tell them apart),
  and an ambiguous name is a hard error — never a guess — when there's no terminal to ask.
  Bulk-friendly commands (`tag`, `untag`, `favorite`, `sync`) take `--all` to act on every
  copy; `sync` also accepts an optional disc to refresh just that disc/mold. IDs are internal;
  users never see or type them. Recommendations are unchanged — they already
  evaluate each physical disc independently.
- A home-screen dashboard. Running `discbag` with no arguments now prints a glanceable
  summary — inventory counts, your profile and estimated arm power, latest round/practice,
  and lightweight suggestions (practice discs, missing roles, neglected discs) — instead of
  argparse help. Every value comes from existing engine functions; nothing is invented. In
  an interactive terminal it's colorized with section icons (plain and parseable when piped
  or when `NO_COLOR` is set). `discbag --help` becomes the canonical reference and is now
  organized by purpose (Common / Organization / Analysis / Advanced). `discbag profile
  --name <you>` personalizes the dashboard title.
- Disc lifecycle that preserves history. Every disc has a **status** — `active` or an
  archived state (`retired`, `lost`, `sold`, `gifted`, `broken`) with an optional reason.
  `remove` now **archives** instead of deleting (default status `retired`; `--status` and
  `--reason` record the story), so a disc that leaves your bag keeps its history. Archived
  discs are excluded from the active inventory the engine reasons about (`recommend`,
  `build-bag`, `bag`, `choose`, `chart`, `show`). New commands: `history <disc>` (full story
  incl. status/reason/uses/rounds/practices/first & last used — spans active *and* archived),
  `restore <disc>` (reactivate), and `delete <disc>` (the only permanent erase, with a
  confirmation prompt and `--yes`). `list` gains `--all` and `--status` to view archived discs.

### Changed
- `round-used` is now the primary verb for recording a round; `used` is documented as its
  alias (`practice-used` records practice). No behavior change — only naming/help clarity.
- Player profile records a separate putting hand (`--putt-hand`, alias `--putt`) for
  players who throw with one hand and putt with the other.
- `profile` is now a sectioned dashboard (Experience / Throwing / Performance /
  Preferences / Comfort Zone / Estimated Arm Power) with proper units (ft, rpm) and no
  stray precision.
- A **Comfort Zone** derived from estimated arm power shows the speed ranges a player
  throws comfortably, is developing, and can grow into — explaining why recommendations
  shift as the player improves.
- Preferred brands on the player profile (`--brand`, repeatable; `--clear-brands`).
- Purchase suggestions favor preferred brands softly — the best fits are still shown, but a
  preferred-brand disc is promoted when it fits nearly as well. `recommend --preferred-only`
  restricts suggestions to preferred brands, with a graceful message when none are set.
- `build-bag --goal coverage|development|confidence|tournament|fun` chooses what the bag
  optimizes for; scenarios (`--windy`, `--woods`, …) remain environmental modifiers and
  compose with goals.
- `build-bag --rotate` varies among comparably-scored discs for controlled variety, never
  selecting a notably worse disc.
- Explainable scoring for tuning the engine: `discbag explain build-bag` (per-role
  selection, score, other candidates, and rotation visibility), `discbag explain role
  "<name>"` (profile + ranked candidate scores), and `discbag score <disc>... [--verbose]`
  (a component breakdown — role fit, goal sub-terms, scenario — summing to a points total).
  Only components the engine actually uses are exposed.
- Lightweight use tracking: `discbag used <disc>...` (and the `round-used` alias) records a
  timestamped use, `--date` backfills a past round, and `discbag usage` summarizes per-disc
  or overall (most used / neglected). `throw_count` is renamed to `use_count` (legacy data
  migrated) and joined by `last_used` and a `use_dates` log. Use signal feeds the build-bag
  goals (confidence/tournament favor frequent & recent use; development favors under-used
  discs; fun revisits neglected ones).
- Rounds and practice are tracked separately. `discbag practice-used <disc>...` records a
  practice session (backyard, field, putting, net); `round-used`/`used` record a round. Each
  use log entry now carries a `session_type`, and `usage` breaks the total down into Rounds /
  Practices with the last of each. `use_count` still increments for both — only the context
  differs. Legacy string entries count as rounds; no migration required.

## [0.1.0] - 2026-07-02

Initial release — a command-line disc golf bag intelligence engine.

### Added

**Bag management**
- `add` with hybrid lookup: matches the local disc database, prompts among multiple
  molds, or falls back to manual entry. Strips plastic/run words so
  "Gateway Wizard SS Chalky" matches the base "Wizard" and stores the plastic as metadata.
- `list` (with `--tag`, `--favorite`, `--in-bag` filters), `show`, and `remove`.
- Bag stored as human-readable JSON in `~/.discbag/`.

**Disc database**
- Bundled snapshot of ~1,200 discs from the free DiscIt API (Marshall Street Flight Guide).
- `updatedb` to refresh the database, `db-info` to show its size and age.

**Separation of manufacturer and user data**
- Each owned disc references a mold + cached manufacturer snapshot, kept strictly separate
  from user data (plastic, weight, color, condition, purchase location, date added,
  favorite, tags, personal role, throw count, notes, personal flight numbers).
- `sync` refreshes cached manufacturer numbers without touching personal data.
- Automatic, backed-up migration of the older flat inventory format.

**The role engine**
- A single reusable engine defining roles by flight characteristics (turn/fade) and
  intended use rather than speed class.
- `recommend` reports Covered/Missing per role with an explanation; `--gaps` shows only
  missing roles; `--next` names the single most valuable purchase.
- `build-bag` assembles a bag by covering functional roles, with situational presets
  (`--windy`, `--woods`, `--minimal`, `--travel`, `--rain`) and an `-n`/`--size` limit.

**Player awareness**
- A single persistent player profile (`profile`): distance, arm speed, experience, hand,
  style.
- A disc power-requirement model derived from speed + turn + fade (understable discs need
  less power than overstable ones), labelled *estimated*, with support for explicit
  per-mold overrides.
- Practical priority (Satisfied / High / Medium / Low) layered on role coverage, so
  recommendations reflect what would improve *your* game today and evolve automatically as
  your distance grows.
- Player-adjusted flight informs recommendations, `choose`, `practice`, and `overlap`.

**Personalization**
- `tag`/`untag`, `role`, `favorite`, and `bag add|remove|list` (owned vs. currently carried).
- `flight` records personal flight numbers (with average distance and confidence), which
  override the modelled behavior everywhere.

**Analysis & decision**
- `overlap` — finds near-duplicate discs by how they fly for you.
- `compare` — side-by-side flight/role table for discs from your bag or the database.
- `choose` — the best disc to throw for a shot (`--distance`, `--wind`, `--shape`).
- `practice` — form-focused practice discs.

**Visualization**
- `chart` — a Braille-dot flight scatter by default, plus `grid` (labelled letter chart)
  and `stability`/`speed`/`composition`/`brands` distribution histograms.

**Project**
- Built test-first with 109 passing tests. MIT licensed. No third-party dependencies.

[Unreleased]: https://github.com/erimar77/discbag/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/erimar77/discbag/releases/tag/v0.1.0
