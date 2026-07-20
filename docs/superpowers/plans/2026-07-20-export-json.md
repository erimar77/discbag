# `discbag export` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `discbag export`, a command emitting a deterministic, portable JSON snapshot (schema v1.0) of the user's collection and every analysis the engine already computes.

**Architecture:** A new leaf module `discbag/export.py` exposes one pure function, `build_export()`, which calls existing engine functions and reshapes their results into JSON-safe structures. Both clocks are injected so output is byte-reproducible. Two small engine additions give identity and situation-aliasing a proper home (`db.catalog_id`, `roles.canonical_situations`), and one prerequisite refactor splits `analysis.compare_verdict()` into structured meaning (engine) plus prose rendering (CLI).

**Tech Stack:** Python 3.9+, stdlib only (`json`, `dataclasses`, `datetime`, `ast`). pytest for tests. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-20-export-json-design.md` (commit `99f9cbe`). Read it before starting.

## Global Constraints

- **`export.py` creates no knowledge.** It serializes existing engine results. A threshold, comparison, classification, or scoring rule appearing in `export.py` is a defect. Rename fields for schema clarity; never interpret values.
- **`export.py` never calls `datetime.now()`.** Both `analysis_date` and `generated_at` are injected keyword-only arguments.
- **Import direction:** `export.py` may import `roles`, `analysis`, `recommend`, `maturity`, `player`, `db`, `inventory`, `history`, and the stdlib. No engine module may import `export`.
- **Layering:** the engine returns meaning, the CLI renders prose, the export serializes structure.
- **Schema version is `"1.0"`** for all of this work.
- **`analysis_defaults` mirrors the CLI exactly:** `{"goal": "coverage", "bag_size": None, "rotate": False}`.
- **Canonical scenarios are `windy`, `minimal`, `woods`.** There is no `technical` or `open` scenario.
- **No invented relationship taxonomy.** No `kind` field with values like `backup`, `similar`, `more_stable`, or `complement`.
- **All top-level keys are always present**, including for empty inventory and absent profile. Never emit a partial export.
- **`null` vs empty:** empty array/object means the report ran and had no results; `null` means the concept exists but could not be calculated.
- **Every list with no semantic order is explicitly sorted.** `sort_keys=True` stabilizes object keys only, never array order.
- **CLI `compare` output must remain byte-identical** after the Task 2 refactor.
- Run tests with `. .venv/bin/activate` active, from the repo root `/Users/ericmartin/Desktop/discbag`.

---

### Task 1: `catalog_id()` in `db.py`

Catalog records carry no identifier. Identity of a catalog record belongs to the module that owns the catalog, not to serialization.

**Files:**
- Modify: `discbag/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `db.catalog_id(record) -> str`. Accepts either a catalog record `dict` (keys `brand`, `name`) or any object with `.brand` and `.name` attributes (`Disc`, `OwnedDisc`). Returns a lowercase hyphen slug, e.g. `"gateway-wizard"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
# ---------- catalog_id ----------

def test_catalog_id_from_record_dict():
    assert db.catalog_id({"brand": "Gateway", "name": "Wizard"}) == "gateway-wizard"


def test_catalog_id_normalizes_case_space_and_punctuation():
    assert db.catalog_id({"brand": "Lone Star Discs", "name": "Artemis"}) == \
        "lone-star-discs-artemis"
    assert db.catalog_id({"brand": "Innova", "name": "Mako3"}) == "innova-mako3"
    assert db.catalog_id({"brand": "Gateway", "name": "Wizard SS"}) == "gateway-wizard-ss"


def test_catalog_id_accepts_an_object_with_brand_and_name():
    from discbag.inventory import Disc
    d = Disc(name="Wizard", brand="Gateway", category="Putter",
             speed=2, glide=3, turn=0, fade=2)
    assert db.catalog_id(d) == "gateway-wizard"


def test_catalog_id_omits_empty_parts_without_leaving_a_stray_hyphen():
    assert db.catalog_id({"brand": "", "name": "Wizard"}) == "wizard"
    assert db.catalog_id({"brand": "Gateway", "name": ""}) == "gateway"


def test_catalog_id_is_deterministic():
    rec = {"brand": "Gateway", "name": "Wizard"}
    assert db.catalog_id(rec) == db.catalog_id(rec)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_db.py -k catalog_id -v`
Expected: FAIL with `AttributeError: module 'discbag.db' has no attribute 'catalog_id'`

- [ ] **Step 3: Implement**

Add to `discbag/db.py`, after `normalize_name`:

```python
def _slug(value):
    """Lowercase alphanumeric runs joined by single hyphens."""
    out, prev_hyphen = [], True
    for ch in str(value or "").lower():
        if ch.isalnum():
            out.append(ch)
            prev_hyphen = False
        elif not prev_hyphen:
            out.append("-")
            prev_hyphen = True
    return "".join(out).strip("-")


def catalog_id(record):
    """Stable identifier for a catalog mold, derived from brand + name.

    Accepts a raw catalog record dict or any object exposing .brand/.name
    (Disc, OwnedDisc). Stable only while the upstream brand and mold name are
    unchanged: a catalog rename changes the derived id in schema v1.
    """
    if isinstance(record, dict):
        brand, name = record.get("brand"), record.get("name")
    else:
        brand, name = getattr(record, "brand", ""), getattr(record, "name", "")
    return "-".join(p for p in (_slug(brand), _slug(name)) if p)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (all, including pre-existing tests)

- [ ] **Step 5: Commit**

```bash
git add discbag/db.py tests/test_db.py
git commit -m "Add db.catalog_id: stable brand+name slug for catalog molds"
```

---

### Task 2: Refactor `compare_verdict()` to return structured data

Prerequisite refactor. The engine currently returns one terminal-formatted blob; a public schema must not carry CLI prose formatting.

**Files:**
- Modify: `discbag/analysis.py:186-205` (`compare_verdict`)
- Modify: `discbag/cli.py:1293-1310` (`cmd_compare`)
- Test: `tests/test_analysis.py:90-172` (adapt the 11 existing verdict tests)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `analysis.CompareVerdict` — frozen dataclass with fields `overlap_text: str|None`, `key_difference: str|None`, `how_to_use: str|None`, `degraded_note: str|None`.
  - `analysis.compare_verdict(discs) -> CompareVerdict | None` — `None` for fewer than two discs or incomplete manufacturer flight (unchanged); a `CompareVerdict` with only `degraded_note` set for three or more; all three prose fields set and `degraded_note=None` for exactly two.
  - `cli.render_compare_verdict(verdict) -> str` — reproduces the current output byte-for-byte.

- [ ] **Step 1: Adapt the existing verdict tests to assert on rendered text**

The 11 existing tests assert `"..." in v` against the returned string. Keep every assertion — routing them through the renderer is what proves byte-identical output.

In `tests/test_analysis.py`, add this helper immediately below the `# ---------- compare_verdict ----------` banner on line 90:

```python
def verdict_text(discs):
    """The rendered verdict, so the existing wording assertions keep testing
    exactly what the CLI prints."""
    from discbag.cli import render_compare_verdict
    v = analysis.compare_verdict(discs)
    return None if v is None else render_compare_verdict(v)
```

Then in each of the 11 tests below it, replace `analysis.compare_verdict(` with `verdict_text(`. For example:

```python
def test_verdict_two_discs_has_three_labeled_sections():
    v = verdict_text([WAVE, WRAITH])
    assert "Bottom line" in v
    assert "Overlap:" in v
    assert "Key difference:" in v
    assert "How to use them:" in v
```

