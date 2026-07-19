# Partial Manufacturer Specs (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Represent partially/fully unknown manufacturer flight honestly (never `0`), keep incomplete-flight discs first-class, and have flight-based analysis treat them as `Unknown` — plus local-mold authoring and prototype provenance.

**Architecture:** One model change (nullable flight + provenance/origin/edition) threaded through the engine via a single `flight_known` gate. Phased so each phase leaves the suite green. Reuses `personal_flight`, the cached `Disc` snapshot, and the event log.

**Tech Stack:** Python 3.9+, dataclasses, argparse, pytest. Runner: `./.venv/bin/python -m pytest`.

## Global Constraints (from the spec)

- **Unknown ≠ 0.** Missing manufacturer flight is `None`, never coerced to `0`.
- **`has_flight` is derived** (`all four not None`), never stored. **`release_status`** (stored) ∈ {`production`, `prototype`} and is **independent** of completeness (Wizard OS = prototype + complete flight).
- **`origin`** is an open string (`"discit"`, `"local"`, …); a sync refreshes only molds whose `origin` matches the catalog; `origin=="local"` is never auto-refreshed.
- **`edition`** lives on `UserData` (per-copy, survives DB refresh). **Never** on the cached `Disc`.
- **Identity:** local molds use canonical `(brand, mold)` — never decorated names.
- **`manufacturer_notes`** = manufacturer statements only (`--manufacturer-note`); user commentary → `--notes`. Editable, not immutable.
- **Flight precedence:** complete `personal_flight` → complete manufacturer → `Unknown`. Unknown discs are present everywhere except flight math.
- **v1 non-goals:** no coarse reasoning / precision tiers / inferred numbers / automated graduation / collectibles.
- **Backward compatibility:** existing complete discs behave identically; **no data migration**.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

## Phases & dependencies

```
Phase 1 (model + predicates)  ──┬──► Phase 2 (engine honors Unknown) ──► Phase 3 (CLI author/display) ──► Phase 5 (docs)
                                └──► Phase 4 (sync/origin protection) ──────────────────────────────────┘
```
Phase 2, 3, 4 all depend on Phase 1. Phase 3 depends on Phase 2 (excluded-disc output). Phase 4 depends only on Phase 1. Docs last. **Each phase ends green.**

---

## Phase 1 — Model & predicates (foundation)

### Task 1.1 — Nullable flight + provenance fields + `has_flight` (`Disc`), `edition` (`UserData`)

**Files:** Modify `discbag/inventory.py`; Test `tests/test_inventory.py`.

**Interfaces produced:** `Disc.speed/glide/turn/fade: Optional[float]=None`; `Disc.release_status/origin/program/release/manufacturer_notes`; `Disc.has_flight` property; `UserData.edition`.

- [ ] **Step 1 — Failing tests** (`tests/test_inventory.py`):

```python
def test_disc_flight_defaults_to_none_not_zero():
    d = Disc(name="Comanche", brand="Gateway", speed=10)  # glide/turn/fade omitted
    assert d.speed == 10
    assert d.glide is None and d.turn is None and d.fade is None
    assert d.has_flight is False


def test_disc_has_flight_true_when_all_present():
    d = Disc(name="Buzzz", brand="Discraft", speed=5, glide=4, turn=-1, fade=1)
    assert d.has_flight is True


def test_disc_provenance_defaults_and_roundtrip():
    d = Disc(name="Comanche", brand="Gateway", speed=10,
             release_status="prototype", origin="local", program="Premier Membership",
             release="2026-07", manufacturer_notes=["Excellent resistance to turn"])
    back = Disc.from_dict(d.to_dict())
    assert back.release_status == "prototype" and back.origin == "local"
    assert back.program == "Premier Membership" and back.release == "2026-07"
    assert back.manufacturer_notes == ["Excellent resistance to turn"]
    assert back.has_flight is False


def test_disc_defaults_are_production_discit():
    d = Disc(name="Buzzz", brand="Discraft", speed=5, glide=4, turn=-1, fade=1)
    assert d.release_status == "production" and d.origin == "discit"
    assert d.manufacturer_notes == []


def test_userdata_edition_roundtrips():
    u = UserData(edition="First Run")
    assert UserData.from_dict(u.to_dict()).edition == "First Run"


def test_old_inventory_json_loads_with_defaults(tmp_path):
    # A pre-feature record (no new fields) loads with safe defaults, flight intact.
    path = tmp_path / "inventory.json"
    rec = OwnedDisc.from_db_record(MAKO3).to_dict()
    for k in ("release_status", "origin", "program", "release", "manufacturer_notes"):
        rec["cached"].pop(k, None)
    rec["user"].pop("edition", None)
    path.write_text(json.dumps([rec]))
    d = inventory.Inventory(path=path).list_discs()[0]
    assert d.cached.release_status == "production" and d.cached.origin == "discit"
    assert d.user.edition == ""
    assert d.cached.has_flight is True                       # MAKO3 has full numbers
```

