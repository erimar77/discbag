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
| **Provenance / release** | Is this an experimental/limited release, and from where? | **Stored** (`spec_status`, `program`, `release`) | prototype, Premier, 2026-07 | prototype, Premier, 2026-07 | production |

Wizard OS is the acceptance-critical case: **`spec_status = prototype` with complete flight** —
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
    spec_status: str = "production"       # "production" | "prototype"
    source: str = "db"                    # "db" | "local"
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

### Which fields become nullable, and why flight is "special"

Flight (`speed/glide/turn/fade`) becomes `Optional` because it's the only manufacturer data the
**engine computes on**. `category`, `stability`, `release`, `program` are descriptive/reference —
already string/optional and never arithmetic'd. Flight is special to the **engine**, not the
**schema**: the schema just makes the four numbers honestly optional.

**Identity invariant:** `brand` and `mold` (a disc's `name`) must be non-empty. A name may be
*provisional* ("Comanche Prototype") but never absent. This single invariant is what keeps
"everything optional" from becoming a meaningless empty record.

### Completeness: derived, not stored

`has_flight` is a **derived property**, never a persisted boolean. Storing a `flight_complete`
flag would duplicate truth and drift (fill `fade`, forget the flag). `spec_status` **is** stored
because it's provenance, not completeness — and the two are independent (Wizard OS).

`spec_status` allowed values in v1: **`"production"`** and **`"prototype"`**. The field is a plain
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
| `show` / `list` | `cli.py` (`format_owned`, `_print_disc_row`, `flight_str`) | render `?`/`—` for `None`; show `spec_status`, `program`/`release`, `manufacturer_notes`, `edition` |

This also fixes a **latent crash**: `db.update_db` already writes `None` for an unparseable flight
field (`db.py:146`), which today would blow up `float(disc.speed)`. The filter hardens that path.

---

## Local molds and database sync

**Reframe:** the inventory **owns** its mold snapshots; the DB is a **reference** that seeds and
refreshes the matching ones. Locally-authored molds (prototypes, homemade, overmolds, club runs)
are first-class, marked `source="local"`.

- **`add` a mold with no DB match** succeeds (see CLI) instead of failing/forcing full manual stats.
- **`sync` / `refresh_from_db`** (`db.py`, `inventory.refresh_from_db`) **must never overwrite a
  `source="local"` disc** — its provenance and partial specs are authoritative. `refresh_from_db`
  already no-ops on no name match; v1 adds an explicit `source == "local"` skip so a coincidental
  same-name DB mold can't clobber a local one (that reconciliation is v3 graduation).
- Existing production discs keep `source="db"` and refresh exactly as today.

---

## CLI behavior

### `add` (author a local prototype / partial mold)

```
discbag add Comanche --brand Gateway --prototype --speed 10 \
    --plastic "NXTG / NXT Lite Blend" --program "Premier Membership" --release 2026-07 \
    --spec-note "Experimental Comanche top" --spec-note "Excellent resistance to turn" \
    --spec-note "Long forward push" --spec-note "Dependable fade"
```

- **`--prototype`** authors the disc as a **local prototype** (`source="local"`, `spec_status="prototype"`),
  and **bypasses the DB-match requirement**. Without it, `add` behaves exactly as today.
- Individual flight flags **`--speed/--glide/--turn/--fade`** set only the numbers you have; omitted
  ones stay `None` (never `0`). (Alternatively `--flight 3/3/0/2.5` sets all four.)
- **`--brand`** supplies the manufacturer (the positional is the mold name, so multi-word brands
  like "Latitude 64" are unambiguous). Optional **`--category`**.
- **`--program` / `--release`** set provenance; **`--spec-note`** (repeatable) appends manufacturer
  notes. Existing **`--notes`** remains *your* personal note; **`--edition`** sets the per-copy label.

Output: `Added Gateway Comanche in NXTG / NXT Lite Blend (prototype — flight not yet published).`

The **Floating Comanche** is the same mold, a second copy:
`discbag add Comanche --brand Gateway --prototype --speed 10 --plastic "Floating Sure Grip" --weight 161 --program "Premier Membership" --release 2026-07 --spec-note "Floats in water"`

**Wizard OS** (prototype provenance, complete flight — the independence case):
`discbag add "Wizard OS" --brand Gateway --prototype --flight 3/3/0/2.5 --plastic "Double-SS Coffee Blend" --program "Premier Membership" --release 2026-07 --spec-note "Scented" --spec-note "Blunt nose" --spec-note "Subtle thumb track"`
→ `flight_known = True` → participates in every analysis command normally.

### `edit` (fill in numbers as they're published; adjust provenance)

`discbag edit comanche --turn -1 --fade 2 --glide 5` fills fields individually (they stay `None`
until set). `discbag edit comanche --spec-status production` marks it finalized. (v1: manual;
automated graduation is v3.) `edit` never fabricates and never touches history.

### `list` / `show` / discovery

- `list` renders an Unknown disc's flight as `?` (or `—`) and marks it `(prototype)`.
- **`list --prototype`** — a thin filter for `spec_status="prototype"`, satisfying the "prototype
  list" idea without a separate command tree.
- `show` displays the full picture (see output examples).

---

## Output examples

```
$ discbag add Comanche --brand Gateway --prototype --speed 10 --plastic "NXTG / NXT Lite Blend" \
      --program "Premier Membership" --release 2026-07 --spec-note "Excellent resistance to turn"
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
  defaults; **old inventory JSON loads with `spec_status="production"`, `source="db"`,
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

- **Identity:** `--brand` and mold name required and non-empty for `--prototype` authoring.
- **`spec_status`** ∈ {`production`, `prototype`} on input (stored strings are otherwise untouched).
- **Flight flags** each parse as a number if given; any subset may be omitted → `None`. Never coerced
  to `0`. (`--flight S/G/T/F` requires all four.)
- **`--release`** validates as `YYYY-MM` when provided (reuse a strict check like `_iso_date`'s).
- **`source`** ∈ {`db`, `local`}; `--prototype` sets `local`.
- No validation *forces* completeness — an all-unknown disc is a legal inventory entry.

---

## Subsystems requiring modification (implementation scope, visible up front)

1. **`inventory.py`** — `Disc` flight → `Optional`; new `Disc` fields + `has_flight`; `UserData.edition`;
   `from_db_record`/`from_dict`/`to_dict` carry the new fields; `refresh_from_db` skips `source="local"`.
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
8. **`db.py`** — `refresh_manufacturer`/sync respects `source="local"`; (already writes `None` on
   parse failure — now safe).
9. **`cli.py`** — `flight_str` renders `None`; `format_owned` (`show`) and `_print_disc_row` (`list`)
   show provenance/notes/incomplete flight; `cmd_add` gains `--prototype`, `--brand`, per-field flight
   flags, `--program`, `--release`, `--spec-note`, `--edition`, and a local-authoring path; `cmd_edit`
   allows setting flight fields, `--spec-status`, provenance, notes; `list` gains `--prototype`;
   analysis commands emit the "N not considered" note. New `_iso_month` validator (`YYYY-MM`).

---

## Tests and acceptance criteria

- **Honest nulls:** authoring a prototype with only `--speed 10` stores `glide/turn/fade = None`
  (never `0`) and round-trips through JSON.
- **Unknown gate:** a `flight_known=False` disc is excluded from `choose`, `overlap`, `build-bag`,
  `practice`, role coverage, and maturity's flight signals — and is still present in `list`, `show`,
  `bag`, usage, favorites, status/lifecycle, notes.
- **Independence (Wizard OS):** `spec_status="prototype"` with complete flight → `has_flight=True`,
  `flight_known=True`, participates in `choose`/`overlap`/coverage exactly like a production disc.
- **personal_flight bridge:** an incomplete-manufacturer disc with a **complete** `personal_flight`
  → `flight_known=True`, reasoned on the player's numbers (existing precedence).
- **Two copies, one mold:** the NXTG and Floating Comanche are two `OwnedDisc`s sharing mold
  "Comanche", each with its own plastic/weight/flight snapshot.
- **Sync safety:** `refresh_from_db`/`sync` never overwrites a `source="local"` disc, even if a
  same-name DB mold exists.
- **Backward compat / no migration:** an old inventory.json (no new fields, flight numbers present)
  loads unchanged; every existing command test stays green (goal #8).
- **Rendering:** `flight_str`/`show`/`list` render `None` gracefully (`?`/`—`, "not yet published").
- **Validation:** bad `--spec-status`, malformed `--release`, and (unchanged) numeric flags are
  rejected at parse time.
- **Fixtures:** the three Gateway examples (Comanche NXTG, Floating Comanche, Wizard OS) are shared
  test fixtures with the exact known/unknown fields from the brief.

---

## Future compatibility (designed for, not built)

- **v2 — coarse reasoning:** add an *optional, human-curated* `manufacturer_class` (a stability/
  character enum) to `Disc`, and a **precision tier** derived from `{personal_complete,
  manufacturer_complete, manufacturer_class, speed-only}`. Commands grow tier-awareness so a
  speed-10 + `overstable` Comanche can participate as a **low-confidence** driver. Nothing in v1
  blocks this: `spec_status`, `manufacturer_notes`, and `Optional` flight are already present; v2
  adds one field and a derived tier, no model rewrite.
- **v3 — graduation & conflict resolution:** graduation is recorded as an **event on the existing
  `UserData.events` log** (like lost/damaged), flips `spec_status`→`production` and possibly
  `source`→`db`, fills flight from the DB, and **keeps provenance as history** (never "sync and
  forget"). Conflict resolution (local vs DiscItDB divergence) reuses the same event trail. The v1
  `source` field and event log are the hooks; no migration needed.

## Explicit v1 non-goals

Automated coarse reasoning, precision/confidence tiers, inferred flight numbers, automated
graduation, prototype-specific command trees (only the thin `list --prototype` filter), and any
collectible/merchandise tracking.
