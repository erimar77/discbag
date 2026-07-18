# Collection Maturity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `discbag maturity` command that qualitatively tells a player where their collection sits today (Discovery / Developing / Developed) and why, with grounded usage insights and observed preferences.

**Architecture:** A new pure `maturity.py` (analysis layer) exposes small, independently-testable functions over owned discs — no I/O, no wall-clock (a `today: date` is injected). The CLI (`cmd_maturity`) composes them and renders, colorized in a terminal and plain when piped, like `render_dashboard`. Reuses `roles.assess`, `roles.stability_number`, and `analysis.overlap`.

**Tech Stack:** Python 3.9+, dataclasses, pytest. Runner: `./.venv/bin/python -m pytest`.

## Global Constraints

- **Qualitative only** — no score, no percentage, no star rating. Output is a phase label plus a `✓`/`•` "why" list. (A per-category concentration *percentage inside an insight sentence* — "84% of throws" — is allowed; a maturity score is not.)
- **Only grounded signals** — every statement derives from real data (coverage, usage, favorites, dates, flight, brand). Never mention plastic tier or rim width.
- **Read-only, no new persistence.** No progression/snapshots in this feature.
- **Two required signals gate the phase:** sufficient usage + settled usage. New-mold restraint and established favorites are **supporting** (shown in the "why," never flip the phase).
- **Coverage gate:** a *meaningful gap* = a role that is missing, **not optional**, and **High or Medium** priority. Missing Low-priority or optional roles never force Discovery.
- **Refinement ≠ exploration:** the new-mold signal counts only distinct molds whose *first* acquisition (across all copies, active or archived) is recent; a backup/replacement/plastic-or-weight variant/rebuy of an owned mold never counts.
- **Determinism:** all age math uses the injected `today` (a `datetime.date`); no wall-clock reads in `maturity.py`.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Full suite must stay green.

## File structure

- Create `discbag/maturity.py` — pure maturity logic (phase, insights, preferences).
- Create `tests/test_maturity.py` — unit tests for the pure logic.
- Modify `discbag/cli.py` — add `cmd_maturity`, register the subparser, add the help-group entry.
- Modify `tests/test_cli.py` — CLI-level test.
- Modify `README.md`, `CHANGELOG.md` — docs.

---

### Task 1: Phase model (`maturity.py` core)

**Files:**
- Create: `discbag/maturity.py`
- Test: `tests/test_maturity.py`

**Interfaces:**
- Consumes: `roles.assess(bag, profile) -> [RoleCoverage]` where `RoleCoverage` has `.covered` (bool), `.priority` (str: "Satisfied"/"High"/"Medium"/"Low"), `.role.optional` (bool), `.role.name` (str). `OwnedDisc.user` fields: `.use_count` (int), `.last_used` (str|None), `.favorite` (bool), `.date_added` (str|None); `OwnedDisc.brand`, `.mold`, `.speed`.
- Produces: `maturity.Signal(met: bool, text: str)`; `maturity.assess_phase(active, all_discs, profile, today) -> (phase: str, signals: list[Signal])` with phase in `{"Discovery","Developing","Developed"}`. Also the individually-testable signal functions `sufficient_usage(active, today)`, `settled_core(active)`, `not_chasing_new_molds(all_discs, today)`, `established_favorites(active)`, all returning `Signal`. Module constants (`MIN_USES`, etc.).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_maturity.py`:

```python
from datetime import date

from discbag import maturity
from discbag.inventory import OwnedDisc


def owned(mold, *, brand="Innova", speed=5, category="Midrange",
          turn=0, fade=1, uses=0, last=None, fav=False, added="2026-01-01"):
    rec = {"name": mold, "brand": brand, "category": category,
           "speed": speed, "glide": 5, "turn": turn, "fade": fade, "stability": ""}
    return OwnedDisc.from_db_record(rec, use_count=uses, last_used=last,
                                    favorite=fav, date_added=added)


TODAY = date(2026, 7, 14)


# ---------- individual signals ----------