- [ ] **Step 2 — Run, expect FAIL:** `./.venv/bin/python -m pytest tests/test_inventory.py -k "flight_defaults or has_flight or provenance or edition or defaults_are or old_inventory" -v` → FAIL (fields/property missing).

- [ ] **Step 3 — Implement.** In `discbag/inventory.py`, change `Disc`:

```python
@dataclass
class Disc:
    """Manufacturer / mold data. Immutable facts sourced from a catalog or authored locally."""

    name: str
    brand: str = ""
    category: str = ""
    speed: Optional[float] = None       # None = not published (distinct from a real 0)
    glide: Optional[float] = None
    turn: Optional[float] = None
    fade: Optional[float] = None
    stability: str = ""
    release_status: str = "production"  # "production" | "prototype"
    origin: str = "discit"              # open string: which catalog (or "local")
    program: Optional[str] = None       # e.g. "Premier Membership"
    release: Optional[str] = None       # e.g. "2026-07"
    manufacturer_notes: List[str] = field(default_factory=list)

    @property
    def has_flight(self):
        return all(v is not None for v in (self.speed, self.glide, self.turn, self.fade))

    @classmethod
    def from_db_record(cls, record):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in record.items() if k in known})

    from_dict = from_db_record

    def to_dict(self):
        return asdict(self)
```

In `UserData`, add `edition: str = ""` (place it near `notes`). `UserData.from_dict` already filters known fields, so `edition` round-trips automatically.

- [ ] **Step 4 — Run, expect PASS** for the same `-k` selection.

- [ ] **Step 5 — Audit the default change.** Run the **full** suite: `./.venv/bin/python -m pytest -q`. Any test that constructed a bare `Disc(name=...)` and relied on flight defaulting to `0` will now see `None`. Fix each by giving that fixture explicit flight numbers (it was relying on a placeholder `0`). Re-run until green. Expected: PASS.

- [ ] **Step 6 — Commit.**
```bash
git add discbag/inventory.py tests/test_inventory.py
git commit -m "Model: nullable manufacturer flight + provenance/origin/edition + has_flight

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### Task 1.2 — `flight_known` predicates (`roles.py`)

**Files:** Modify `discbag/roles.py`; Test `tests/test_roles.py`.

**Interfaces produced:** `roles.flight_known(disc) -> bool`, `roles._personal_complete(disc)`, `roles._manufacturer_complete(disc)`.

- [ ] **Step 1 — Failing tests** (`tests/test_roles.py`):

```python
def test_flight_known_manufacturer_complete():
    from discbag.inventory import Disc
    assert roles.flight_known(Disc(name="B", speed=5, glide=4, turn=-1, fade=1)) is True
    assert roles.flight_known(Disc(name="C", speed=10)) is False        # glide/turn/fade None


def test_flight_known_via_personal(tmp_path):
    from discbag.inventory import OwnedDisc
    rec = {"name": "Comanche", "brand": "Gateway", "category": "",
           "speed": 10, "glide": None, "turn": None, "fade": None, "stability": ""}
    d = OwnedDisc.from_db_record(rec)
    assert roles.flight_known(d) is False
    d.user.personal_flight = {"speed": 10, "glide": 5, "turn": -1, "fade": 2}
    assert roles.flight_known(d) is True                                # personal completes it


def test_personal_incomplete_does_not_satisfy():
    from discbag.inventory import OwnedDisc
    d = OwnedDisc.from_db_record({"name": "X", "brand": "Y", "speed": None,
                                  "glide": None, "turn": None, "fade": None, "stability": ""})
    d.user.personal_flight = {"speed": 10}                              # partial
    assert roles.flight_known(d) is False
```

- [ ] **Step 2 — Run, expect FAIL** (`AttributeError`). `./.venv/bin/python -m pytest tests/test_roles.py -k flight_known -v`

- [ ] **Step 3 — Implement** in `discbag/roles.py` (near the top, after imports):

```python
def _personal_complete(disc):
    p = getattr(getattr(disc, "user", None), "personal_flight", None)
    return bool(p) and all(p.get(k) is not None for k in ("speed", "glide", "turn", "fade"))


