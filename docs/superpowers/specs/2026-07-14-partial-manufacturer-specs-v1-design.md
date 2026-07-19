# Partially-known manufacturer specifications (v1) — design

**Date:** 2026-07-14
**Status:** Approved direction, pre-implementation

## Purpose

Support discs whose **manufacturer flight specifications are partially or fully unknown** —
Gateway Premier prototypes are the motivating case — without inventing numbers and without
losing the information the manufacturer *did* provide. Unknown values are represented honestly
(never silently `0`), incomplete-flight discs stay first-class in inventory and lifecycle, and
the reasoning engine simply declines to compute flight math it doesn't have.

The real feature is **"partially-known manufacturer specs,"** not "prototypes." Prototype
provenance and spec completeness are **independent axes** (the Wizard OS fixture proves it).

### Scope (from the product decision)

discbag stays a tracker of **throwable discs**. Prototype / first-run / limited-edition /
fundraiser metadata is recorded *when attached to a throwable disc*. Minis, pins, patches,
stickers, and merchandise are **out of scope** — the Gateway Premier 3D mini is not modeled.
**No generic collection-item hierarchy in v1.**

## Two independent axes (the core model idea)

| Axis | Question | Stored as | Example: Comanche | Example: Wizard OS | Example: stock Buzzz |
|------|----------|-----------|-------------------|--------------------|----------------------|
| **Spec completeness** | Are the four flight numbers published? | **Derived** (`has_flight`) | ✗ (speed only) | ✓ (3/3/0/2.5) | ✓ |
| **Provenance / release** | Is this an experimental/limited release, and from where? | **Stored** (`release_status`, `program`, `release`) | prototype, Premier, 2026-07 | prototype, Premier, 2026-07 | production |

Wizard OS is the acceptance-critical case: **`release_status = prototype` with complete flight** —
it participates in analysis normally, proving the axes are decoupled.

---

## Model / schema changes

### `Disc` (manufacturer mold snapshot) — `discbag/inventory.py`

```python
@dataclass
class Disc:
    name: str
    brand: str = ""
    category: str = ""
    # Flight becomes OPTIONAL. None = "not published", distinct from a real 0.
    speed: Optional[float] = None        # was: float = 0
    glide: Optional[float] = None
    turn: Optional[float] = None
    fade: Optional[float] = None
    stability: str = ""
    # --- v1: provenance & spec state (manufacturer side) ---
    release_status: str = "production"       # "production" | "prototype"
    origin: str = "discit"               # open string: "discit" | "local" | future catalogs
    program: Optional[str] = None         # e.g. "Premier Membership"
    release: Optional[str] = None         # e.g. "2026-07"
    manufacturer_notes: List[str] = field(default_factory=list)

    @property
    def has_flight(self):
        """All four manufacturer flight numbers are published."""
        return all(v is not None for v in (self.speed, self.glide, self.turn, self.fade))
```

### `UserData` (personal / per-copy) — `discbag/inventory.py`

```python
    edition: str = ""      # v1: per-copy run/edition label (First Run, Tour Series, LE, ...)
    # personal_flight: UNCHANGED — reused as the sole observation model (goal #7).
```

`OwnedDisc` is structurally unchanged (`brand`, `mold`, `cached`, `user`, `id`). It already caches
its own `Disc` snapshot per copy, which is exactly why locally-authored molds are first-class.

**Why `edition` is per-copy, not on the mold snapshot.** Edition (First Run, Tour Series, Limited
Edition, Factory Store) is a property of the physical *copy/run*, like plastic, color, and weight —
the mold's flight *design* is identical across editions, so it is not manufacturer flight data. The
decisive reason it lives on `UserData`: `refresh_from_db` rewrites the cached `Disc` from the
catalog, which knows nothing about your disc's edition, so on the mold snapshot it would be **wiped
on the next sync**. `UserData` means "per-copy facts about *your* disc" (plastic and weight are
objective physical facts too) — not "opinions."

