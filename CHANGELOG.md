# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Player profile records a separate putting hand (`--putt-hand`, alias `--putt`) for
  players who throw with one hand and putt with the other.
- `profile` is now a sectioned dashboard (Experience / Throwing / Performance /
  Comfort Zone / Estimated Arm Power) with proper units (ft, rpm) and no stray
  precision.
- A **Comfort Zone** derived from estimated arm power shows the speed ranges a player
  throws comfortably, is developing, and can grow into — explaining why recommendations
  shift as the player improves.

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