def _manufacturer_complete(disc):
    return all(getattr(disc, k, None) is not None for k in ("speed", "glide", "turn", "fade"))


def flight_known(disc):
    """Complete flight to reason with: the player's personal_flight, or the mold's published
    numbers. Works on OwnedDisc (delegates to its cached snapshot) and on a bare Disc."""
    return _personal_complete(disc) or _manufacturer_complete(disc)
```

- [ ] **Step 4 — Run, expect PASS**, then full suite `-q` PASS.
- [ ] **Step 5 — Commit.**
```bash
git add discbag/roles.py tests/test_roles.py
git commit -m "Add flight_known / completeness predicates

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

### ✅ Phase 1 acceptance
`tests/test_inventory.py` and `tests/test_roles.py` new tests pass; **full suite green**; nullable flight, provenance/origin/edition, `has_flight`, and `flight_known` exist and round-trip. No behavior change to complete discs yet.

---

## Phase 2 — Engine honors `Unknown`

Every flight subsystem filters/guards on `flight_known` so an incomplete disc is never arithmetic'd. Complete discs are unaffected. **Depends on Phase 1.**

### Task 2.1 — None-safe flight access (`roles.py`, `player.py`)

**Files:** Modify `discbag/roles.py`, `discbag/player.py`; Test `tests/test_roles.py`.

- [ ] **Step 1 — Failing test:**
```python
def test_stability_number_none_safe():
    from discbag.inventory import Disc
    assert roles.stability_number(Disc(name="C", speed=10)) is None      # incomplete → None
    assert roles.stability_number(Disc(name="B", speed=5, glide=4, turn=-1, fade=1)) == 0.0
```

- [ ] **Step 2 — Run, expect FAIL** (current `stability_number` does `float(None)` → TypeError).

- [ ] **Step 3 — Implement.**
  - `roles.stability_number`:
    ```python
    def stability_number(disc):
        """turn + fade, or None if flight is incomplete."""
        if disc.turn is None or disc.fade is None:
            return None
        return float(disc.turn) + float(disc.fade)
    ```
  - `roles.effective_flight`: use `personal_flight` only when `_personal_complete`, else the manufacturer numbers; both branches are only reached for `flight_known` discs. Guard the personal branch:
    ```python
    def effective_flight(disc):
        if _personal_complete(disc):
            p = disc.user.personal_flight
            return Flight(speed=float(p["speed"]), glide=float(p["glide"]),
                          turn=float(p["turn"]), fade=float(p["fade"]))
        return Flight(speed=float(disc.speed), glide=float(getattr(disc, "glide", 0) or 0),
                      turn=float(disc.turn), fade=float(disc.fade))
    ```
  - `player.adjusted_numbers`: precondition is `flight_known`; leave as-is (callers guarantee it) but make the read defensive against a `None` glide only:
    (no change required beyond callers filtering; do not silently coerce `None` speed/turn/fade — those callers must have filtered.)

- [ ] **Step 4 — Run, expect PASS**; note downstream callers of `stability_number` must handle `None` (done in later tasks). Full suite may still be green here because complete discs are unaffected; if any existing test now hits `None`, it belongs to a later task's filter — if a failure appears, it indicates the caller needs its Task-2.x filter; apply that task first. Expected on this task in isolation: the new test passes and previously-green tests stay green.
- [ ] **Step 5 — Commit** (`roles.py`, `player.py`, `tests/test_roles.py`): "None-safe stability_number and effective_flight".

### Task 2.2 — Role coverage filters Unknown (`roles.py`)

**Files:** Modify `discbag/roles.py`; Test `tests/test_roles.py`.

- [ ] **Step 1 — Failing test:**
```python
def test_assess_ignores_unknown_flight_discs():
    from discbag.inventory import OwnedDisc
    known = OwnedDisc.from_db_record({"name": "Aviar", "brand": "Innova", "category": "Putter",
                                      "speed": 2, "glide": 3, "turn": 0, "fade": 1, "stability": ""})
    unknown = OwnedDisc.from_db_record({"name": "Comanche", "brand": "Gateway", "category": "",
                                        "speed": 10, "glide": None, "turn": None, "fade": None,
                                        "stability": ""})
    cov = roles.assess([known, unknown])
    # the Unknown disc fills no role
    for rc in cov:
        assert unknown not in rc.discs
```

- [ ] **Step 2 — Run, expect FAIL** (currently `qualifies`/`fit_score` crash on the Unknown disc, or it wrongly qualifies).