### Which fields become nullable, and why flight is "special"

Flight (`speed/glide/turn/fade`) becomes `Optional` because it's the only manufacturer data the
**engine computes on**. `category`, `stability`, `release`, `program` are descriptive/reference —
already string/optional and never arithmetic'd. Flight is special to the **engine**, not the
**schema**: the schema just makes the four numbers honestly optional.

**Identity invariant:** `brand` and `mold` (a disc's `name`) must be non-empty — never absent. The
name must be the mold's **canonical** identity, never a decorated one (see the Identity principle
below).

### Identity principle for local molds

A locally-authored mold is keyed by its **canonical `(brand, mold)`** — the identity the production
mold will have — e.g. `brand="Gateway", mold="Comanche"`. Do **not** decorate the mold name with
prototype status, release month, plastic, or program (`"Comanche Prototype"`, `"Comanche NXTG"`,
`"Comanche 2026-07"` are all wrong). Those belong in their dedicated fields:

- prototype status → `release_status`
- program / release month → `program` / `release`
- plastic, weight, edition → `UserData`

This is not cosmetic: discbag joins molds to the catalog by `(brand, mold)`. Canonical naming is
what lets **v3 graduation** match a local prototype to the finalized DiscItDB entry when it appears
(`"Gateway"/"Comanche"` local ↔ `"Gateway"/"Comanche"` DB). Decorated names would never match, and
graduation would be impossible. `add --prototype` therefore rejects a **deterministically** decorated
name (one containing "prototype" or a `YYYY-MM` token); plastic decoration is documented-not-detected
(a plastic vocabulary would be unbounded and false-positive-prone).

### Completeness: derived, not stored

`has_flight` is a **derived property**, never a persisted boolean. Storing a `flight_complete`
flag would duplicate truth and drift (fill `fade`, forget the flag). `release_status` **is** stored
because it's provenance, not completeness — and the two are independent (Wizard OS).

`release_status` allowed values in v1: **`"production"`** and **`"prototype"`**. The field is a plain
string, so later values (e.g. `"test_flight"`) can be added with no schema change; v1 input
validation accepts only the two canonical values.

---

## Manufacturer notes and personal observations

- **Manufacturer claims** ("Excellent resistance to turn", "Long forward push", "Floats in water")
  are stored verbatim in **`Disc.manufacturer_notes: List[str]`** — lossless, on the manufacturer
  side, distinct from `UserData.notes` (which is yours). v1 does **not** parse them into any
  structured class (that curated coarse class is a v2 field; see Future compatibility). A stated
  weight *range* ("160–163 g") is recorded as a manufacturer note in v1; the user's own copy weight
  goes in `UserData.weight` as usual.
- **Personal observations** reuse **`UserData.personal_flight`** unchanged — no new observation
  model. Throw the prototype for months, record your numbers there; they already override the model
  everywhere (see precedence).

**Invariant — `manufacturer_notes` are manufacturer-attributed only.** They hold statements the
manufacturer made; they are never a home for your commentary, which stays in `UserData.notes` and
`personal_flight`. This is enforced **structurally by the write paths**: `--manufacturer-note`
appends here, `--notes` writes your personal note, and no path routes user commentary into
`manufacturer_notes`. They remain **editable** — you may fix a transcription typo, or (in v3)
replace them with the catalog's official description on graduation — so the invariant is about
*whose statement it is*, not technical immutability.

---

## Flight precedence and the "Unknown" gate

A single predicate governs eligibility for flight reasoning:

```python
# discbag/roles.py
def _personal_complete(disc):
    p = getattr(getattr(disc, "user", None), "personal_flight", None)
    return bool(p) and all(p.get(k) is not None for k in ("speed", "glide", "turn", "fade"))

def _manufacturer_complete(disc):
    return all(getattr(disc, k, None) is not None for k in ("speed", "glide", "turn", "fade"))

def flight_known(disc):
    """We have complete flight to reason with: the player's recorded personal_flight, or the
    mold's published manufacturer numbers. Works on OwnedDisc (delegates) and bare Disc."""
    return _personal_complete(disc) or _manufacturer_complete(disc)
```