Leave every `assert` line untouched.

- [ ] **Step 2: Add structured-shape tests**

Append to `tests/test_analysis.py`:

```python
def test_verdict_returns_structured_fields_for_two_discs():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert v.degraded_note is None
    assert "same broad distance driver slot" in v.overlap_text.lower()
    assert "The Wave has more high-speed turn and a gentler finish." in v.key_difference
    assert "finish left more strongly" in v.how_to_use


def test_verdict_structured_contains_no_section_headings():
    # Headings are presentation and belong to the CLI renderer, not the engine.
    v = analysis.compare_verdict([WAVE, WRAITH])
    for text in (v.overlap_text, v.key_difference, v.how_to_use):
        assert "Bottom line" not in text
        assert "Overlap:" not in text
        assert "Key difference:" not in text
        assert "How to use them:" not in text


def test_verdict_three_plus_sets_only_degraded_note():
    third = Disc(name="Firebird", brand="Innova", category="Distance Driver",
                 speed=9, glide=3, turn=0, fade=4)
    v = analysis.compare_verdict([WAVE, WRAITH, third])
    assert v.overlap_text is None
    assert v.key_difference is None
    assert v.how_to_use is None
    assert "Most similar:" in v.degraded_note


def test_verdict_none_for_fewer_than_two_discs():
    assert analysis.compare_verdict([WAVE]) is None
    assert analysis.compare_verdict([]) is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_analysis.py -k verdict -v`
Expected: FAIL — `ImportError: cannot import name 'render_compare_verdict'` and `AttributeError: 'str' object has no attribute 'degraded_note'`

- [ ] **Step 4: Change the engine to return meaning**

In `discbag/analysis.py`, add the dataclass above `compare_verdict`:

```python
@dataclass(frozen=True)
class CompareVerdict:
    """The rule-derived comparison result, as meaning rather than prose.

    Exactly two discs set the three text fields and leave degraded_note None;
    three or more set only degraded_note.
    """
    overlap_text: Optional[str] = None
    key_difference: Optional[str] = None
    how_to_use: Optional[str] = None
    degraded_note: Optional[str] = None
```

If `Optional` is not already imported in `analysis.py`, add `from typing import Optional` to its imports.

Replace the body of `compare_verdict` (currently `analysis.py:186-205`) with:

```python
def compare_verdict(discs):
    """A rule-derived bottom line. Three-part relative verdict for exactly two
    discs; a degraded note for 3+; None for fewer than two.

    Returns structured meaning; the CLI renders it for the terminal.
    """
    if len(discs) < 2:
        return None
    if not all(roles._manufacturer_complete(d) for d in discs):
        return None
    if len(discs) > 2:
        return CompareVerdict(degraded_note=_degraded_note(discs))
    a, b = discs
    return CompareVerdict(
        overlap_text=_overlap_text(a, b),
        key_difference=_trait_sentence(a, b) + " " + _trait_sentence(b, a),
        how_to_use=_how_to_use_text(a, b),
    )
```

- [ ] **Step 5: Move rendering into the CLI**

In `discbag/cli.py`, add above `cmd_compare` (currently line 1293):

```python
def render_compare_verdict(verdict):
    """The terminal form of a CompareVerdict. Presentation lives here, not in the engine."""
    if verdict.degraded_note is not None:
        return verdict.degraded_note
    return (
        "Bottom line\n\n"
        f"Overlap:\n{verdict.overlap_text}\n\n"
        f"Key difference:\n{verdict.key_difference}\n\n"
        f"How to use them:\n{verdict.how_to_use}"
    )
```

Then in `cmd_compare`, change:

```python
    verdict = analysis.compare_verdict(discs)
    if verdict:
        print()
        print(verdict)
```

to:

```python
    verdict = analysis.compare_verdict(discs)
    if verdict:
        print()
        print(render_compare_verdict(verdict))
```

- [ ] **Step 6: Run the full suite to verify nothing regressed**

Run: `python -m pytest tests/ -v`
Expected: PASS. The adapted wording tests passing is the byte-identical guarantee; `tests/test_cli.py` covers the command end-to-end.

- [ ] **Step 7: Commit**

```bash
git add discbag/analysis.py discbag/cli.py tests/test_analysis.py
git commit -m "compare_verdict returns structured meaning; CLI renders prose

Splits result determination from terminal formatting so the verdict can
enter a public export schema without carrying CLI presentation. Rendered
CLI output is unchanged, proven by routing the existing wording tests
through render_compare_verdict."
```

---

### Task 3: `export.py` envelope, profile, and degenerate inputs

Establishes the signature and the always-present top-level shape. Every later task fills a section in.

**Files:**
- Create: `discbag/export.py`
- Create: `tests/test_export.py`

**Interfaces:**
- Consumes: `db.catalog_id` (Task 1).
- Produces:
  - `export.SCHEMA_VERSION = "1.0"`
  - `export.build_export(inventory, profile, catalog, *, analysis_date, generated_at) -> dict` — `inventory` is a list of `OwnedDisc` (all discs, active and archived); `profile` is a `PlayerProfile` or `None`; `catalog` is the list of raw catalog record dicts; `analysis_date` is a `datetime.date`; `generated_at` is a `datetime.datetime`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_export.py`:

```python
from datetime import date, datetime

from discbag import export
from discbag.inventory import OwnedDisc
from discbag.player import PlayerProfile

ANALYSIS_DATE = date(2026, 7, 20)
GENERATED_AT = datetime(2026, 7, 20, 14, 32, 11)

TOP_LEVEL_KEYS = {"schema_version", "generated_at", "discbag_version",
                  "analysis_defaults", "reports_included", "profile",
                  "catalog", "inventory", "analysis"}

ANALYSIS_KEYS = {"coverage", "gaps", "overlap_groups", "pairwise_comparisons",
                 "goal_bags", "scenario_bags", "scenario_aliases", "maturity",
                 "next_purchase", "exclusions"}


def owned(name="Wizard", brand="Gateway", category="Putter",
          speed=2, glide=3, turn=0, fade=2, disc_id="id-wizard", **user_kwargs):
    """An OwnedDisc with a stable id, for deterministic export assertions."""
    d = OwnedDisc.from_db_record(
        {"name": name, "brand": brand, "category": category, "stability": "",
         "speed": speed, "glide": glide, "turn": turn, "fade": fade},
        **user_kwargs)
    d.id = disc_id
    return d


def build(inventory=None, profile=None, catalog=None):
    return export.build_export(
        inventory if inventory is not None else [],
        profile,
        catalog if catalog is not None else [],
        analysis_date=ANALYSIS_DATE,
        generated_at=GENERATED_AT,
    )


# ---------- envelope ----------

def test_envelope_has_every_top_level_key():
    assert set(build().keys()) == TOP_LEVEL_KEYS


def test_envelope_reports_schema_version_and_generated_at():
    out = build()
    assert out["schema_version"] == "1.0"
    assert out["generated_at"] == "2026-07-20T14:32:11Z"


def test_envelope_reports_discbag_version():
    from discbag import __version__
    assert build()["discbag_version"] == __version__


def test_analysis_defaults_mirror_the_cli():
    assert build()["analysis_defaults"] == {
        "goal": "coverage", "bag_size": None, "rotate": False}


def test_reports_included_matches_the_analysis_section_keys():
    out = build()
    # Every advertised report is a real analysis key.
    assert set(out["reports_included"]) <= set(out["analysis"].keys())


# ---------- profile ----------

def test_profile_is_null_when_unset():
    assert build()["profile"] is None