- [ ] **Step 3 — Implement.** In `roles.assess`, filter the bag once at the top:
```python
def assess(bag, profile=None):
    bag = [d for d in bag if flight_known(d)]     # Unknown-flight discs fill no role
    ...
```
Also guard `_bag_behaves_overstable(bag, profile)` similarly (`bag = [d for d in bag if flight_known(d)]` at its top), and ensure `best_next`/`suggest` operate on the filtered assessment (they consume `assess`, so no extra change).

- [ ] **Step 4 — Run, expect PASS**; full suite `-q` PASS.
- [ ] **Step 5 — Commit:** "Role coverage ignores Unknown-flight discs".

### Task 2.3 — analysis: choose / practice / overlap filter; compare renders `—` (`analysis.py`)

**Files:** Modify `discbag/analysis.py`; Test `tests/test_analysis.py`.

- [ ] **Step 1 — Failing tests:**
```python
def test_choose_excludes_unknown_flight():
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)   # glide/turn/fade None
    picks = analysis.choose([known, unknown], distance=300, shape="straight")
    assert all(p.disc is not unknown for p in picks)


def test_overlap_excludes_unknown_flight():
    a = Disc(name="Buzzz", brand="Discraft", category="Midrange", speed=5, glide=4, turn=-1, fade=1)
    b = Disc(name="Buzzz2", brand="Discraft", category="Midrange", speed=5, glide=4, turn=-1, fade=1)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    groups = analysis.overlap([a, b, unknown])
    flat = [d for g in groups for d in g]
    assert unknown not in flat


def test_compare_renders_dash_for_unknown_flight():
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    table = analysis.compare([known, unknown])
    rows = {r.label: r.values for r in table.rows}
    assert rows["Glide"][1] == "—" and rows["Turn"][1] == "—"      # Unknown disc → dashes
    assert rows["Speed"][1] == 10                                    # a known field still shows


def test_compare_verdict_skipped_when_a_disc_is_unknown():
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    assert analysis.compare_verdict([known, unknown]) is None       # can't reason without flight
```

- [ ] **Step 2 — Run, expect FAIL.**