**Precedence (unchanged from today, tightened for None-safety):** complete **`personal_flight`** →
else complete **manufacturer** flight → else **Unknown**. `effective_flight`/`behaves_flight` are
only called on `flight_known(disc)` discs; `effective_flight` uses `personal_flight` only when it's
**complete**, else the (complete) manufacturer numbers.

A disc where `flight_known` is False is **Unknown**: present everywhere except flight math.

---

## Behavior of every flight-dependent subsystem when values are incomplete

**v1 rule:** each flight subsystem **filters its input to `flight_known` discs** before any flight
arithmetic; Unknown discs are silently skipped there (optionally surfaced with a one-line "N
prototype/incomplete disc(s) not shown — flight not yet published"). Everything non-flight includes
them.

| Subsystem | File | v1 behavior with an Unknown disc |
|-----------|------|----------------------------------|
| Role coverage / `best_next` / priority | `roles.py` (`assess`, `qualifies`, `fit_score`, `stability_number`, `_bag_behaves_overstable`) | filtered out before role fitting — an Unknown disc fills no role and doesn't skew "bag behaves overstable" |
| `overlap` | `analysis.py` (`_flight_distance`) | filtered out — no distance math on Unknown |
| `compare` | `analysis.py` (`compare`, `compare_verdict`) | Unknown disc's numeric rows render `—`; verdict says flight not yet published; no stability/overlap claim |
| `choose` | `analysis.py` (`_shot_score`) | filtered out of candidates |
| `practice` | `analysis.py` (`_practice_score`) | filtered out |
| `build-bag` | `recommend.py` (`build_bag`, `score_disc`, `_selection_score`, `_stability`, `_overpower`) | filtered out — never selected to fill a role |
| `maturity` | `maturity.py` (`_broad_category`, stability signals, `observed_preferences`, concentration) | flight-derived signals filter out Unknown discs; usage/favorites/coverage still count them |
| player power model | `player.py` (`adjusted_numbers`, `_overpower`) | only ever invoked on `flight_known` discs |
| charts | `chart.py`, `braille.py` (`stability`, scatter) | Unknown discs skipped from flight plots |
| `show` / `list` | `cli.py` (`format_owned`, `_print_disc_row`, `flight_str`) | render `?`/`—` for `None`; show `release_status`, `program`/`release`, `manufacturer_notes`, `edition` |

This also fixes a **latent crash**: `db.update_db` already writes `None` for an unparseable flight
field (`db.py:146`), which today would blow up `float(disc.speed)`. The filter hardens that path.

---

## Local molds and database sync

**Reframe:** the inventory **owns** its mold snapshots; the DB is a **reference** that seeds and
refreshes the matching ones. Locally-authored molds (prototypes, homemade, overmolds, club runs)
are first-class, marked `origin="local"`.

- **`add` a mold with no DB match** succeeds (see CLI) instead of failing/forcing full manual stats.
- **`sync` / `refresh_from_db`** (`db.py`, `inventory.refresh_from_db`) refresh **only molds whose
  `origin` matches the catalog being refreshed.** **v1 implements the DiscItDB refresh only:** it
  updates `origin=="discit"` molds and **skips every other origin** — `origin=="local"` is never
  auto-refreshed (its provenance and partial specs are authoritative), and any future catalog is
  skipped until its own refresh exists. `refresh_from_db` already no-ops on no name match; v1 adds
  the explicit origin check so a coincidental same-name DB mold can't clobber a local one (that
  reconciliation is v3 graduation).
- Existing production discs keep `origin="discit"` and refresh exactly as today.

---

## CLI behavior

### `add` (author a local prototype / partial mold)