def test_sufficient_usage_true_when_enough_and_recent():
    bag = [owned("Buzzz", uses=8, last="2026-07-10"),
           owned("Roc", uses=5, last="2026-07-01")]
    s = maturity.sufficient_usage(bag, TODAY)
    assert s.met is True


def test_sufficient_usage_false_when_too_few_uses():
    bag = [owned("Buzzz", uses=3, last="2026-07-10")]
    s = maturity.sufficient_usage(bag, TODAY)
    assert s.met is False
    assert "recorded use" in s.text.lower()


def test_sufficient_usage_false_when_stale():
    bag = [owned("Buzzz", uses=20, last="2026-01-01")]   # >90 days before TODAY
    s = maturity.sufficient_usage(bag, TODAY)
    assert s.met is False


def test_settled_core_true_when_concentrated():
    # 90 uses on 2 discs, 5 more discs barely used -> a small core carries most throws.
    bag = [owned("Buzzz", uses=50), owned("Roc", uses=40)]
    bag += [owned(f"D{i}", uses=1) for i in range(5)]
    s = maturity.settled_core(bag)
    assert s.met is True
    assert "discs" in s.text


def test_settled_core_false_when_spread_out():
    bag = [owned(f"D{i}", uses=5) for i in range(9)]      # even spread, no core
    s = maturity.settled_core(bag)
    assert s.met is False


def test_settled_core_false_with_no_usage():
    assert maturity.settled_core([owned("Buzzz", uses=0)]).met is False


def test_new_molds_counts_only_new_molds_recently():
    # Two copies of Wave (one old, one recent) = refinement, not a new mold.
    all_discs = [
        owned("Wave", brand="MVP", added="2024-01-01"),
        owned("Wave", brand="MVP", added="2026-07-01"),   # backup, recent
        owned("Roc", added="2020-01-01"),
    ]
    s = maturity.not_chasing_new_molds(all_discs, TODAY)
    assert s.met is True                                  # no NEW mold recently


def test_new_molds_flags_genuinely_new_recent_molds():
    all_discs = [owned("Roc", added="2020-01-01"),
                 owned("Zone", added="2026-07-01"),        # new mold, recent
                 owned("Buzzz", added="2026-07-02")]       # new mold, recent
    s = maturity.not_chasing_new_molds(all_discs, TODAY)
    assert s.met is False                                  # 2 new > MAX_RECENT_NEW_MOLDS (1)
    assert "experimenting" in s.text.lower()


def test_established_favorites_threshold():
    bag = [owned("A", fav=True), owned("B", fav=True), owned("C", fav=True)]
    assert maturity.established_favorites(bag).met is True
    assert maturity.established_favorites([owned("A", fav=True)]).met is False


# ---------- assess_phase (gate + resolution), roles.assess monkeypatched ----------

class _FakeRole:
    def __init__(self, name, optional=False):
        self.name = name
        self.optional = optional


class _FakeCoverage:
    def __init__(self, covered, priority, optional=False, name="Role"):
        self.covered = covered
        self.priority = priority
        self.role = _FakeRole(name, optional)


def test_phase_discovery_when_meaningful_gap(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess",
                        lambda bag, profile=None: [_FakeCoverage(False, "High", name="Overstable mid")])
    phase, signals = maturity.assess_phase([owned("Buzzz", uses=20, last="2026-07-10")],
                                           [], None, TODAY)
    assert phase == "Discovery"
    assert any("overstable mid" in s.text.lower() for s in signals)


def test_phase_ignores_low_priority_and_optional_gaps(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [
        _FakeCoverage(True, "Satisfied"),
        _FakeCoverage(False, "Low", name="Utility driver"),      # low → not meaningful
        _FakeCoverage(False, "High", optional=True, name="2nd distance driver"),  # optional
    ])
    bag = [owned("Buzzz", uses=30, last="2026-07-10"), owned("Roc", uses=1)]
    phase, _ = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developed"


def test_phase_developed_when_covered_settled_and_used(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [_FakeCoverage(True, "Satisfied")])
    bag = [owned("Buzzz", uses=50, last="2026-07-10"), owned("Roc", uses=40, last="2026-07-08")]
    bag += [owned(f"D{i}", uses=1) for i in range(5)]
    phase, _ = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developed"