- [ ] **Step 3 — Implement** in `discbag/analysis.py`:
  - Add at the top: `from discbag import roles` is already imported. Add a helper:
    ```python
    def _flight_known(d):
        return roles.flight_known(d)
    ```
  - `choose`: first line `bag = [d for d in bag if roles.flight_known(d)]`.
  - `practice`: first line `bag = [d for d in bag if roles.flight_known(d)]`.
  - `overlap`: first line `discs = [d for d in discs if roles.flight_known(d)]`.
  - `compare`: keep all discs (it's a side-by-side of what you asked for), but render each numeric cell as `"—"` when `None`, and the Stability row per disc as its word or `"—"` when `stability_number` is `None`. In `compare`'s row construction, replace raw `d.speed` etc. with a cell that maps `None`→`"—"`:
    ```python
    def _cell(v):
        return "—" if v is None else v
    rows = [
        Row("Speed", [_cell(d.speed) for d in discs]),
        Row("Glide", [_cell(d.glide) for d in discs]),
        Row("Turn", [_cell(d.turn) for d in discs]),
        Row("Fade", [_cell(d.fade) for d in discs]),
        Row("Stability", [(roles.stability_word(s) if (s := roles.stability_number(d)) is not None
                           else "—") for d in discs]),
        Row("Role", [_role_of(d) for d in discs]),
    ]
    ```
    (`_role_of` calls `roles.primary_role`; make `primary_role` return a sentinel/`"—"`-friendly value — see below.)
  - `compare_verdict`: at the top, `if not all(roles.flight_known(d) for d in discs): return None`.
  - `_role_of` / `roles.primary_role`: `primary_role` computes fit via `effective_flight`; guard it — if `not roles.flight_known(disc)`, `_role_of` should return `"—"` (do the check in `_role_of` in analysis, not deep in roles): 
    ```python
    def _role_of(disc):
        user = getattr(disc, "user", None)
        if user is not None and user.role:
            return user.role
        if not roles.flight_known(disc):
            return "—"
        return roles.primary_role(disc).name
    ```

- [ ] **Step 4 — Run, expect PASS**; full suite `-q` PASS.
- [ ] **Step 5 — Commit:** "analysis: filter Unknown from choose/practice/overlap; compare shows —".

### Task 2.4 — build-bag, maturity, charts filter Unknown (`recommend.py`, `maturity.py`, `chart.py`, `braille.py`)

**Files:** Modify those four; Test `tests/test_recommend.py`, `tests/test_maturity.py`.

- [ ] **Step 1 — Failing tests:**
```python
# tests/test_recommend.py
def test_build_bag_ignores_unknown_flight():
    from discbag.inventory import Disc
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    result = recommend.build_bag([known, unknown])
    assert all(f.disc is not unknown for f in result.filled)

# tests/test_maturity.py
def test_maturity_flight_signals_skip_unknown():
    # An Unknown-flight disc doesn't crash maturity and isn't counted in flight-derived signals.
    from discbag.inventory import OwnedDisc
    unknown = OwnedDisc.from_db_record({"name": "Comanche", "brand": "Gateway", "category": "",
                                        "speed": 10, "glide": None, "turn": None, "fade": None,
                                        "stability": ""})
    prefs = maturity.observed_preferences([unknown])
    assert prefs == []                                     # no stability/speed claim from Unknown
```

- [ ] **Step 2 — Run, expect FAIL.**

- [ ] **Step 3 — Implement** (filter at each flight entry point):
  - `recommend.build_bag`: first line `bag = [d for d in bag if roles.flight_known(d)]` (import `roles` if not already). `score_disc`/`_selection_score`/`_stability`/`_overpower` are then only reached for known discs.
  - `maturity`: in `_by_category`/`_broad_category` callers and `observed_preferences`, filter to `roles.flight_known`. Concretely, at the top of `observed_preferences`, `usage_insights`, and the settled-core/preference helpers that read speed/turn/fade, use `active = [d for d in active if roles.flight_known(d)]` **only for the flight-derived computations** (leave coverage/usage/favorites — which already route through `roles.assess` or `use_count` — to include all discs). Simplest: guard the three flight-reading helpers (`_broad_category` callers, `_stability_group`, speed clustering) by filtering their input list.
  - `chart.py` / `braille.py`: in the functions that plot stability/flight, filter `discs = [d for d in discs if roles.flight_known(d)]` before computing `stability(d)`.

- [ ] **Step 4 — Run, expect PASS**; full suite `-q` PASS.
- [ ] **Step 5 — Commit:** "build-bag/maturity/charts skip Unknown-flight discs".

### ✅ Phase 2 acceptance
An Unknown-flight disc is excluded from `choose`, `overlap`, `build-bag`, `practice`, role coverage, and maturity's flight signals; `compare` renders `—` and skips the verdict; a **complete** disc (incl. Wizard-OS-style prototype-with-flight, and an incomplete disc with complete `personal_flight`) participates exactly as before. Full suite green.

---

## Phase 3 — CLI authoring & display

**Depends on Phase 1 + 2.**

### Task 3.1 — `flight_str`, `show`, `list` render incomplete flight + provenance (`cli.py`)

**Files:** Modify `discbag/cli.py`; Test `tests/test_cli.py`.

- [ ] **Step 1 — Failing tests:**
```python
def test_flight_str_renders_unknown():
    from discbag.inventory import Disc
    assert cli.flight_str(Disc(name="C", brand="Gateway", speed=10)) == "10 / ? / ? / ?"


def test_show_prototype_displays_provenance_and_pending_flight(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    rec = {"name": "Comanche", "brand": "Gateway", "category": "",
           "speed": 10, "glide": None, "turn": None, "fade": None, "stability": "",
           "release_status": "prototype", "origin": "local", "program": "Premier Membership",
           "release": "2026-07", "manufacturer_notes": ["Excellent resistance to turn"]}
    inv.add(OwnedDisc.from_db_record(rec, plastic="NXTG / NXT Lite Blend"))
    cli.cmd_show(_ns(name=["comanche"]), inv)
    out = capsys.readouterr().out
    assert "Prototype" in out
    assert "Premier Membership" in out and "2026-07" in out
    assert "Excellent resistance to turn" in out
    assert "not yet published" in out.lower() or "?" in out
```

- [ ] **Step 2 — Run, expect FAIL.**

- [ ] **Step 3 — Implement** in `discbag/cli.py`:
  - `flight_str`: render `None` as `?`:
    ```python
    def _num_or_q(v):
        return "?" if v is None else _num_str(v)
    def flight_str(disc):
        return " / ".join(_num_or_q(v) for v in (disc.speed, disc.glide, disc.turn, disc.fade))
    ```
  - `format_owned` (show): after the header, if `disc.cached.release_status != "production"`, print a `(Prototype)` badge; if `not disc.cached.has_flight`, print `Flight: not yet published` (plus any known component, e.g. speed); print `Program: {program} ({release})` when set; print each `manufacturer_notes` line under a `Manufacturer:` block; print `Edition:` when `user.edition`.
  - `_print_disc_row` (list): render flight via `flight_str` (now `?`-aware) and append `(prototype)` when `release_status != "production"`.

- [ ] **Step 4 — Run, expect PASS**; full suite `-q` PASS.
- [ ] **Step 5 — Commit:** "show/list/flight_str render incomplete flight and provenance".

### Task 3.2 — `add --prototype` (local authoring) + validators (`cli.py`)

**Files:** Modify `discbag/cli.py`; Test `tests/test_cli.py`.

- [ ] **Step 1 — Failing tests:**
```python
def test_add_prototype_authors_local_mold_with_partial_flight(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    args = _ns(query=["Comanche"], brand="Gateway", prototype=True,
               speed=10, glide=None, turn=None, fade=None, flight=None, category=None,
               plastic="NXTG / NXT Lite Blend", weight=None, color=None, condition=None,
               location=None, notes=None, edition=None, program="Premier Membership",
               release="2026-07",
               manufacturer_note=["Excellent resistance to turn", "Long forward push"], yes=True)
    rc = cli.cmd_add(args, inv)
    assert rc == 0
    d = inv.all_discs()[0]
    assert d.cached.release_status == "prototype" and d.cached.origin == "local"
    assert d.cached.speed == 10 and d.cached.turn is None      # partial, not zeroed
    assert d.cached.program == "Premier Membership"
    assert d.cached.manufacturer_notes == ["Excellent resistance to turn", "Long forward push"]
    assert d.user.plastic == "NXTG / NXT Lite Blend"


def test_iso_month_validator():
    import argparse, pytest
    assert cli._iso_month("2026-07") == "2026-07"
    for bad in ("2026-7", "202607", "2026-13", "2026-07-03"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._iso_month(bad)


def test_parser_rejects_decorated_prototype_name_and_bad_release_status():
    parser = cli.build_parser()
    import pytest
    with pytest.raises(SystemExit):
        parser.parse_args(["edit", "comanche", "--release-status", "bogus"])
```

- [ ] **Step 2 — Run, expect FAIL.**

- [ ] **Step 3 — Implement** in `discbag/cli.py`:
  - Add `_iso_month(s)` validator (strict `^\d{4}-\d{2}$`, month 01–12), mirroring `_iso_date`.
  - Extend the `add` parser (`p_add`): `--prototype` (store_true), `--brand`, `--category`, `--speed/--glide/--turn/--fade` (type `float`), `--flight` (`S/G/T/F`), `--program`, `--release` (type `_iso_month`), `--manufacturer-note` (action append, dest `manufacturer_note`), `--edition`. Keep existing flags.
  - `cmd_add`: when `args.prototype`, take the **local-authoring** path — build the `Disc` directly from `--brand` + the positional mold name (canonical; reject a decorated name containing "prototype"/a plastic token/`YYYY-MM`) + the provided flight fields (omitted → `None`, from `--flight` if given) + `release_status="prototype"`, `origin="local"`, `program`, `release`, `manufacturer_notes` — **without** requiring a DB match. Then `OwnedDisc.from_db_record`-equivalent construction with the user metadata (`plastic`, `weight`, `edition`, personal `notes`). Non-prototype `add` is unchanged.
  - `edit` parser (`p_edit`): add `--speed/--glide/--turn/--fade`, `--release-status` (choices `["production", "prototype"]`), `--program`, `--release` (`_iso_month`), `--manufacturer-note` (append). `cmd_edit` sets them on the cached snapshot; flight fields fill individual `None`s. (Reuse the existing `update_metadata` path; extend it to carry the manufacturer/flight fields.)

- [ ] **Step 4 — Run, expect PASS**; end-to-end sanity in a temp HOME authoring the three fixtures; full suite `-q` PASS.
- [ ] **Step 5 — Commit:** "add --prototype authors local molds; edit fills flight/provenance; _iso_month".

### Task 3.3 — `list --prototype` filter + "N not considered" analysis note (`cli.py`)

**Files:** Modify `discbag/cli.py`; Test `tests/test_cli.py`.

- [ ] **Step 1 — Failing tests:**
```python
def test_list_prototype_filters(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record({"name": "Comanche", "brand": "Gateway", "category": "",
             "speed": 10, "glide": None, "turn": None, "fade": None, "stability": "",
             "release_status": "prototype", "origin": "local"}))
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None, all=False,
                     ids=False, prototype=True), inv)
    out = capsys.readouterr().out
    assert "Comanche" in out and "Mako3" not in out


def test_choose_notes_excluded_prototypes(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record({"name": "Wraith", "brand": "Innova",
             "category": "Distance Driver", "speed": 11, "glide": 5, "turn": -1, "fade": 3}))
    inv.add(OwnedDisc.from_db_record({"name": "Comanche", "brand": "Gateway", "category": "",
             "speed": 10, "glide": None, "turn": None, "fade": None, "stability": "",
             "release_status": "prototype"}))
    cli.cmd_choose(_ns(distance=300, wind=None, shape="straight"), inv)
    out = capsys.readouterr().out.lower()
    assert "not considered" in out and "flight" in out
```

- [ ] **Step 2 — Run, expect FAIL.**

- [ ] **Step 3 — Implement:**
  - `p_list`: add `--prototype` (store_true). `cmd_list`: when set, filter to `release_status == "prototype"` (via `inv.filter` extended or a post-filter on the result). Header reads "N prototypes".
  - `cmd_choose` / `cmd_practice` / `cmd_build_bag`: compute `excluded = [d for d in candidates if not roles.flight_known(d)]` and, when non-empty, print a trailing `Note: N disc(s) not considered — flight not yet published.` (Candidates here are the carry bag for choose/practice, active inventory for build-bag.)

- [ ] **Step 4 — Run, expect PASS**; full suite `-q` PASS.
- [ ] **Step 5 — Commit:** "list --prototype; analysis notes excluded incomplete discs".

### ✅ Phase 3 acceptance
The three Gateway fixtures author cleanly (`add --prototype`), `show`/`list` display provenance + pending flight honestly, `list --prototype` filters, `edit` fills numbers, validators reject bad `--release-status`/`--release`/decorated names, and analysis commands footnote excluded discs. Full suite green.

---

## Phase 4 — Sync / origin protection

**Depends on Phase 1.**

### Task 4.1 — Catalog refresh respects `origin` (`inventory.py`, `db.py`)

**Files:** Modify `discbag/inventory.py` (`refresh_from_db`, `refresh_manufacturer`); Test `tests/test_inventory.py`.

- [ ] **Step 1 — Failing test:**
```python
def test_refresh_never_overwrites_local_mold(tmp_path):
    inv = make_inv(tmp_path)
    rec = {"name": "Comanche", "brand": "Gateway", "category": "",
           "speed": 10, "glide": None, "turn": None, "fade": None, "stability": "",
           "release_status": "prototype", "origin": "local",
           "manufacturer_notes": ["Long forward push"]}
    inv.add(OwnedDisc.from_db_record(rec))
    # A catalog that now contains a same-name mold with full numbers.
    catalog = [{"name": "Comanche", "brand": "Gateway", "category": "Distance Driver",
                "speed": 10, "glide": 5, "turn": -1, "fade": 2, "stability": ""}]
    inv.refresh_manufacturer(catalog)
    d = inv.all_discs()[0]
    assert d.cached.origin == "local"                       # untouched
    assert d.cached.turn is None                            # local partial specs preserved
    assert d.cached.manufacturer_notes == ["Long forward push"]


def test_refresh_still_updates_discit_mold(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))                # origin defaults "discit"
    inv.refresh_manufacturer([dict(MAKO3, fade=1)])
    assert inv.all_discs()[0].cached.fade == 1              # discit mold refreshes as before
```

- [ ] **Step 2 — Run, expect FAIL** (local mold currently gets overwritten / no-op only on name miss).

- [ ] **Step 3 — Implement.** In `OwnedDisc.refresh_from_db(self, db_discs)`, return early when the mold is not catalog-backed:
```python
    def refresh_from_db(self, db_discs):
        if self.cached.origin != "discit":     # local / other-catalog molds are authoritative
            return False
        ... (existing exact-match refresh) ...
```
`refresh_manufacturer`/`sync` call `refresh_from_db` per disc, so this is the single choke point. (Generalization to per-catalog origin matching is v-future; v1 protects `origin != "discit"`.)

- [ ] **Step 4 — Run, expect PASS**; full suite `-q` PASS.
- [ ] **Step 5 — Commit:** "sync never overwrites non-discit (local) molds".

### ✅ Phase 4 acceptance
`sync`/`refresh` leaves `origin != "discit"` molds (local prototypes, homemade) untouched — partial specs, provenance, and notes preserved — while `discit` molds refresh exactly as today. Full suite green.

---

## Phase 5 — Documentation

### Task 5.1 — README + CHANGELOG

**Files:** Modify `README.md`, `CHANGELOG.md`.

- [ ] **Step 1 — README.** In the Organization/Common command area, document `add --prototype` (local-mold authoring with partial flight), the canonical-identity rule, `edit` filling flight/provenance, `list --prototype`, and that incomplete-flight discs are tracked but not used by flight analysis until published (or you record a personal flight). Match house style; keep the mold/inventory/bag terminology.
- [ ] **Step 2 — CHANGELOG.** Add an "Added" entry:
```markdown
- Prototype / partially-known molds: author a local mold with `add --prototype` (partial flight
  stays unknown, never zeroed), record manufacturer notes and Premier/release provenance, and
  fill numbers with `edit` as they're published. Incomplete-flight discs are fully tracked
  (inventory, bag, usage, favorites, history) but sit out flight-based analysis until complete.
  `list --prototype` filters them; catalog sync never overwrites local molds.
```
- [ ] **Step 3 — Run** `./.venv/bin/python -m pytest -q` (docs-only; green).
- [ ] **Step 4 — Commit:** "Document prototype / partial-manufacturer-spec support".

### ✅ Phase 5 acceptance
Docs match shipped behavior; full suite green.

---

## Fixtures (shared across tests)

Add to `tests/test_cli.py` (and reuse where useful):

```python
COMANCHE_NXTG = {"name": "Comanche", "brand": "Gateway", "category": "",
                 "speed": 10, "glide": None, "turn": None, "fade": None, "stability": "",
                 "release_status": "prototype", "origin": "local", "program": "Premier Membership",
                 "release": "2026-07",
                 "manufacturer_notes": ["Experimental Comanche top", "Excellent resistance to turn",
                                        "Long forward push", "Dependable fade"]}
WIZARD_OS = {"name": "Wizard OS", "brand": "Gateway", "category": "Putter",
             "speed": 3, "glide": 3, "turn": 0, "fade": 2.5, "stability": "",
             "release_status": "prototype", "origin": "local", "program": "Premier Membership",
             "release": "2026-07",
             "manufacturer_notes": ["Scented", "Blunt nose", "Subtle thumb track"]}
```
- **Independence acceptance:** `WIZARD_OS` has `release_status="prototype"` **and** complete flight → `has_flight`/`flight_known` True → appears in `choose`/`overlap`/coverage like any disc. `COMANCHE_NXTG` is Unknown → excluded from those but present in list/show/bag/usage. The Floating Comanche is a second copy of mold `Comanche` (same fixture, different `--plastic`/`--weight`).

## Subsystems modified (scope recap)

`inventory.py` (model, serialization, `refresh_from_db` origin), `roles.py` (predicates, None-safe, coverage filter), `analysis.py` (choose/practice/overlap filter, compare `—`), `recommend.py` (build-bag filter), `maturity.py` (flight-signal filter), `player.py` (None-safe access), `chart.py`/`braille.py` (skip Unknown), `cli.py` (add/edit/list/show/flight_str/validators/notes). Docs: `README.md`, `CHANGELOG.md`.

---

## Self-Review

**Spec coverage:** nullable flight (1.1) · `has_flight` derived (1.1) · `flight_known` + precedence (1.2, 2.1) · Unknown in every flight subsystem (2.2–2.4) · `release_status`/`origin`/`program`/`release`/`manufacturer_notes`/`edition` (1.1) · manufacturer-notes write-path separation (3.2) · canonical-identity validation (3.2) · local authoring + no DB match (3.2) · sync respects origin, never overwrites local (4.1) · CLI add/edit/list/show + outputs (3.1–3.3) · serialization/backward-compat/no-migration (1.1) · validation (3.2) · Wizard-OS independence (fixtures) · v2/v3 untouched. ✓

**Phased & green-per-phase:** each task is RED→GREEN→full-suite-green; Phase acceptance gates listed. Dependencies drawn at top. ✓

**Placeholder scan:** every code step shows complete code or an exact edit; no TBD. The one broad step (1.1/Step 5, "audit bare-Disc tests") is a concrete action with a defined fix (give the fixture explicit flight) — not a placeholder.

**Type consistency:** `flight_known`/`_personal_complete`/`_manufacturer_complete` (1.2) used unchanged in 2.x/3.x; `Disc.has_flight` (1.1) used in 3.1/4.1; `stability_number` now `Optional` (2.1) and its callers handle `None` (2.3 compare, 2.4); `_iso_month` (3.2) used in the add/edit parsers; new namespace fields on `_ns` in CLI tests match the parser dests.