```
discbag add Comanche --brand Gateway --prototype --speed 10 \
    --plastic "NXTG / NXT Lite Blend" --program "Premier Membership" --release 2026-07 \
    --manufacturer-note "Experimental Comanche top" --manufacturer-note "Excellent resistance to turn" \
    --manufacturer-note "Long forward push" --manufacturer-note "Dependable fade"
```

- **`--prototype`** authors the disc as a **local prototype** (`origin="local"`, `release_status="prototype"`),
  and **bypasses the DB-match requirement**. Without it, `add` behaves exactly as today.
- Individual flight flags **`--speed/--glide/--turn/--fade`** set only the numbers you have; omitted
  ones stay `None` (never `0`). (Alternatively `--flight 3/3/0/2.5` sets all four.)
- **`--brand`** supplies the manufacturer (the positional is the mold name, so multi-word brands
  like "Latitude 64" are unambiguous). Optional **`--category`**.
- **`--program` / `--release`** set provenance; **`--manufacturer-note`** (repeatable) appends manufacturer
  notes. Existing **`--notes`** remains *your* personal note; **`--edition`** sets the per-copy label.

Output: `Added Gateway Comanche in NXTG / NXT Lite Blend (prototype — flight not yet published).`

The **Floating Comanche** is the same mold, a second copy:
`discbag add Comanche --brand Gateway --prototype --speed 10 --plastic "Floating Sure Grip" --weight 161 --program "Premier Membership" --release 2026-07 --manufacturer-note "Floats in water"`

**Wizard OS** (prototype provenance, complete flight — the independence case):
`discbag add "Wizard OS" --brand Gateway --prototype --flight 3/3/0/2.5 --plastic "Double-SS Coffee Blend" --program "Premier Membership" --release 2026-07 --manufacturer-note "Scented" --manufacturer-note "Blunt nose" --manufacturer-note "Subtle thumb track"`
→ `flight_known = True` → participates in every analysis command normally.

### `edit` (fill in numbers as they're published; adjust provenance)

`discbag edit comanche --turn -1 --fade 2 --glide 5` fills fields individually (they stay `None`
until set). `discbag edit comanche --release-status production` marks it finalized. (v1: manual;
automated graduation is v3.) `edit` never fabricates and never touches history.

### `list` / `show` / discovery

- `list` renders an Unknown disc's flight as `?` (or `—`) and marks it `(prototype)`.
- **`list --prototype`** — a thin filter for `release_status="prototype"`, satisfying the "prototype
  list" idea without a separate command tree.
- `show` displays the full picture (see output examples).

---

## Output examples

```
$ discbag add Comanche --brand Gateway --prototype --speed 10 --plastic "NXTG / NXT Lite Blend" \
      --program "Premier Membership" --release 2026-07 --manufacturer-note "Excellent resistance to turn"
Added Gateway Comanche in NXTG / NXT Lite Blend (prototype — flight not yet published).

$ discbag show comanche
Gateway Comanche  [NXTG / NXT Lite Blend]   (Prototype)
  Flight:        not yet published (speed 10, glide/turn/fade pending)
  Program:       Premier Membership (2026-07)
  Manufacturer:  Experimental Comanche top
                 Excellent resistance to turn
                 Long forward push
                 Dependable fade
  Status:        Active
  Uses:          0

$ discbag list --prototype
Your inventory (3 prototypes):

  Gateway Comanche [NXTG / NXT Lite Blend]  (prototype)
      ? / ? / ? / ?   speed 10   flight not yet published
  Gateway Comanche [Floating Sure Grip]  (prototype)
      ? / ? / ? / ?   speed 10   flight not yet published
  Gateway Wizard OS [Double-SS Coffee Blend]  (prototype)
      3 / 3 / 0 / 2.5   Putter  (overstable)

$ discbag choose --distance 300
For 300 ft:
  ✓ Innova Wraith  (11 / 5 / -1 / 3)
  ...
Note: 2 prototype disc(s) not considered — flight not yet published.
```