def test_phase_developing_when_usage_insufficient(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [_FakeCoverage(True, "Satisfied")])
    bag = [owned("Buzzz", uses=2, last="2026-07-10")]      # < MIN_USES
    phase, _ = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developing"


def test_developed_stays_developed_after_new_molds(monkeypatch):
    monkeypatch.setattr(maturity.roles, "assess", lambda bag, profile=None: [_FakeCoverage(True, "Satisfied")])
    # Settled core with real usage...
    bag = [owned("Buzzz", uses=50, last="2026-07-10"), owned("Roc", uses=40, last="2026-07-08")]
    bag += [owned(f"D{i}", uses=1) for i in range(5)]
    # ...plus two brand-new molds bought recently but barely thrown (curiosity).
    bag += [owned("Zone", added="2026-07-01", uses=0), owned("Mako3", added="2026-07-02", uses=0)]
    phase, signals = maturity.assess_phase(bag, bag, None, TODAY)
    assert phase == "Developed"                                    # not demoted
    assert any(("experimenting" in s.text.lower()) and not s.met for s in signals)  # supporting •
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discbag.maturity'`

- [ ] **Step 3: Implement `discbag/maturity.py`**

Create `discbag/maturity.py`:

```python
"""Collection maturity — a qualitative read of where a bag sits today, and why.

Pure functions over owned discs: no I/O, no wall-clock (a `today: date` is injected).
The CLI composes and renders these; keep rendering out of here.
"""

import math
from dataclasses import dataclass
from datetime import date

from discbag import roles

# --- tunable constants (see the design spec) ---
MIN_USES = 10                # recorded uses before "settled" can be judged
ACTIVE_WINDOW = 90           # days: "thrown recently"
CONCENTRATION = 0.80         # share of throws a "core" must cover
CORE_FRACTION = 1 / 3        # max core size as a fraction of the active bag
RECENT_WINDOW = 180          # days: a "recently introduced" new mold
MAX_RECENT_NEW_MOLDS = 1     # new molds recently before the note reads "experimenting"
MIN_FAVORITES = 3            # supporting "established favorites" threshold


@dataclass
class Signal:
    met: bool
    text: str


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _uses(disc):
    return disc.user.use_count or 0


def _meaningful_gaps(assessment):
    """Missing, non-optional roles that matter to this player now (High/Medium)."""
    return [rc for rc in assessment
            if not rc.covered and not rc.role.optional
            and rc.priority in ("High", "Medium")]


def sufficient_usage(active, today):
    """Required: enough recorded throws, thrown recently, to judge settledness."""
    total = sum(_uses(d) for d in active)
    last = max((dt for dt in (_parse_date(d.user.last_used) for d in active) if dt),
               default=None)
    recent = last is not None and (today - last).days <= ACTIVE_WINDOW
    met = total >= MIN_USES and recent
    if total < MIN_USES:
        text = f"Only {total} recorded uses — log a few rounds to judge (need {MIN_USES})"
    elif not recent:
        text = "No rounds logged recently — throw your bag to confirm it's settled"
    else:
        text = f"{total} recorded uses, thrown recently"
    return Signal(met, text)


def settled_core(active):
    """Required: a small core carries most throws."""
    counts = sorted((_uses(d) for d in active), reverse=True)
    total = sum(counts)
    if total == 0:
        return Signal(False, "No usage recorded yet")
    target = CONCENTRATION * total
    acc = core = 0
    for c in counts:
        if acc >= target:
            break
        acc += c
        core += 1
    max_core = max(1, math.ceil(len(active) * CORE_FRACTION))
    met = core <= max_core
    pct = round(100 * acc / total)
    if met:
        text = f"{pct}% of your throws use just {core} discs — you've settled on a core"
    else:
        text = f"your throws are still spread across {core} discs — no settled core yet"
    return Signal(met, text)


def not_chasing_new_molds(all_discs, today):
    """Supporting: distinct molds whose first acquisition is recent. A backup/
    replacement/variant/rebuy of an owned mold introduces no new mold."""
    earliest = {}
    for d in all_discs:
        da = _parse_date(d.user.date_added)
        if da is None:
            continue
        key = (str(d.brand).strip().lower(), str(d.mold).strip().lower())
        if key not in earliest or da < earliest[key]:
            earliest[key] = da
    recent = sum(1 for da in earliest.values() if (today - da).days <= RECENT_WINDOW)
    met = recent <= MAX_RECENT_NEW_MOLDS
    if recent == 0:
        text = "No new molds lately — you're refining what you own"
    elif met:
        text = f"Recent additions mostly refine molds you own ({recent} new)"
    else:
        text = f"You've added {recent} new molds recently — a little experimenting"
    return Signal(met, text)


def established_favorites(active):
    """Supporting: you've marked the discs you trust."""
    n = sum(1 for d in active if d.user.favorite)
    met = n >= MIN_FAVORITES
    if not n:
        text = "No favorites marked yet"
    elif met:
        text = f"{n} established favorites"
    else:
        text = f"{n} favorites so far — mark the discs you trust"
    return Signal(met, text)


def assess_phase(active, all_discs, profile, today):
    """(phase, signals). Coverage gates; among the covered, the two required usage
    signals decide Developed vs Developing. New-mold and favorite signals are
    supporting context only."""
    if not active:
        return "Discovery", [Signal(False, "Your bag is empty — add discs to get started")]
    gaps = _meaningful_gaps(roles.assess(active, profile))
    if gaps:
        signals = [Signal(False, f"Missing {rc.role.name.lower()} ({rc.priority.lower()} priority)")
                   for rc in gaps]
        return "Discovery", signals
    usage = sufficient_usage(active, today)        # required
    core = settled_core(active)                    # required
    supporting = [not_chasing_new_molds(all_discs, today), established_favorites(active)]
    signals = [Signal(True, "No meaningful coverage gaps"), usage, core, *supporting]
    phase = "Developed" if (usage.met and core.met) else "Developing"
    return phase, signals
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -v`
Expected: PASS (all phase-model tests green).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add discbag/maturity.py tests/test_maturity.py
git commit -m "Add collection-maturity phase model (coverage gate + settled-usage)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Usage insights