def test_profile_serializes_fields():
    p = PlayerProfile(name="Eric", max_distance=320, hand="right")
    out = build(profile=p)
    assert out["profile"]["name"] == "Eric"
    assert out["profile"]["max_distance"] == 320
    assert out["profile"]["hand"] == "right"


# ---------- degenerate inputs ----------

def test_empty_inventory_produces_a_complete_schema():
    out = build()
    assert set(out.keys()) == TOP_LEVEL_KEYS
    assert set(out["analysis"].keys()) == ANALYSIS_KEYS
    assert out["inventory"] == []
    assert out["catalog"] == {}


def test_empty_reports_use_empty_containers_not_null():
    a = build()["analysis"]
    for key in ("coverage", "gaps", "overlap_groups", "pairwise_comparisons", "exclusions"):
        assert a[key] == [], key
    for key in ("goal_bags", "scenario_bags", "scenario_aliases"):
        assert a[key] == {}, key


def test_export_never_calls_datetime_now():
    # Two calls with identical injected clocks must agree on every time field.
    first, second = build(), build()
    assert first["generated_at"] == second["generated_at"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -v`
Expected: FAIL with `ImportError: cannot import name 'export' from 'discbag'`

- [ ] **Step 3: Implement the envelope**

Create `discbag/export.py`:

```python
"""Serialize discbag's existing knowledge as a portable JSON snapshot (schema v1.0).

This module is a leaf: it imports from the engine, and nothing in the engine
imports it. It creates no knowledge. Every value here is either raw user data
or the return value of an existing engine function, reshaped into JSON-safe
structures. A threshold, comparison, classification, or scoring rule appearing
in this module is a defect.

Both clocks are injected. This module must never call datetime.now(): that is
what makes build_export() deterministic and byte-reproducible in tests.
"""

from dataclasses import asdict

from discbag import __version__

SCHEMA_VERSION = "1.0"

# Mirrors the CLI exactly: `build-bag` defaults to goal=coverage and applies no
# --size limit. A null bag_size means "no explicit size override", not a number.
ANALYSIS_DEFAULTS = {"goal": "coverage", "bag_size": None, "rotate": False}

# The analysis sections this schema version advertises, in a stable order.
REPORTS_INCLUDED = [
    "coverage",
    "gaps",
    "overlap_groups",
    "pairwise_comparisons",
    "goal_bags",
    "scenario_bags",
    "maturity",
    "next_purchase",
    "exclusions",
]


def _iso_z(moment):
    """UTC timestamp in the schema's fixed format."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _profile_dict(profile):
    return None if profile is None else asdict(profile)


def _empty_analysis():
    """Every analysis key, always present. Empty containers mean the report ran
    and had no results; None means a value could not be calculated."""
    return {
        "coverage": [],
        "gaps": [],
        "overlap_groups": [],
        "pairwise_comparisons": [],
        "goal_bags": {},
        "scenario_bags": {},
        "scenario_aliases": {},
        "maturity": None,
        "next_purchase": None,
        "exclusions": [],
    }


def build_export(inventory, profile, catalog, *, analysis_date, generated_at):
    """A complete, deterministic snapshot of the collection and its analysis.

    inventory     -- list of OwnedDisc, active and archived alike
    profile       -- PlayerProfile, or None if the user has not set one
    catalog       -- list of raw catalog record dicts
    analysis_date -- datetime.date driving date-sensitive analysis
    generated_at  -- datetime.datetime recorded as provenance only
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_z(generated_at),
        "discbag_version": __version__,
        "analysis_defaults": dict(ANALYSIS_DEFAULTS),
        "reports_included": list(REPORTS_INCLUDED),
        "profile": _profile_dict(profile),
        "catalog": {},
        "inventory": [],
        "analysis": _empty_analysis(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS (all 11)

- [ ] **Step 5: Commit**

```bash
git add discbag/export.py tests/test_export.py
git commit -m "export: envelope, profile, and complete schema for degenerate inputs"
```

---

### Task 4: Serialize `inventory[]` and the portable `catalog` map

**Files:**
- Modify: `discbag/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `db.catalog_id` (Task 1); `build_export` (Task 3).
- Produces: populated `out["inventory"]` (sorted by `inventory_id`) and `out["catalog"]` (keyed by `catalog_id`). Each inventory record has keys `inventory_id`, `catalog_id`, `mold`, `manufacturer`, `user`, `computed`, `history_summary`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
# ---------- inventory records ----------

def test_inventory_record_uses_the_existing_disc_id():
    out = build([owned(disc_id="1683a68e94dd4d1e913fb05f0fbacf32")])
    assert out["inventory"][0]["inventory_id"] == "1683a68e94dd4d1e913fb05f0fbacf32"


def test_inventory_record_separates_manufacturer_user_and_computed():
    out = build([owned(plastic="Firm", weight=175, favorite=True)])
    rec = out["inventory"][0]
    assert rec["mold"] == "Wizard"
    assert rec["catalog_id"] == "gateway-wizard"
    assert rec["manufacturer"]["brand"] == "Gateway"
    assert rec["manufacturer"]["flight"] == {"speed": 2, "glide": 3, "turn": 0, "fade": 2}
    assert rec["user"]["plastic"] == "Firm"
    assert rec["user"]["weight"] == 175
    assert rec["user"]["favorite"] is True
    assert rec["computed"]["flight_known"] is True


def test_computed_carries_both_flight_views():
    # effective_flight drives roles/fit; behaves_flight drives overlap/choose/practice.
    rec = build([owned()])["inventory"][0]
    assert rec["computed"]["effective_flight"] == {"speed": 2, "glide": 3, "turn": 0, "fade": 2}
    assert set(rec["computed"]["behaves_flight"]) == {"speed", "glide", "turn", "fade"}


def test_computed_carries_role_fit_stability_and_power():
    rec = build([owned()])["inventory"][0]
    assert rec["computed"]["primary_role"] == "Putting"
    assert isinstance(rec["computed"]["fit_score"], float)
    assert rec["computed"]["stability"] == 2          # turn 0 + fade 2
    assert isinstance(rec["computed"]["required_power"], float)


def test_history_summary_counts_rounds_and_practices():
    d = owned(use_dates=[{"date": "2026-07-07", "session_type": "round"},
                         {"date": "2026-07-01", "session_type": "practice"}],
              date_added="2025-03-11")
    rec = build([d])["inventory"][0]
    assert rec["history_summary"]["rounds"] == 1
    assert rec["history_summary"]["practices"] == 1
    assert rec["history_summary"]["last_used"] == "2026-07-07"
    assert rec["history_summary"]["acquired"] == "2025-03-11"


def test_incomplete_flight_disc_stays_visible_with_nulled_computed_fields():
    from tests.conftest import prototype_disc
    d = prototype_disc()
    d.id = "id-proto"
    d.user.personal_flight = None       # nothing recorded: genuinely unknown
    rec = build([d])["inventory"][0]
    assert rec["inventory_id"] == "id-proto"          # present, not dropped
    assert rec["computed"]["flight_known"] is False
    assert rec["computed"]["effective_flight"] is None
    assert rec["computed"]["primary_role"] is None
    assert rec["computed"]["fit_score"] is None


def test_archived_disc_stays_visible_with_its_status():
    rec = build([owned(status="lost", status_reason="creek")])["inventory"][0]
    assert rec["user"]["status"] == "lost"
    assert rec["user"]["status_reason"] == "creek"


def test_inventory_is_sorted_by_inventory_id():
    out = build([owned(disc_id="id-c"), owned(disc_id="id-a"), owned(disc_id="id-b")])
    assert [r["inventory_id"] for r in out["inventory"]] == ["id-a", "id-b", "id-c"]


# ---------- portable catalog map ----------

def test_catalog_map_holds_a_portable_summary_for_each_owned_mold():
    out = build([owned()])
    assert out["catalog"]["gateway-wizard"] == {
        "catalog_id": "gateway-wizard",
        "name": "Wizard",
        "brand": "Gateway",
        "category": "Putter",
        "stability": "",
        "flight": {"speed": 2, "glide": 3, "turn": 0, "fade": 2},
    }


def test_catalog_map_deduplicates_repeated_molds():
    out = build([owned(disc_id="id-1"), owned(disc_id="id-2")])
    assert list(out["catalog"]) == ["gateway-wizard"]


def test_catalog_map_excludes_unreferenced_records():
    unreferenced = {"name": "Destroyer", "brand": "Innova", "category": "Distance Driver",
                    "stability": "Overstable", "speed": 12, "glide": 5, "turn": -1, "fade": 3}
    out = build([owned()], catalog=[unreferenced])
    assert "innova-destroyer" not in out["catalog"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -k "inventory or catalog or computed or history or archived or incomplete" -v`
Expected: FAIL — `IndexError: list index out of range` (inventory is still `[]`)

- [ ] **Step 3: Implement**

In `discbag/export.py`, extend the imports:

```python
from dataclasses import asdict

from discbag import __version__, db, player, roles
```

Add these helpers above `build_export`:

```python
def _flight_dict(flight):
    """A Flight (or None) as JSON-safe numbers."""
    if flight is None:
        return None
    return {"speed": flight.speed, "glide": flight.glide,
            "turn": flight.turn, "fade": flight.fade}


def _catalog_summary(disc):
    """The deliberate portable summary of a mold, defined by the public schema.

    Deliberately not a dump of the internal catalog object: an export must
    render on a machine with no discs.json.
    """
    return {
        "catalog_id": db.catalog_id(disc),
        "name": disc.name,
        "brand": disc.brand,
        "category": disc.category,
        "stability": disc.stability,
        "flight": _flight_dict(roles.effective_flight(disc)) if roles.flight_known(disc)
                  else {"speed": disc.speed, "glide": disc.glide,
                        "turn": disc.turn, "fade": disc.fade},
    }


def _computed(disc, profile):
    """Engine conclusions about one disc. Every value is an existing engine
    result; unavailable ones are None rather than a substitute."""
    known = roles.flight_known(disc)
    if not known:
        return {"flight_known": False, "effective_flight": None, "behaves_flight": None,
                "stability": None, "primary_role": None, "fit_score": None,
                "required_power": None}
    effective = roles.effective_flight(disc)
    role = roles.primary_role(disc)
    return {
        "flight_known": True,
        "effective_flight": _flight_dict(effective),
        "behaves_flight": _flight_dict(roles.behaves_flight(disc, profile)),
        "stability": roles.stability_number(disc),
        "primary_role": role.name,
        # A weighted distance from the role's ideal: LOWER IS BETTER, unbounded.
        "fit_score": roles.fit_score(disc, role),
        "required_power": player.required_power(effective),
    }


def _history_summary(disc):
    u = disc.user
    return {
        "rounds": u.round_count,
        "practices": u.practice_count,
        "use_count": u.use_count,
        "first_used": u.first_used,
        "last_used": u.last_used,
        "last_round": u.last_round,
        "last_practice": u.last_practice,
        "acquired": u.date_added,
    }


def _inventory_record(disc, profile):
    return {
        "inventory_id": disc.id,
        "catalog_id": db.catalog_id(disc),
        "mold": disc.mold,
        "manufacturer": {
            "brand": disc.brand,
            "category": disc.category,
            "stability": disc.stability,
            "flight": {"speed": disc.speed, "glide": disc.glide,
                       "turn": disc.turn, "fade": disc.fade},
        },
        "user": asdict(disc.user),
        "computed": _computed(disc, profile),
        "history_summary": _history_summary(disc),
    }
```

Then in `build_export`, replace the `"catalog": {}` and `"inventory": []` lines:

```python
    records = sorted((_inventory_record(d, profile) for d in inventory),
                     key=lambda r: r["inventory_id"])
    catalog_map = {}
    for disc in inventory:
        catalog_map.setdefault(db.catalog_id(disc), _catalog_summary(disc))
```

and use `"catalog": catalog_map,` / `"inventory": records,` in the returned dict.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add discbag/export.py tests/test_export.py
git commit -m "export: inventory records and deduplicated portable catalog map"
```

---

### Task 5: Coverage, gaps, next purchase, and maturity

**Files:**
- Modify: `discbag/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: Task 4 helpers.
- Produces: populated `analysis.coverage`, `analysis.gaps`, `analysis.next_purchase`, `analysis.maturity`. Catalog suggestions in `next_purchase` add entries to the top-level `catalog` map.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
# ---------- coverage / gaps ----------

def test_coverage_reports_every_role_with_priority_and_reason():
    out = build([owned()])
    coverage = out["analysis"]["coverage"]
    assert len(coverage) == len(__import__("discbag.roles", fromlist=["ROLES"]).ROLES)
    putting = next(c for c in coverage if c["role"] == "Putting")
    assert putting["covered"] is True
    assert putting["priority"] == "Satisfied"
    assert putting["reason"]
    assert putting["disc_ids"] == ["id-wizard"]


def test_gaps_lists_only_uncovered_roles():
    out = build([owned()])
    gaps = out["analysis"]["gaps"]
    assert "Putting" not in [g["role"] for g in gaps]
    assert all(g["covered"] is False for g in gaps)


def test_coverage_disc_ids_reference_real_inventory_ids():
    out = build([owned()])
    known = {r["inventory_id"] for r in out["inventory"]}
    for entry in out["analysis"]["coverage"]:
        assert set(entry["disc_ids"]) <= known


# ---------- next purchase ----------

def test_next_purchase_is_null_for_an_empty_bag():
    assert build()["analysis"]["next_purchase"] is None


def test_next_purchase_carries_reason_and_catalog_backed_candidates():
    catalog = [{"name": "Firebird", "brand": "Innova", "category": "Distance Driver",
                "stability": "Very Overstable", "speed": 9, "glide": 3, "turn": 0, "fade": 4}]
    out = build([owned()], catalog=catalog)
    nxt = out["analysis"]["next_purchase"]
    assert nxt["role"]
    assert nxt["reason"]
    for cand in nxt["candidates"]:
        assert cand["catalog_id"] in out["catalog"]


# ---------- maturity ----------

def test_maturity_reports_phase_and_signals():
    out = build([owned()])
    m = out["analysis"]["maturity"]
    assert m["phase"] in {"Discovery", "Developing", "Developed"}
    assert all({"met", "text"} <= set(s) for s in m["signals"])


def test_maturity_is_null_when_there_is_nothing_to_assess():
    assert build()["analysis"]["maturity"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -k "coverage or gaps or next_purchase or maturity" -v`
Expected: FAIL — `assert [] ` / `AssertionError` (sections are still empty)

- [ ] **Step 3: Implement**

Extend the imports in `discbag/export.py`:

```python
from discbag import __version__, db, maturity, player, recommend, roles
```

Add above `build_export`:

```python
def _coverage_entry(rc):
    return {
        "role": rc.role.name,
        "description": rc.role.description,
        "covered": rc.covered,
        "priority": rc.priority,
        "priority_reason": rc.priority_reason,
        "reason": rc.reason,
        "disc_ids": [d.id for d in rc.discs],      # engine order: best fit first
    }


def _next_purchase(active, catalog_discs, profile, catalog_map):
    """The engine's single most valuable purchase, with its reasoning. Candidate
    molds are not owned, so their portable summaries join the catalog map."""
    result = roles.best_next(active, catalog_discs, profile=profile)
    if result is None:
        return None
    candidates = []
    for pick in result.candidates:
        cid = db.catalog_id(pick.disc)
        catalog_map.setdefault(cid, _catalog_summary(pick.disc))
        candidates.append({"catalog_id": cid, "score": pick.score})
    return {
        "role": result.coverage.role.name,
        "priority": result.coverage.priority,
        "reason": result.reason,
        "candidates": candidates,        # engine rank order, best first
    }


def _maturity(active, all_discs, profile, analysis_date):
    if not all_discs:
        return None
    phase, signals = maturity.assess_phase(active, all_discs, profile, analysis_date)
    return {
        "phase": phase,
        "signals": [{"met": s.met, "text": s.text} for s in signals],
        "usage_insights": list(maturity.usage_insights(active, analysis_date)),
        "observed_preferences": list(maturity.observed_preferences(active)),
    }
```

In `build_export`, after building `catalog_map`, add:

```python
    active = [d for d in inventory if d.user.is_active]
    assessment = roles.assess(active, profile)
    analysis_section = _empty_analysis()
    analysis_section["coverage"] = [_coverage_entry(rc) for rc in assessment]
    analysis_section["gaps"] = [_coverage_entry(rc) for rc in assessment if not rc.covered]
    analysis_section["next_purchase"] = (
        _next_purchase(active, catalog, profile, catalog_map) if active else None)
    analysis_section["maturity"] = _maturity(active, inventory, profile, analysis_date)
```

and return `"analysis": analysis_section,` instead of `_empty_analysis()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add discbag/export.py tests/test_export.py
git commit -m "export: coverage, gaps, next purchase, and maturity"
```

---

### Task 6: Goal bags, scenario bags, and canonical situation aliases

The engine defines five situations but only three distinct role sets. Which name is canonical is a fact about the situations table, so it lives in `roles.py`, not in the export.

**Files:**
- Modify: `discbag/roles.py`
- Modify: `discbag/export.py`
- Test: `tests/test_roles.py`, `tests/test_export.py`

**Interfaces:**
- Consumes: Task 5.
- Produces:
  - `roles.canonical_situations() -> (list[str], dict[str, str])` — canonical names in table order, plus `{alias: canonical}`.
  - Populated `analysis.goal_bags`, `analysis.scenario_bags`, `analysis.scenario_aliases`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_roles.py`:

```python
# ---------- canonical situations ----------

def test_canonical_situations_dedupes_identical_role_sets():
    canonical, aliases = roles.canonical_situations()
    assert canonical == ["windy", "woods", "minimal"]
    assert aliases == {"rain": "windy", "travel": "minimal"}


def test_every_situation_is_canonical_or_aliased_to_one():
    canonical, aliases = roles.canonical_situations()
    for name in roles._SITUATIONS:
        assert name in canonical or aliases[name] in canonical


def test_aliased_situations_resolve_to_the_same_roles():
    canonical, aliases = roles.canonical_situations()
    for alias, target in aliases.items():
        assert roles.roles_for_situation(alias) == roles.roles_for_situation(target)
```

Append to `tests/test_export.py`:

```python
# ---------- goal and scenario bags ----------

def test_goal_bags_cover_every_supported_goal():
    out = build([owned()])
    assert set(out["analysis"]["goal_bags"]) == {
        "coverage", "development", "confidence", "tournament", "fun"}


def test_goal_bag_entries_reference_inventory_ids_in_engine_order():
    out = build([owned()])
    bag = out["analysis"]["goal_bags"]["coverage"]
    known = {r["inventory_id"] for r in out["inventory"]}
    for slot in bag["filled"]:
        assert slot["disc_id"] in known
        assert slot["role"]
    assert isinstance(bag["gaps"], list)


def test_scenario_bags_hold_only_the_three_canonical_scenarios():
    out = build([owned()])
    assert set(out["analysis"]["scenario_bags"]) == {"windy", "woods", "minimal"}


def test_scenario_aliases_map_duplicates_to_canonical_names():
    out = build([owned()])
    assert out["analysis"]["scenario_aliases"] == {"rain": "windy", "travel": "minimal"}


def test_no_technical_or_open_scenario_exists():
    bags = build([owned()])["analysis"]["scenario_bags"]
    assert "technical" not in bags
    assert "open" not in bags
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_roles.py -k canonical tests/test_export.py -k "goal_bag or scenario" -v`
Expected: FAIL — `AttributeError: module 'discbag.roles' has no attribute 'canonical_situations'`

- [ ] **Step 3: Implement `roles.canonical_situations()`**

Add to `discbag/roles.py`, below `roles_for_situation`:

```python
def canonical_situations():
    """(canonical_names, aliases). Several situations share an identical role
    set — windy/rain and minimal/travel — so reports need only be built for the
    distinct ones. The first name in table order wins as canonical.
    """
    canonical, aliases, seen = [], {}, {}
    for name, role_names in _SITUATIONS.items():
        key = tuple(role_names)
        if key in seen:
            aliases[name] = seen[key]
        else:
            seen[key] = name
            canonical.append(name)
    return canonical, aliases
```

- [ ] **Step 4: Implement the bag sections in `export.py`**

Add above `build_export`:

```python
GOALS = ["coverage", "development", "confidence", "tournament", "fun"]


def _bag_result(active, profile, analysis_date, goal="coverage", situation=None):
    """One build-bag report. Uses the CLI defaults: no size limit, no rotation
    (rotation is RNG-driven and would break reproducibility)."""
    result = recommend.build_bag(
        active, size=ANALYSIS_DEFAULTS["bag_size"], situation=situation,
        goal=goal, rotate=False, profile=profile, today=analysis_date)
    return {
        # Engine order throughout — role priority, never alphabetized.
        # RoleFill.score is roles.fit_score for the chosen role: LOWER IS BETTER.
        "filled": [{"role": f.role.name, "disc_id": f.disc.id, "fit_score": f.score}
                   for f in result.filled],
        "gaps": [r.name for r in result.gaps],
        "omitted": [r.name for r in result.omitted],
    }
```

In `build_export`, after the maturity line:

```python
    if active:
        analysis_section["goal_bags"] = {
            goal: _bag_result(active, profile, analysis_date, goal=goal)
            for goal in GOALS}
        canonical, aliases = roles.canonical_situations()
        analysis_section["scenario_bags"] = {
            name: _bag_result(active, profile, analysis_date, situation=name)
            for name in canonical}
        analysis_section["scenario_aliases"] = dict(aliases)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_roles.py tests/test_export.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add discbag/roles.py discbag/export.py tests/test_roles.py tests/test_export.py
git commit -m "export: goal bags plus canonical scenario bags and alias map

Situation dedup lives in roles.py, where the situations table lives."
```

---

### Task 7: `overlap_groups` and `pairwise_comparisons`

No relationship taxonomy is invented. `overlap()` produces no score and no reasoning, so neither is exported.

**Files:**
- Modify: `discbag/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: Task 2 (`analysis.CompareVerdict`), Task 6.
- Produces: populated `analysis.overlap_groups` and `analysis.pairwise_comparisons`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
# ---------- overlap groups ----------

def twins():
    """Two near-identical putters plus one clearly distinct driver."""
    return [
        owned(name="Wizard", brand="Gateway", disc_id="id-a"),
        owned(name="Challenger", brand="Discraft", disc_id="id-b"),
        owned(name="Destroyer", brand="Innova", category="Distance Driver",
              speed=12, glide=5, turn=-1, fade=3, disc_id="id-c"),
    ]


def test_overlap_groups_reference_member_inventory_ids():
    groups = build(twins())["analysis"]["overlap_groups"]
    assert groups
    assert groups[0]["inventory_ids"] == ["id-a", "id-b"]


def test_overlap_group_id_is_deterministic_and_documented_as_structural():
    first = build(twins())["analysis"]["overlap_groups"][0]["group_id"]
    second = build(twins())["analysis"]["overlap_groups"][0]["group_id"]
    assert first == second


def test_overlap_groups_carry_no_invented_score_or_reasoning():
    # overlap() returns groups only; nothing is manufactured to fill those slots.
    group = build(twins())["analysis"]["overlap_groups"][0]
    assert set(group) == {"group_id", "inventory_ids"}


# ---------- pairwise comparisons ----------

def test_pairwise_endpoints_are_ordered_min_then_max():
    pairs = build(twins())["analysis"]["pairwise_comparisons"]
    for p in pairs:
        assert p["left_inventory_id"] < p["right_inventory_id"]


def test_pairwise_covers_each_unordered_pair_exactly_once():
    pairs = build(twins())["analysis"]["pairwise_comparisons"]
    seen = {(p["left_inventory_id"], p["right_inventory_id"]) for p in pairs}
    assert seen == {("id-a", "id-b"), ("id-a", "id-c"), ("id-b", "id-c")}


def test_pairwise_is_sorted_by_endpoints():
    pairs = build(twins())["analysis"]["pairwise_comparisons"]
    keys = [(p["left_inventory_id"], p["right_inventory_id"]) for p in pairs]
    assert keys == sorted(keys)


def test_pairwise_verdict_carries_structured_fields():
    pairs = build(twins())["analysis"]["pairwise_comparisons"]
    v = pairs[0]["verdict"]
    assert set(v) == {"overlap_text", "key_difference", "how_to_use", "degraded_note"}
    assert v["degraded_note"] is None      # always exactly two discs here


def test_pairwise_omits_the_presentation_table():
    # compare() is a terminal table; its facts already live in the inventory records.
    pairs = build(twins())["analysis"]["pairwise_comparisons"]
    assert "comparison" not in pairs[0]


def test_pairwise_carries_no_relationship_taxonomy():
    pairs = build(twins())["analysis"]["pairwise_comparisons"]
    assert "kind" not in pairs[0]


def test_single_disc_produces_an_empty_pairwise_list():
    assert build([owned()])["analysis"]["pairwise_comparisons"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -k "overlap or pairwise" -v`
Expected: FAIL — `assert []` (sections are still empty)

- [ ] **Step 3: Implement**

Extend the imports in `discbag/export.py`:

```python
from itertools import combinations

from discbag import __version__, analysis, db, maturity, player, recommend, roles
```

Add above `build_export`:

```python
def _overlap_groups(active, profile):
    """The engine's thresholded clusters. overlap() returns member discs only —
    no score and no reasoning — so neither is exported."""
    out = []
    for group in analysis.overlap(active, profile=profile):
        ids = sorted(d.id for d in group)
        # Structural identifier for rendering, derived from the sorted members.
        # Not an engine conclusion.
        out.append({"group_id": "overlap-" + "-".join(ids), "inventory_ids": ids})
    return sorted(out, key=lambda g: g["inventory_ids"])


def _verdict_dict(verdict):
    return {"overlap_text": verdict.overlap_text,
            "key_difference": verdict.key_difference,
            "how_to_use": verdict.how_to_use,
            "degraded_note": verdict.degraded_note}


def _pairwise_comparisons(active):
    """Existing compare_verdict() output for each eligible unordered pair.

    The compare() table is deliberately omitted: it is presentation, and every
    fact it shows already lives in the two referenced inventory records.
    """
    out = []
    for a, b in combinations(active, 2):
        left, right = (a, b) if a.id <= b.id else (b, a)
        verdict = analysis.compare_verdict([left, right])
        if verdict is None:           # incomplete flight: engine declines to judge
            continue
        out.append({"left_inventory_id": left.id,
                    "right_inventory_id": right.id,
                    "verdict": _verdict_dict(verdict)})
    return sorted(out, key=lambda p: (p["left_inventory_id"], p["right_inventory_id"]))
```

In `build_export`, inside the `if active:` block:

```python
        analysis_section["overlap_groups"] = _overlap_groups(active, profile)
        analysis_section["pairwise_comparisons"] = _pairwise_comparisons(active)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add discbag/export.py tests/test_export.py
git commit -m "export: overlap groups and pairwise comparisons

No invented relationship taxonomy; no manufactured score or reasoning."
```

---

### Task 8: Structured `exclusions`

**Files:**
- Modify: `discbag/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: Task 7.
- Produces: populated `analysis.exclusions` — a list of `{inventory_id, reason, excluded_from}`, sorted by `(inventory_id, reason)`. Reason codes: `incomplete_flight_data`, `inactive_status`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_export.py`:

```python
# ---------- exclusions ----------

def unknown_flight_disc(disc_id="id-unknown"):
    d = OwnedDisc.from_db_record(
        {"name": "Comanche", "brand": "Gateway", "category": "", "stability": "",
         "speed": None, "glide": None, "turn": None, "fade": None})
    d.id = disc_id
    return d


def test_incomplete_flight_disc_is_recorded_as_excluded():
    out = build([owned(), unknown_flight_disc()])
    entry = next(e for e in out["analysis"]["exclusions"]
                 if e["inventory_id"] == "id-unknown")
    assert entry["reason"] == "incomplete_flight_data"
    assert set(entry["excluded_from"]) == {
        "coverage", "goal_bags", "scenario_bags", "overlap_groups",
        "pairwise_comparisons"}


def test_inactive_disc_is_recorded_as_excluded():
    out = build([owned(disc_id="id-active"),
                 owned(disc_id="id-lost", status="lost")])
    entry = next(e for e in out["analysis"]["exclusions"]
                 if e["inventory_id"] == "id-lost")
    assert entry["reason"] == "inactive_status"


def test_excluded_discs_still_appear_in_inventory():
    out = build([owned(), unknown_flight_disc()])
    assert {r["inventory_id"] for r in out["inventory"]} == {"id-wizard", "id-unknown"}


def test_excluded_disc_never_appears_in_the_reports_it_was_excluded_from():
    out = build([owned(), unknown_flight_disc()])
    for entry in out["analysis"]["coverage"]:
        assert "id-unknown" not in entry["disc_ids"]
    for pair in out["analysis"]["pairwise_comparisons"]:
        assert "id-unknown" not in (pair["left_inventory_id"], pair["right_inventory_id"])


def test_reason_codes_are_stable_machine_readable_slugs():
    out = build([owned(), unknown_flight_disc(), owned(disc_id="id-lost", status="lost")])
    for entry in out["analysis"]["exclusions"]:
        assert entry["reason"] in {"incomplete_flight_data", "inactive_status"}


def test_exclusions_are_sorted_by_id_then_reason():
    out = build([owned(disc_id="id-z"), unknown_flight_disc("id-a"),
                 owned(disc_id="id-m", status="lost")])
    keys = [(e["inventory_id"], e["reason"]) for e in out["analysis"]["exclusions"]]
    assert keys == sorted(keys)


def test_no_exclusions_when_every_disc_participates():
    assert build([owned()])["analysis"]["exclusions"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export.py -k exclusion -v`
Expected: FAIL — `StopIteration` (exclusions is still empty)

- [ ] **Step 3: Implement**

Add above `build_export` in `discbag/export.py`:

```python
# Reports each exclusion reason actually keeps a disc out of. Verified against
# real engine behavior — a disc is never claimed to be excluded from a report
# the engine in fact includes it in.
_INCOMPLETE_FLIGHT_REPORTS = ["coverage", "goal_bags", "scenario_bags",
                              "overlap_groups", "pairwise_comparisons"]
_INACTIVE_REPORTS = ["coverage", "gaps", "goal_bags", "scenario_bags",
                     "overlap_groups", "pairwise_comparisons", "next_purchase"]


def _exclusions(inventory):
    """Which owned discs the engine leaves out of which reports, and why.

    Excluded discs stay visible in `inventory`; only their analysis
    participation is limited.
    """
    out = []
    for disc in inventory:
        if not disc.user.is_active:
            out.append({"inventory_id": disc.id, "reason": "inactive_status",
                        "excluded_from": list(_INACTIVE_REPORTS)})
        elif not roles.flight_known(disc):
            out.append({"inventory_id": disc.id, "reason": "incomplete_flight_data",
                        "excluded_from": list(_INCOMPLETE_FLIGHT_REPORTS)})
    return sorted(out, key=lambda e: (e["inventory_id"], e["reason"]))
```

In `build_export`, after the `if active:` block:

```python
    analysis_section["exclusions"] = _exclusions(inventory)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add discbag/export.py tests/test_export.py
git commit -m "export: structured exclusions with stable reason codes"
```

---

### Task 9: The `discbag export` CLI command

**Files:**
- Modify: `discbag/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `export.build_export` (Tasks 3-8).
- Produces: `discbag export [--output PATH] [--indent N]`. No `--json` flag. The CLI owns loading, both clocks, JSON serialization, and output.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py` (match the file's existing invocation helper — if it differs from `run_cli`, use that instead):

```python
# ---------- export ----------

def test_export_writes_valid_json_to_stdout(tmp_path, capsys):
    out = run_cli(["export"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"
    assert set(payload) >= {"profile", "inventory", "analysis", "catalog"}
    assert out == 0


def test_export_writes_to_a_file_with_output(tmp_path, capsys):
    target = tmp_path / "snapshot.json"
    assert run_cli(["export", "--output", str(target)]) == 0
    payload = json.loads(target.read_text())
    assert payload["schema_version"] == "1.0"
    assert capsys.readouterr().out.strip() == ""       # file mode prints no JSON


def test_export_has_no_json_flag():
    # The command emits JSON by definition; a mandatory flag would carry no information.
    assert run_cli(["export", "--json"]) != 0


def test_export_help_warns_that_snapshots_contain_personal_data(capsys):
    with pytest.raises(SystemExit):
        run_cli(["export", "--help"])
    help_text = capsys.readouterr().out.lower()
    assert "personal" in help_text
    assert "history" in help_text


def test_export_generated_at_is_utc_zulu(capsys):
    run_cli(["export"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["generated_at"].endswith("Z")
    datetime.strptime(payload["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
```

Ensure `tests/test_cli.py` imports `json`, `pytest`, and `from datetime import datetime`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -k export -v`
Expected: FAIL — `invalid choice: 'export'`

- [ ] **Step 3: Implement the command**

Add to `discbag/cli.py`, near the other `cmd_` functions:

```python
def cmd_export(args, inv):
    """Write a portable JSON snapshot of the collection and its analysis."""
    from datetime import date, datetime, timezone

    from discbag import export

    payload = export.build_export(
        inv.all_discs(),
        player.load_profile(),
        db.load_db().get("discs", []),
        analysis_date=date.today(),
        generated_at=datetime.now(timezone.utc),
    )
    text = json.dumps(payload, indent=args.indent, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n")
    else:
        print(text)
    return 0
```

Confirm `json` and `Path` are imported at the top of `cli.py`; add them if not.

- [ ] **Step 4: Register the parser**

Add alongside the other subparsers (near `p_bag`, around `cli.py:1909`):

```python
    p_export = sub.add_parser(
        "export",
        help="write a portable JSON snapshot of your collection and analysis",
        description=("Write a portable JSON snapshot of your collection and every "
                     "analysis discbag computes, for use by external tools.\n\n"
                     "An export may contain personal profile details, disc notes, "
                     "and your complete usage history. Anyone you send the file to "
                     "can read all of it."),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p_export.add_argument("--output", metavar="PATH",
                          help="write to this file instead of stdout")
    p_export.add_argument("--indent", type=int, default=2,
                          help="JSON indentation (default: 2)")
    p_export.set_defaults(func=cmd_export)
```

Match the surrounding registration style — if neighbouring parsers are wired through a dispatch table rather than `set_defaults(func=...)`, follow that instead.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 6: Verify against real data**

Run: `python -m discbag export --output /tmp/discbag-snapshot.json && python -c "import json;d=json.load(open('/tmp/discbag-snapshot.json'));print(d['schema_version'], len(d['inventory']), sorted(d['analysis']))"`
Expected: prints `1.0`, the real disc count, and the full analysis key list. This is the first end-to-end run against the actual collection.

- [ ] **Step 7: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Add discbag export: portable JSON snapshot command"
```

---

### Task 10: Schema invariants — determinism, leaf boundary, portability, golden snapshot

The invariants that keep the contract honest as the code changes. Written last, when every section exists.

**Files:**
- Create: `tests/test_export_invariants.py`
- Create: `tests/fixtures/export_snapshot.json`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Write the invariant tests**

Create `tests/test_export_invariants.py`:

```python
"""Contract invariants for the export schema.

These guard the properties the dashboard depends on: reproducible bytes, a
serializer that never becomes a second analysis surface, and snapshots that
render with no discbag installation.
"""

import ast
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from discbag import export
from tests.test_export import ANALYSIS_DATE, GENERATED_AT, build, owned, twins

FIXTURE = Path(__file__).parent / "fixtures" / "export_snapshot.json"

# export.py may lean on the engine; nothing else may lean on export.py.
ALLOWED_IMPORTS = {"discbag", "discbag.analysis", "discbag.db", "discbag.history",
                   "discbag.inventory", "discbag.maturity", "discbag.player",
                   "discbag.recommend", "discbag.roles"}


def dumps(payload):
    return json.dumps(payload, indent=2, sort_keys=True)


# ---------- 1. schema snapshot ----------

def test_export_matches_the_committed_structured_snapshot():
    assert build(twins()) == json.loads(FIXTURE.read_text())


def test_serialized_form_is_stable():
    assert dumps(build(twins())) == dumps(json.loads(FIXTURE.read_text()))


# ---------- 2. determinism ----------

def test_two_calls_with_identical_input_are_byte_identical():
    assert dumps(build(twins())) == dumps(build(twins()))


def test_inventory_order_does_not_affect_output():
    forward = twins()
    assert dumps(build(forward)) == dumps(build(list(reversed(forward))))


def test_generated_at_is_the_only_time_field_and_comes_from_injection():
    out = export.build_export([], None, [], analysis_date=date(2020, 1, 1),
                              generated_at=datetime(2020, 1, 1, 0, 0, 0))
    assert out["generated_at"] == "2020-01-01T00:00:00Z"


# ---------- 3. leaf boundary ----------

def _imported_modules(path):
    tree = ast.parse(Path(path).read_text())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _engine_modules():
    pkg = Path(export.__file__).parent
    return [p for p in pkg.glob("*.py") if p.name != "export.py"]


@pytest.mark.parametrize("module_path", _engine_modules(), ids=lambda p: p.name)
def test_no_engine_module_imports_export(module_path):
    assert not any(name.startswith("discbag.export") or name == "export"
                   for name in _imported_modules(module_path))


def test_export_imports_only_the_approved_allowlist():
    discbag_imports = {n for n in _imported_modules(export.__file__)
                       if n.split(".")[0] == "discbag"}
    # Sub-attribute forms like "discbag.roles.assess" resolve to their module.
    for name in discbag_imports:
        assert any(name == allowed or name.startswith(allowed + ".")
                   for allowed in ALLOWED_IMPORTS), name


# ---------- 4. portability ----------

def _referenced_catalog_ids(payload):
    """Every catalog_id appearing outside an owned inventory record."""
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "catalog_id" and isinstance(value, str):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload["analysis"])
    return found


def test_every_referenced_catalog_id_has_an_embedded_summary():
    catalog = [{"name": "Firebird", "brand": "Innova", "category": "Distance Driver",
                "stability": "Very Overstable", "speed": 9, "glide": 3, "turn": 0, "fade": 4}]
    payload = build(twins(), catalog=catalog)
    assert _referenced_catalog_ids(payload) <= set(payload["catalog"])


def test_inventory_catalog_ids_are_also_embedded():
    payload = build(twins())
    for record in payload["inventory"]:
        assert record["catalog_id"] in payload["catalog"]


def test_catalog_summaries_are_self_contained():
    required = {"catalog_id", "name", "brand", "category", "stability", "flight"}
    for summary in build(twins())["catalog"].values():
        assert required <= set(summary)


# ---------- 5. referential integrity ----------

def _referenced_inventory_ids(payload):
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"inventory_id", "disc_id", "left_inventory_id",
                           "right_inventory_id"} and isinstance(value, str):
                    found.add(value)
                elif key == "inventory_ids":
                    found.update(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload["analysis"])
    return found


def test_no_report_contains_a_dangling_inventory_id():
    payload = build(twins() + [owned(disc_id="id-lost", status="lost")])
    known = {r["inventory_id"] for r in payload["inventory"]}
    assert _referenced_inventory_ids(payload) <= known


def test_whole_payload_is_json_serializable():
    json.dumps(build(twins()))      # raises TypeError on any non-JSON-safe value
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_export_invariants.py -v`
Expected: FAIL — `FileNotFoundError` for the fixture on the two snapshot tests; the remaining tests should already pass.

- [ ] **Step 3: Generate the golden fixture**

Run:

```bash
mkdir -p tests/fixtures
python -c "
import json
from datetime import date, datetime
from discbag import export
from tests.test_export import twins, ANALYSIS_DATE, GENERATED_AT
payload = export.build_export(twins(), None, [],
                              analysis_date=ANALYSIS_DATE, generated_at=GENERATED_AT)
open('tests/fixtures/export_snapshot.json', 'w').write(
    json.dumps(payload, indent=2, sort_keys=True) + '\n')
"
```

Then **read the generated file** and confirm by eye: `schema_version` is `1.0`, the three discs appear sorted by id, `scenario_bags` has exactly `windy`/`woods`/`minimal`, `scenario_aliases` maps `rain`/`travel`, no `comparison` key appears in `pairwise_comparisons`, and no `kind` key appears anywhere. A golden file committed without reading it defeats its purpose.

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: PASS — every test, including the pre-existing suite.

- [ ] **Step 5: Document the fixture-update rule**

Add to the top of `tests/fixtures/export_snapshot.json`'s sibling test file — i.e. as a comment block below the docstring in `tests/test_export_invariants.py`:

```python
# Updating the golden fixture is an explicit act. Regenerate it with the command
# in docs/superpowers/plans/2026-07-20-export-json.md Task 10 Step 3, read the
# diff, and commit the regenerated fixture in the SAME commit as the schema
# change that motivated it. A silent regeneration hides a contract break.
```

- [ ] **Step 6: Commit**

```bash
git add tests/test_export_invariants.py tests/fixtures/export_snapshot.json
git commit -m "export: schema invariants — determinism, leaf boundary, portability

Golden snapshot plus mechanically enforced contract rules: no engine module
imports export, every referenced catalog_id ships an embedded summary, and no
report contains a dangling inventory_id."
```

---

### Task 11: Document the schema in the README

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Add the command to the reference**

In `README.md`, under **Advanced Commands**, add:

```markdown
### Export

```bash
discbag export [--output PATH] [--indent N]
```

Writes a portable JSON snapshot (schema v1.0) of your collection and every analysis `discbag`
computes: role coverage, gaps, goal and scenario bags, overlap groups, pairwise comparisons,
collection maturity, and next-purchase reasoning — each with the engine's own reasoning attached.

The snapshot is self-contained. Molds referenced by recommendations travel with the file, so an
export renders on a machine with no `discbag` installation. `discbag` produces the data; external
tools visualize it.

Two conventions worth knowing when consuming an export:

- `fit_score` is a **distance from a role's ideal — lower is better**, not a 0-1 rating.
- `scenario_bags` holds only the three distinct scenarios (`windy`, `woods`, `minimal`);
  `scenario_aliases` maps `rain` and `travel` onto them. Resolve through the alias map.

Discs with incomplete flight data and archived discs stay visible in `inventory` but sit out the
analyses the engine already excludes them from — `analysis.exclusions` records exactly which, and
why, with stable reason codes.

**An export may contain your profile details, disc notes, and complete usage history.** Anyone you
send the file to can read all of it.
```

- [ ] **Step 2: Add a changelog entry**

In `CHANGELOG.md`, under the unreleased section (match the file's existing heading style):

```markdown
### Added
- `discbag export` — a portable, deterministic JSON snapshot (schema v1.0) of your collection and
  every computed analysis, for consumption by external tools.
- `db.catalog_id()` — stable brand+name identifier for catalog molds.
- `roles.canonical_situations()` — the distinct situations and the aliases that resolve onto them.

### Changed
- `analysis.compare_verdict()` now returns a structured `CompareVerdict` rather than pre-formatted
  text; the CLI renders it. Terminal output is unchanged.
```

- [ ] **Step 3: Verify the documented example runs**

Run: `python -m discbag export --indent 2 | head -20`
Expected: valid JSON beginning with `"analysis_defaults"` (keys are sorted), no traceback.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Document discbag export and schema v1.0 consumer conventions"
```

---

## Notes for the implementer

**The one rule that matters most.** If you find yourself writing a comparison, a threshold, or a
classification inside `export.py`, stop. That logic belongs in the engine. The export's whole value
is that it cannot drift from the CLI, and it only holds if the module stays a serializer.

**Where the schema is authoritative.** `docs/superpowers/specs/2026-07-20-export-json-design.md` wins
over this plan if they disagree. Flag the conflict rather than picking silently.

**Things deliberately absent** — do not add them, even if they seem obviously useful: wind
suitability, effective distance ranges, shot shapes, strengths/weaknesses, a `similar`/`backup`/
`more_stable` relationship taxonomy, rotation output, `choose` results, redaction, and any
relationship filtering or top-N truncation. Each is a deliberate deferral recorded in the spec.

**Task 2 is the only change to existing behavior.** Everything else is additive. Its guarantee is
byte-identical CLI output, which the adapted wording tests enforce.