`show` on Wizard OS looks like a normal disc plus a `(Prototype)` badge and its Program line — its
`3/3/0/2.5` are real, so it appears in `choose`/`recommend`/`overlap` like any disc.

---

## Serialization, backward compatibility, migration

- **`to_dict` / `from_dict`** already use `asdict` + a known-field filter. New fields serialize with
  defaults; **old inventory JSON loads with `release_status="production"`, `origin="discit"`,
  `manufacturer_notes=[]`, `edition=""`**, and existing stored flight numbers → `has_flight=True`.
- **No data migration is required.** Every existing owned disc has explicit flight numbers persisted
  in its `cached` block, so none become `None` on load; behavior is byte-for-byte the same
  (goal #8). The only defaults change is *in-code construction* of a `Disc` without flight (now
  `None` instead of `0`) — the plan audits/updates any test that constructed a bare `Disc` and
  relied on `0`.
- Forward compatibility is preserved because all additions are **optional fields with safe defaults**
  and **reuse of existing structures** (`personal_flight`, the event log). No nested restructuring.

---

## Validation rules (v1)

- **Identity:** `--brand` and mold name required and non-empty for `--prototype` authoring. The mold
  name must be canonical — reject a **deterministically** decorated name: one containing "prototype"
  (case-insensitive) or a `\d{4}-\d{2}` release-date token, so v3 graduation can match by
  `(brand, mold)`. Plastic decoration is **documented as disallowed, not pattern-detected** (detecting
  plastics needs an unbounded vocabulary and risks false positives on real mold names).
- **`release_status`** ∈ {`production`, `prototype`} on input (stored strings are otherwise untouched).
- **Flight flags** each parse as a number if given; any subset may be omitted → `None`. Never coerced
  to `0`. (`--flight S/G/T/F` requires all four.)
- **`--release`** validates as `YYYY-MM` when provided (a strict check, mirroring `_iso_date`).
- **`origin`** is an **open string**, not a closed enum — it is *not* validated against a fixed set.
  `--prototype` sets it to `local`; catalog imports set their own identifier.
- No validation *forces* completeness — an all-unknown disc is a legal inventory entry.

---

## Subsystems requiring modification (implementation scope, visible up front)

1. **`inventory.py`** — `Disc` flight → `Optional`; new `Disc` fields + `has_flight`; `UserData.edition`;
   `from_db_record`/`from_dict`/`to_dict` carry the new fields; `refresh_from_db` skips `origin="local"`.
2. **`roles.py`** — add `flight_known`/`_personal_complete`/`_manufacturer_complete`; make
   `effective_flight`/`behaves_flight` None-safe (complete-personal else manufacturer); `assess`,
   `qualifies`, `fit_score`, `stability_number`, `best_next`, `_bag_behaves_overstable`,
   `primary_role` filter/guard on `flight_known`.
3. **`analysis.py`** — `overlap`, `compare`/`compare_verdict`, `choose`, `practice` filter to
   `flight_known`; compare renders `—` for `None`.
4. **`recommend.py`** — `build_bag`, `score_disc`, `_selection_score`, `_stability`, `_overpower`
   operate only on `flight_known` discs.
5. **`maturity.py`** — `_broad_category`, `_stability_group`, `observed_preferences`, concentration,
   and any flight-derived signal filter to `flight_known`; non-flight signals unaffected.
6. **`player.py`** — `adjusted_numbers`, `_overpower`, `_overstability_shift` only ever receive
   `flight_known` discs (callers guarantee it).
7. **`chart.py` / `braille.py`** — `stability` and the scatter skip Unknown discs.
8. **`db.py`** — `refresh_manufacturer`/sync respects `origin="local"`; (already writes `None` on
   parse failure — now safe).