**Files:**
- Modify: `discbag/maturity.py`
- Test: `tests/test_maturity.py`

**Interfaces:**
- Consumes: the `owned(...)` test helper and `Signal`/constants from Task 1; `analysis.overlap(discs, profile=None) -> [group]`; `OwnedDisc.user.round_count`.
- Produces: `maturity.usage_insights(active, today) -> list[str]` (capped at `MAX_INSIGHTS`); helper `maturity._broad_category(disc) -> str` ("putter"/"midrange"/"fairway"/"driver").

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_maturity.py`:

```python
def test_broad_category_by_speed():
    assert maturity._broad_category(owned("Aviar", speed=2)) == "putter"
    assert maturity._broad_category(owned("Buzzz", speed=5)) == "midrange"
    assert maturity._broad_category(owned("Teebird", speed=7)) == "fairway"
    assert maturity._broad_category(owned("Wraith", speed=11)) == "driver"


def test_usage_insight_concentration():
    drivers = [owned("Wave", speed=11, uses=40), owned("Wraith", speed=11, uses=40)]
    drivers += [owned(f"Dr{i}", speed=11, uses=1) for i in range(4)]   # 6 drivers total
    out = maturity.usage_insights(drivers, TODAY)
    assert any("6 drivers" in s and "%" in s for s in out)


def test_usage_insight_neglected():
    bag = [owned("Buzzz", speed=5, uses=30, last="2026-07-10"),
           owned("Boss", speed=13, uses=2, last="2025-06-01")]   # >180 days stale
    out = maturity.usage_insights(bag, TODAY)
    assert any("Boss" in s and "month" in s.lower() for s in out)


def test_usage_insights_capped():
    # Build many candidate insights; result must not exceed MAX_INSIGHTS.
    bag = []
    for cat_speed in (2, 5, 7, 11):
        bag.append(owned(f"lead{cat_speed}", speed=cat_speed, uses=50, last="2026-07-10"))
        bag += [owned(f"n{cat_speed}_{i}", speed=cat_speed, uses=1, last="2024-01-01")
                for i in range(6)]
    out = maturity.usage_insights(bag, TODAY)
    assert len(out) <= maturity.MAX_INSIGHTS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -k "category or usage_insight" -v`
Expected: FAIL — `AttributeError: module 'discbag.maturity' has no attribute 'usage_insights'`

- [ ] **Step 3: Implement usage insights**

In `discbag/maturity.py`, add near the top (after the existing constants):

```python
NEGLECT_DAYS = 180           # unused this long → "neglected"
DOMINANT_SHARE = 0.50        # category-usage share that makes a disc the clear primary
MAX_INSIGHTS = 4             # cap on rendered usage insights
MIN_CATEGORY_DISCS = 5       # a category needs this many discs before "concentration" is worth noting
```

And add these functions (below `assess_phase`):

```python
def _broad_category(disc):
    speed = float(disc.speed)
    if speed <= 3:
        return "putter"
    if speed <= 5:
        return "midrange"
    if speed <= 8:
        return "fairway"
    return "driver"


def _by_category(active):
    groups = {}
    for d in active:
        groups.setdefault(_broad_category(d), []).append(d)
    return groups


def _plural(cat):
    return cat + "s"


def _concentration_insight(cat, discs):
    counts = sorted((_uses(d) for d in discs), reverse=True)
    total = sum(counts)
    if len(discs) < MIN_CATEGORY_DISCS or total == 0:
        return None
    target = CONCENTRATION * total
    acc = core = 0
    for c in counts:
        if acc >= target:
            break
        acc += c
        core += 1
    if core >= len(discs):            # not actually concentrated
        return None
    pct = round(100 * acc / total)
    return f"You own {len(discs)} {_plural(cat)}; {pct}% of those throws use {core} of them."


def _neglected_insight(active, today):
    stale = []
    for d in active:
        if not getattr(d.user, "in_bag", True):
            continue
        last = _parse_date(d.user.last_used)
        added = _parse_date(d.user.date_added)
        if last is not None:
            age = (today - last).days
        elif added is not None:
            age = (today - added).days       # never thrown; age since acquired
        else:
            continue
        if age > NEGLECT_DAYS:
            stale.append((age, d))
    if not stale:
        return None
    stale.sort(reverse=True)
    name = f"{stale[0][1].brand} {stale[0][1].mold}"
    months = stale[0][0] // 30
    return f"You haven't thrown your {name} in {months}+ months — it may not need a bag spot."


def _primary_backup_insight(active):
    from discbag import analysis
    for cat, discs in _by_category(active).items():
        total = sum(_uses(d) for d in discs)
        if total == 0 or len(discs) < 2:
            continue
        top = max(discs, key=_uses)
        if _uses(top) / total < DOMINANT_SHARE:
            continue
        # A backup exists if any other disc overlaps the primary's flight.
        others = [d for d in discs if d is not top]
        has_backup = any(top in g and any(o in g for o in others)
                         for g in analysis.overlap([top] + others))
        if not has_backup:
            return (f"Your {top.brand} {top.mold} is your most-thrown {cat} — "
                    "consider a backup before a new mold.")
    return None


def _category_leader_insight(active):
    best = None
    for cat, discs in _by_category(active).items():
        if len(discs) < 2:
            continue
        top = max(discs, key=lambda d: d.user.round_count)
        if top.user.round_count <= 0:
            continue
        if best is None or top.user.round_count > best[0]:
            best = (top.user.round_count, f"Your {top.brand} {top.mold} leads your "
                    f"{_plural(cat)} in rounds.")
    return best[1] if best else None


def usage_insights(active, today):
    """Grounded observations from usage history, most-salient first, capped."""
    groups = _by_category(active)
    candidates = []
    candidates.append(_neglected_insight(active, today))
    candidates.append(_primary_backup_insight(active))
    for cat, discs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        candidates.append(_concentration_insight(cat, discs))
    candidates.append(_category_leader_insight(active))
    out = [c for c in candidates if c]
    return out[:MAX_INSIGHTS]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -k "category or usage_insight" -v`
Expected: PASS.

- [ ] **Step 5: Run the full maturity suite**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add discbag/maturity.py tests/test_maturity.py
git commit -m "Add collection-maturity usage insights

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Observed preferences

**Files:**
- Modify: `discbag/maturity.py`
- Test: `tests/test_maturity.py`

**Interfaces:**
- Consumes: `roles.stability_number(disc) -> float`, `roles.stability_word(stab) -> str` (Task-independent, already in `roles`); `owned(...)` helper.
- Produces: `maturity.observed_preferences(active) -> list[str]` (each a plain observation; empty when no clear tendency).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_maturity.py`:

```python
def test_preferences_stability_lean():
    # A bag that leans overstable (turn+fade high).
    bag = [owned(f"OS{i}", turn=0, fade=3) for i in range(5)] + [owned("N", turn=-1, fade=1)]
    out = maturity.observed_preferences(bag)
    assert any("overstable" in s.lower() for s in out)


def test_preferences_brand_concentration():
    bag = [owned(f"I{i}", brand="Innova") for i in range(7)] + [owned("X", brand="MVP")]
    out = maturity.observed_preferences(bag)
    assert any("Innova" in s for s in out)


def test_preferences_empty_when_mixed():
    # Even split across brands and stabilities -> no confident observation.
    bag = [owned("A", brand="Innova", turn=-2, fade=0),
           owned("B", brand="Discraft", turn=0, fade=3),
           owned("C", brand="MVP", turn=-1, fade=1),
           owned("D", brand="Latitude 64", turn=1, fade=0)]
    out = maturity.observed_preferences(bag)
    assert not any("gravitate" in s.lower() for s in out)      # no stability lean claimed
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -k preferences -v`
Expected: FAIL — `AttributeError: module 'discbag.maturity' has no attribute 'observed_preferences'`

- [ ] **Step 3: Implement observed preferences**

In `discbag/maturity.py`, add the constant near the others:

```python
PREF_SHARE = 0.60            # share needed before a tendency is called out
```

And add (below `usage_insights`):

```python
def _stability_group(disc):
    stab = roles.stability_number(disc)
    if stab <= -0.5:
        return "understable"
    if stab < 1.5:
        return "neutral"
    return "overstable"


def _dominant(labels, share):
    """The single label holding >= share of the list, or None."""
    if not labels:
        return None
    counts = {}
    for x in labels:
        counts[x] = counts.get(x, 0) + 1
    label, n = max(counts.items(), key=lambda kv: kv[1])
    return label if n / len(labels) >= share else None


def observed_preferences(active):
    """Grounded tendencies, phrased as observations. Empty when nothing is clear."""
    out = []

    groups = [_stability_group(d) for d in active]
    lean = _dominant(groups, PREF_SHARE)
    if lean == "overstable":
        out.append("You gravitate to stable-to-overstable flights.")
    elif lean == "understable":
        out.append("You gravitate to understable flights.")
    elif lean == "neutral":
        out.append("You gravitate to neutral, straight-flying discs.")

    speeds = sorted(float(d.speed) for d in active)
    if len(speeds) >= 4:
        lo = speeds[len(speeds) // 10]
        hi = speeds[-(len(speeds) // 10) - 1]
        out.append(f"Your discs cluster around speed {int(lo)}–{int(hi)}.")

    brands = [str(d.brand) for d in active if str(d.brand)]
    counts = {}
    for b in brands:
        counts[b] = counts.get(b, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])
    if top and brands:
        lead = [b for b, n in top if n / len(brands) >= 0.25][:2]
        if lead and sum(counts[b] for b in lead) / len(brands) >= PREF_SHARE:
            out.append(f"Most of your bag is {' and '.join(lead)}.")

    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -k preferences -v`
Expected: PASS.

- [ ] **Step 5: Run the full maturity suite**