9. **`cli.py`** — `flight_str` renders `None`; `format_owned` (`show`) and `_print_disc_row` (`list`)
   show provenance/notes/incomplete flight; `cmd_add` gains `--prototype`, `--brand`, per-field flight
   flags, `--program`, `--release`, `--manufacturer-note`, `--edition`, and a local-authoring path; `cmd_edit`
   allows setting flight fields, `--release-status`, provenance, notes; `list` gains `--prototype`;
   analysis commands emit the "N not considered" note. New `_iso_month` validator (`YYYY-MM`).

---

## Tests and acceptance criteria

- **Honest nulls:** authoring a prototype with only `--speed 10` stores `glide/turn/fade = None`
  (never `0`) and round-trips through JSON.
- **Unknown gate:** a `flight_known=False` disc is excluded from `choose`, `overlap`, `build-bag`,
  `practice`, role coverage, and maturity's flight signals — and is still present in `list`, `show`,
  `bag`, usage, favorites, status/lifecycle, notes.
- **Independence (Wizard OS):** `release_status="prototype"` with complete flight → `has_flight=True`,
  `flight_known=True`, participates in `choose`/`overlap`/coverage exactly like a production disc.
- **personal_flight bridge:** an incomplete-manufacturer disc with a **complete** `personal_flight`
  → `flight_known=True`, reasoned on the player's numbers (existing precedence).
- **Two copies, one mold:** the NXTG and Floating Comanche are two `OwnedDisc`s sharing mold
  "Comanche", each with its own plastic/weight/flight snapshot.
- **Sync safety:** `refresh_from_db`/`sync` never overwrites a `origin="local"` disc, even if a
  same-name DB mold exists.
- **Backward compat / no migration:** an old inventory.json (no new fields, flight numbers present)
  loads unchanged; every existing command test stays green (goal #8).
- **Rendering:** `flight_str`/`show`/`list` render `None` gracefully (`?`/`—`, "not yet published").
- **Validation:** bad `--release-status`, malformed `--release`, and (unchanged) numeric flags are
  rejected at parse time.
- **Notes separation:** `--manufacturer-note` writes only `manufacturer_notes`; `--notes` writes
  only `UserData.notes`; there is no path from either into the other's field.
- **Canonical identity:** authoring a local mold named `"Comanche Prototype"` (or `"Comanche 2026-07"`)
  is rejected; `"Comanche"` with `--brand Gateway --prototype` is accepted and keyed `(Gateway, Comanche)`.
- **Edition survives sync:** a disc with `edition="First Run"` keeps it after `refresh_from_db`/`sync`
  (edition is `UserData`, untouched by a manufacturer refresh).
- **Fixtures:** the three Gateway examples (Comanche NXTG, Floating Comanche, Wizard OS) are shared
  test fixtures with the exact known/unknown fields from the brief.

---

## Future compatibility (designed for, not built)

- **v2 — coarse reasoning:** add an *optional, human-curated* `manufacturer_class` (a stability/
  character enum) to `Disc`, and a **precision tier** derived from `{personal_complete,
  manufacturer_complete, manufacturer_class, speed-only}`. Commands grow tier-awareness so a
  speed-10 + `overstable` Comanche can participate as a **low-confidence** driver. Nothing in v1
  blocks this: `release_status`, `manufacturer_notes`, and `Optional` flight are already present; v2
  adds one field and a derived tier, no model rewrite.
- **v3 — graduation & conflict resolution:** graduation is recorded as an **event on the existing
  `UserData.events` log** (like lost/damaged), flips `release_status`→`production` and possibly
  `origin`→`discit`, fills flight from the DB, and **keeps provenance as history** (never "sync and
  forget"). Conflict resolution (local vs DiscItDB divergence) reuses the same event trail. The v1
  `origin` field and event log are the hooks; no migration needed.

## Explicit v1 non-goals

Automated coarse reasoning, precision/confidence tiers, inferred flight numbers, automated
graduation, prototype-specific command trees (only the thin `list --prototype` filter), and any
collectible/merchandise tracking.