Run: `./.venv/bin/python -m pytest tests/test_maturity.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add discbag/maturity.py tests/test_maturity.py
git commit -m "Add collection-maturity observed preferences

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `discbag maturity` CLI command

**Files:**
- Modify: `discbag/cli.py` (add `cmd_maturity`, register subparser, add help-group entry)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `maturity.assess_phase`, `maturity.usage_insights`, `maturity.observed_preferences` (Tasks 1–3); existing `_use_color()`, `_styler(enabled)`, `player.load_profile()`, `inv.list_discs()`, `inv.all_discs()`.
- Produces: `cli.cmd_maturity(args, inv) -> int`; a `maturity` subcommand.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_cmd_maturity_developed(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    # A covered, settled, well-used bag. Monkeypatch not needed: give real coverage
    # via a broad speed spread and heavy concentrated usage.
    specs = [("Aviar", 2, 0, 2), ("Wizard", 2, 0, 1), ("Roc", 5, 0, 3),
             ("Buzzz", 5, -1, 1), ("Leopard", 6, -2, 1), ("Teebird", 7, 0, 2),
             ("Firebird", 9, 0, 4), ("Wraith", 11, -1, 3), ("Destroyer", 12, -1, 3)]
    for i, (mold, sp, tu, fa) in enumerate(specs):
        rec = {"name": mold, "brand": "Innova", "category": "x",
               "speed": sp, "glide": 5, "turn": tu, "fade": fa, "stability": ""}
        uses = 30 if i < 2 else 1                       # concentrate on 2 discs
        inv.add(OwnedDisc.from_db_record(rec, use_count=uses, last_used="2026-07-10",
                                         date_added="2025-01-01"))
    cli.cmd_maturity(_ns(), inv)
    out = capsys.readouterr().out
    assert "Collection Maturity" in out
    assert "Why:" in out
    # phase is one of the three labels
    assert any(p in out for p in ("Discovery", "Developing", "Developed"))


def test_cmd_maturity_empty_bag(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    cli.cmd_maturity(_ns(), inv)
    out = capsys.readouterr().out
    assert "Discovery" in out
    assert "empty" in out.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k cmd_maturity -v`
Expected: FAIL — `AttributeError: module 'discbag.cli' has no attribute 'cmd_maturity'`

- [ ] **Step 3: Implement `cmd_maturity`**

In `discbag/cli.py`, add the command function (near the other analysis commands such as `cmd_overlap`):

```python
def cmd_maturity(args, inv):
    """Where your collection sits today — Discovery, Developing, or Developed — and
    why, with grounded usage insights and observed preferences. Coaching, not a
    recommendation: it answers 'do I actually need anything?'"""
    from discbag import maturity
    prof = player.load_profile()
    profile = None if prof.is_empty() else prof
    today = datetime.now(timezone.utc).date()
    active = inv.list_discs()
    all_discs = inv.all_discs()

    phase, signals = maturity.assess_phase(active, all_discs, profile, today)
    insights = maturity.usage_insights(active, today)
    prefs = maturity.observed_preferences(active)

    color = _use_color()
    st = _styler(color)
    hue = {"Discovery": "yellow", "Developing": "cyan", "Developed": "green"}.get(phase, "cyan")

    print(st("Collection Maturity", "bold"))
    print(f"  {st(phase, 'bold', hue)}\n")
    print(st("Why:", "bold"))
    for s in signals:
        mark = st("✓", "green") if s.met else st("•", "dim")
        print(f"  {mark} {s.text}")

    tail = {
        "Discovery": "Keep exploring — every new disc still teaches you something.",
        "Developing": "You're close — more reps will tell you which discs you truly trust.",
        "Developed": ("Another disc is unlikely to improve your game right now.\n"
                      "Your biggest gains will come from throwing the discs you already own."),
    }[phase]
    print("\n" + tail)

    if insights:
        print("\n" + st("Usage insights", "bold"))
        for line in insights:
            print(f"  {line}")
    if prefs:
        print("\n" + st("Observed preferences", "bold"))
        for line in prefs:
            print(f"  {line}")
    return 0
```

- [ ] **Step 4: Register the subparser**

In `discbag/cli.py`, near the other Analysis subparsers (e.g. `p_overlap`), add:

```python
    sub.add_parser("maturity",
                   help="where your collection sits today, and why").set_defaults(func=cmd_maturity)
```

- [ ] **Step 5: Add the help-group entry**

In `discbag/cli.py`, in `_HELP_GROUPS` under the `"Analysis"` group, add after the `flight` line:

```python
        ("flight", "record how a disc flies for you"),
        ("maturity", "is your collection still growing, or settled?"),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k cmd_maturity -v`
Expected: PASS (2 passed).

- [ ] **Step 7: End-to-end check against a throwaway bag**

Run:
```bash
HOME=$(mktemp -d) bash -c '
  P="./.venv/bin/python"
  for d in Aviar Roc Buzzz Leopard Teebird Firebird Wraith Destroyer; do
    $P -c "from discbag.cli import main; import sys; sys.argv=[\"discbag\",\"add\",\"$d\",\"--yes\"]; main()" >/dev/null
  done
  $P -c "from discbag.cli import main; import sys; sys.argv=[\"discbag\",\"round-used\",\"buzzz\",\"roc\",\"buzzz\"]; main()" >/dev/null
  $P -c "from discbag.cli import main; import sys; sys.argv=[\"discbag\",\"maturity\"]; main()"
'
```
Expected: prints `Collection Maturity`, a phase, a `Why:` list, and (if any) insights/preferences.

- [ ] **Step 8: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (all green).

- [ ] **Step 9: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Add discbag maturity command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Update the README**

In `README.md`, in the **Analysis** command block, add a `maturity` line after `chart`:

```bash
discbag maturity                                    # where your collection sits today, and why
```

Then add a short prose paragraph after that block (match the surrounding tone):

```markdown
`maturity` is coaching, not shopping: it answers "do I actually need anything?" It reports a
qualitative phase — **Discovery** (real coverage gaps remain), **Developing** (covered, but your
throwing hasn't settled), or **Developed** (covered and settled — your gains now come from reps,
not molds) — always backed by explicit signals, never a score. It adds grounded usage insights
(concentration, neglected discs, a primary that wants a backup) and observed preferences
(stability, speed, and brand tendencies). Coverage gets you to the gate; how you actually throw
determines maturity, so a mature player can buy a new mold out of curiosity without dropping back.
```

- [ ] **Step 2: Update the CHANGELOG**

In `CHANGELOG.md`, under the top `### Added` section, add:

```markdown
- `discbag maturity` — a qualitative read of where your collection sits (Discovery / Developing /
  Developed) and why, with grounded usage insights and observed preferences. Answers "do I actually
  need anything?" rather than "what should I buy?"
```

- [ ] **Step 3: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (docs-only; all green).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Document the maturity command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Command `discbag maturity`, Analysis group, read-only, no persistence → Task 4. ✓
- Qualitative phase + `✓`/`•` why, no score → Task 1 (`assess_phase`), Task 4 rendering. ✓
- Coverage gate (meaningful = missing, non-optional, High/Medium) → Task 1 `_meaningful_gaps`; tested incl. Low/optional exclusion. ✓
- Required (sufficient usage, settled usage) vs supporting (new molds, favorites) → Task 1 `assess_phase`; tested incl. "developed stays developed after new molds." ✓
- Refinement ≠ exploration (mold-first-acquisition over all copies) → Task 1 `not_chasing_new_molds`; tested with backup + rebuy. ✓
- Usage insights (concentration, neglected, primary/backup, category leader), capped → Task 2. ✓
- Observed preferences (stability, speed, brand); plastic/rim excluded → Task 3 (only those three signals; no plastic/rim code). ✓
- Tunable constants → defined in Task 1/2/3 as module constants. ✓
- Determinism via injected `today` → all age math takes `today`; CLI passes `datetime.now(...).date()`. ✓
- Deferred (progression, plastic/rim, home-screen) → not implemented. ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code.

**Type consistency:** `Signal(met, text)` and `assess_phase(active, all_discs, profile, today)` defined in Task 1 and consumed unchanged in Task 4; `usage_insights(active, today)` and `observed_preferences(active)` defined in Tasks 2/3 and called with those exact signatures in Task 4; `_broad_category`, `_uses`, `_parse_date`, and all constants are defined before use. `roles.stability_number`/`stability_word`, `analysis.overlap`, `_use_color`/`_styler`, `player.load_profile`, `inv.list_discs`/`all_discs` all exist in the current codebase.
