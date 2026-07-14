# `discbag compare` Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `discbag compare` with a derived Stability row and a rule-derived, relative-wording bottom-line verdict (overlap / key difference / how to use), plus an ownership footer when both discs are owned.

**Architecture:** Verdict logic is pure and lives in `analysis` (unit-tested on flight numbers); the Stability word/number logic is consolidated into one shared helper in `roles`; `cmd_compare` renders table + verdict + ownership footer. Stock numbers only — no "for-you" flight, no absolute distance.

**Tech Stack:** Python 3.14, argparse CLI, dataclasses, pytest.

## Global Constraints

- **Stock numbers only.** No `personal_flight` / "for-you" column; no absolute distance estimate.
- **Stability is broad-category shorthand.** The table may show the absolute word (`neutral`, `overstable`, …); the two-disc verdict must use **relative** wording ("the Wraith is *more* overstable *than* the Wave"), never an absolute declaration ("the Wraith is overstable").
- **Overlap is neutral.** Label the section `Overlap:` — never "Do you need both?"; describe overlap, don't judge it.
- **Softened throwing note.** When discs differ in fade/stability, state the more-overstable disc finishes left more strongly and that this is built into the discs, *while acknowledging an unusually early fade can still reflect the throw*. Never claim a stronger fade means the throw was correct.
- **Three-part verdict only for exactly two discs.** 3+ discs get a short degraded note; the table still renders for all.
- **Ownership footer only when every compared disc is owned**, from real usage/favorite data — never an invented confidence metric.
- **Command surface unchanged:** `discbag compare <name…>`.
- **Consolidation preserves behavior**; leave `OwnedDisc.stability` (manufacturer string) untouched.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Test runner: `./.venv/bin/python -m pytest`. Suite must stay green.

---

### Task 1: Consolidate the stability helper into `roles`

**Files:**
- Modify: `discbag/roles.py` (add two shared helpers)
- Modify: `discbag/cli.py` (remove local `_stability_word`, use `roles.stability_word`)
- Modify: `discbag/chart.py`, `discbag/braille.py`, `discbag/recommend.py` (delegate to the shared helper)
- Test: `tests/test_roles.py`

**Interfaces:**
- Produces: `roles.stability_number(disc) -> float` (= `float(disc.turn) + float(disc.fade)`); `roles.stability_word(stab) -> str` (the existing threshold mapping). Later tasks call both.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_roles.py`:

```python
def test_stability_number_is_turn_plus_fade():
    from discbag import roles
    from discbag.inventory import Disc
    d = Disc(name="X", speed=11, glide=5, turn=-2, fade=3)
    assert roles.stability_number(d) == 1.0


def test_stability_word_thresholds():
    from discbag import roles
    assert roles.stability_word(-2) == "very understable"
    assert roles.stability_word(-1) == "understable"
    assert roles.stability_word(0) == "neutral"
    assert roles.stability_word(2) == "overstable"
    assert roles.stability_word(3) == "very overstable"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_roles.py -k stability -v`
Expected: FAIL — `AttributeError: module 'discbag.roles' has no attribute 'stability_number'`

- [ ] **Step 3: Add the shared helpers to `roles.py`**

In `discbag/roles.py`, after the imports (below `from discbag import player`), add:

```python
def stability_number(disc):
    """A single overall-stability number: turn + fade (negative = understable)."""
    return float(disc.turn) + float(disc.fade)


def stability_word(stab):
    """Map a stability number to a broad category word."""
    if stab <= -2:
        return "very understable"
    if stab <= -0.5:
        return "understable"
    if stab < 1.5:
        return "neutral"
    if stab < 3:
        return "overstable"
    return "very overstable"
```

- [ ] **Step 4: Run the new test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_roles.py -k stability -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Delegate the three duplicate number-helpers and remove the word duplicate**

In `discbag/chart.py`, add `from discbag import roles` to the imports (below `from discbag import braille`), and replace the `stability` function body:

```python
def stability(disc):
    """A single overall-stability number: turn + fade (negative = understable)."""
    return roles.stability_number(disc)
```

In `discbag/braille.py`, add `from discbag import roles` to the top of the file (after the module docstring), and replace `_stability`:

```python
def _stability(disc):
    return roles.stability_number(disc)
```

In `discbag/recommend.py` (already imports `roles`), replace `_stability`:

```python
def _stability(disc):
    return roles.stability_number(disc)
```

In `discbag/cli.py`: change the top import line to include `roles`:

```python
from discbag import db, history, player, roles
```

Delete the local `_stability_word` function (the `def _stability_word(stab): …` block), and change its one call site (currently `word = _stability_word(f.turn + f.fade)`) to:

```python
        word = roles.stability_word(f.turn + f.fade)
```

- [ ] **Step 6: Run the full suite to confirm behavior is unchanged**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (all previously-green tests still pass — `test_chart.py`'s `chart.stability` checks included).

- [ ] **Step 7: Commit**

```bash
git add discbag/roles.py discbag/cli.py discbag/chart.py discbag/braille.py discbag/recommend.py tests/test_roles.py
git commit -m "Consolidate stability helper into roles (behavior-preserving)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Add the Stability row to `analysis.compare`

**Files:**
- Modify: `discbag/analysis.py` (`compare`)
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: `roles.stability_number`, `roles.stability_word` (Task 1). `analysis` already imports `roles`.
- Produces: `analysis.compare(discs)` Table now includes a `"Stability"` row (word per disc) between Fade and Role.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_analysis.py` (module-level fixtures WAVE/WRAITH, used here and in Task 3):

```python
WAVE = Disc(name="Wave", brand="MVP", category="Distance Driver",
            speed=11, glide=5, turn=-2, fade=2)
WRAITH = Disc(name="Wraith", brand="Innova", category="Distance Driver",
              speed=11, glide=5, turn=-1, fade=3)


def test_compare_includes_stability_row():
    table = analysis.compare([WAVE, WRAITH])
    stab = next(r for r in table.rows if r.label == "Stability")
    assert stab.values == ["neutral", "overstable"]   # Wave 0, Wraith 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_analysis.py -k stability_row -v`
Expected: FAIL — `StopIteration` (no "Stability" row).

- [ ] **Step 3: Add the Stability row**

In `discbag/analysis.py`, in `compare`, insert the Stability row between Fade and Role:

```python
        Row("Fade", [d.fade for d in discs]),
        Row("Stability",
            [roles.stability_word(roles.stability_number(d)) for d in discs]),
        Row("Role", [_role_of(d) for d in discs]),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_analysis.py -k "stability_row or compare" -v`
Expected: PASS (new test passes; the existing `test_compare_*` tests still pass — they assert specific labels, unaffected by the added row).

- [ ] **Step 5: Commit**

```bash
git add discbag/analysis.py tests/test_analysis.py
git commit -m "Add derived Stability row to compare table

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: The verdict builder — `analysis.compare_verdict`

**Files:**
- Modify: `discbag/analysis.py` (add verdict functions + a near-duplicate constant)
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: `_flight_distance` (module-private, in `analysis`), `roles.primary_role`, `roles.stability_number`.
- Produces: `analysis.compare_verdict(discs) -> str | None`. For exactly two discs, a three-part block (`Bottom line` / `Overlap:` / `Key difference:` / `How to use them:`). For 3+ discs, a one-line degraded note. `None` for fewer than two.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_analysis.py`:

```python
def test_verdict_two_discs_has_three_labeled_sections():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert "Bottom line" in v
    assert "Overlap:" in v
    assert "Key difference:" in v
    assert "How to use them:" in v


def test_verdict_key_difference_matches_target_wording():
    v = analysis.compare_verdict([WAVE, WRAITH])
    # Relative, per-disc trait sentences (reproduces the approved example).
    assert "The Wave has more high-speed turn and a gentler finish." in v
    assert "The Wraith resists turning more and fades harder." in v


def test_verdict_uses_relative_not_absolute_stability():
    v = analysis.compare_verdict([WAVE, WRAITH])
    # No absolute "is overstable"/"is understable" declaration in the verdict.
    assert "is overstable" not in v
    assert "is understable" not in v


def test_verdict_same_slot_but_different_for_wave_wraith():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert "same broad distance driver slot" in v.lower()
    assert "meaningfully different" in v


def test_verdict_how_to_use_has_softened_fade_caveat():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert "finish left more strongly" in v
    assert "can still reflect the throw" in v
    # more-overstable disc (Wraith) is the one that finishes left more strongly
    assert "Expect the Wraith to finish left more strongly than the Wave" in v


def test_verdict_three_plus_is_degraded_note():
    third = Disc(name="Firebird", brand="Innova", category="Distance Driver",
                 speed=9, glide=3, turn=0, fade=4)
    v = analysis.compare_verdict([WAVE, WRAITH, third])
    assert "Key difference:" not in v          # no three-part verdict
    assert "Most similar:" in v
    assert "Most distinct:" in v
    # Wave & Wraith are the closest pair; Firebird the most distinct.
    assert "Wave" in v and "Wraith" in v and "Firebird" in v
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_analysis.py -k verdict -v`
Expected: FAIL — `AttributeError: module 'discbag.analysis' has no attribute 'compare_verdict'`

- [ ] **Step 3: Implement the verdict functions**

In `discbag/analysis.py`, near the `compare` function, add the near-duplicate constant beside `OVERLAP_THRESHOLD`:

```python
# For the compare *verdict*: discs within this weighted flight-distance read as
# "largely duplicate". Stricter than OVERLAP_THRESHOLD (which loosely groups the
# `overlap` command) so that e.g. Wave vs Wraith reads as "same slot, different",
# not "duplicate". Tunable.
NEAR_DUPLICATE_DISTANCE = 1.0
```

Then add the verdict functions (below `compare`):

```python
def _join_and(items):
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _disc_traits(disc, other):
    """Relative flight traits of `disc` vs `other`, split so sentences read
    naturally: (noun phrases that follow "has", standalone verb phrases)."""
    has_nps, verbs = [], []
    if disc.turn < other.turn:
        has_nps.append("more high-speed turn")
    elif disc.turn > other.turn:
        verbs.append("resists turning more")
    if disc.fade > other.fade:
        verbs.append("fades harder")
    elif disc.fade < other.fade:
        has_nps.append("a gentler finish")
    if disc.speed > other.speed:
        has_nps.append("a higher speed ceiling")
    elif disc.speed < other.speed:
        verbs.append("is a touch slower")
    return has_nps, verbs


def _trait_sentence(disc, other):
    has_nps, verbs = _disc_traits(disc, other)
    parts = []
    if has_nps:
        parts.append("has " + _join_and(has_nps))
    parts.extend(verbs)
    if not parts:
        return f"The {disc.name} flies almost identically."
    return f"The {disc.name} " + _join_and(parts) + "."


def _overlap_text(a, b):
    dist = _flight_distance(a, b)
    role_a = roles.primary_role(a).name
    role_b = roles.primary_role(b).name
    same_role = role_a == role_b
    if dist <= NEAR_DUPLICATE_DISTANCE:
        where = f" in the {role_a.lower()} slot" if same_role else ""
        return f"These fly very similarly and largely duplicate each other{where}."
    if same_role:
        return (f"These occupy the same broad {role_a.lower()} slot, but their "
                "flights are meaningfully different.")
    return (f"These fill different roles — {role_a} vs {role_b} — and "
            "complement each other.")


def _how_to_use_text(a, b):
    # More overstable = higher turn+fade; break ties by fade, then speed.
    key = lambda d: (roles.stability_number(d), d.fade, d.speed)
    over, under = (a, b) if key(a) >= key(b) else (b, a)
    text = (f"Reach for the {under.name} when you want easier distance and more "
            f"movement before the fade. Reach for the {over.name} when you want a "
            f"stronger finish or more resistance to wind.")
    if a.fade != b.fade or roles.stability_number(a) != roles.stability_number(b):
        text += (f" Expect the {over.name} to finish left more strongly than the "
                 f"{under.name}. That difference is built into the discs, although "
                 "an unusually early fade can still reflect the throw.")
    return text


def _degraded_note(discs):
    idx = range(len(discs))
    pairs = [(i, j) for i in idx for j in idx if i < j]
    ci, cj = min(pairs, key=lambda p: _flight_distance(discs[p[0]], discs[p[1]]))
    dist_total = lambda i: sum(_flight_distance(discs[i], discs[j])
                               for j in idx if j != i)
    di = max(idx, key=dist_total)
    return (f"Most similar: {discs[ci].name} and {discs[cj].name}. "
            f"Most distinct: {discs[di].name}.")


def compare_verdict(discs):
    """A rule-derived bottom line. Three-part relative verdict for exactly two
    discs; a one-line degraded note for 3+; None for fewer than two."""
    if len(discs) < 2:
        return None
    if len(discs) > 2:
        return _degraded_note(discs)
    a, b = discs
    key_diff = _trait_sentence(a, b) + " " + _trait_sentence(b, a)
    return (
        "Bottom line\n\n"
        f"Overlap:\n{_overlap_text(a, b)}\n\n"
        f"Key difference:\n{key_diff}\n\n"
        f"How to use them:\n{_how_to_use_text(a, b)}"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_analysis.py -k verdict -v`
Expected: PASS (6 passed).

Note: `test_verdict_same_slot_but_different_for_wave_wraith` depends on `roles.primary_role` assigning Wave and Wraith the same role name. If it fails on that assertion, STOP and report — it signals the role engine classifies them differently, which is a real finding, not a test to force.

- [ ] **Step 5: Commit**

```bash
git add discbag/analysis.py tests/test_analysis.py
git commit -m "Add rule-derived compare verdict (overlap, key difference, how-to-use)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Wire the verdict and ownership footer into `cmd_compare`

**Files:**
- Modify: `discbag/cli.py` (`cmd_compare`; add `_ownership_footer`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `analysis.compare`, `analysis.compare_verdict` (Tasks 2–3); `_resolve_disc`; `OwnedDisc.user.round_count`, `.favorite`.
- Produces: `discbag compare` output = table, then verdict (if any), then ownership footer (only when every compared disc is owned).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
WAVE = {"name": "Wave", "brand": "MVP", "category": "Distance Driver",
        "speed": 11, "glide": 5, "turn": -2, "fade": 2, "stability": ""}
WRAITH = {"name": "Wraith", "brand": "Innova", "category": "Distance Driver",
          "speed": 11, "glide": 5, "turn": -1, "fade": 3, "stability": ""}


def test_cmd_compare_prints_table_verdict_and_footer(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [WAVE, WRAITH]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(WAVE))
    inv.add(OwnedDisc.from_db_record(WRAITH))
    for i in range(2):
        inv.record_use("wave", f"2026-07-0{i+1}T00:00:00+00:00")
    for i in range(3):
        inv.record_use("wraith", f"2026-07-0{i+1}T00:00:00+00:00")
    inv.set_favorite("wave", True)
    cli.cmd_compare(_ns(discs=["wave", "wraith"]), inv)
    out = capsys.readouterr().out
    assert "Stability" in out                       # richer table
    assert "Bottom line" in out and "Overlap:" in out
    assert "Key difference:" in out and "How to use them:" in out
    assert "You've thrown" in out                   # ownership footer
    # Footer format: only the first disc carries the "rounds" unit (args order).
    assert "the wave 2 rounds" in out.lower() and "the wraith 3" in out.lower()
    assert "favorite" in out.lower()                # Wave is a favorite


def test_cmd_compare_no_footer_when_a_disc_is_db_only(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [WAVE, WRAITH]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(WAVE))         # only Wave owned; Wraith from DB
    cli.cmd_compare(_ns(discs=["wave", "wraith"]), inv)
    out = capsys.readouterr().out
    assert "Bottom line" in out                     # verdict still shows
    assert "You've thrown" not in out               # but no ownership footer
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k cmd_compare -v`
Expected: FAIL — the footer and verdict assertions fail (current `cmd_compare` prints only the table).

- [ ] **Step 3: Add the ownership footer helper**

In `discbag/cli.py`, add near the other formatting helpers:

```python
def _ownership_footer(discs):
    """A light line of real usage/favorite data — only when every compared disc
    is owned (a database-only disc has no usage). None otherwise."""
    if any(getattr(d, "user", None) is None for d in discs):
        return None
    parts = []
    for i, d in enumerate(discs):
        unit = " rounds" if i == 0 else ""
        parts.append(f"the {d.name} {d.user.round_count}{unit}")
    line = "You've thrown " + ", ".join(parts) + "."
    favs = [d.name for d in discs if d.user.favorite]
    if favs:
        names = _join_and([f"the {n}" for n in favs])
        verb = "is a favorite" if len(favs) == 1 else "are favorites"
        line += f" {names[0].upper() + names[1:]} {verb}."
    return line
```

Add a local `_join_and` to `cli.py` (or import from analysis). To avoid a new dependency edge, add this small helper next to `_ownership_footer`:

```python
def _join_and(items):
    items = list(items)
    if len(items) <= 1:
        return items[0] if items else ""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
```

- [ ] **Step 4: Wire verdict + footer into `cmd_compare`**

In `discbag/cli.py`, replace the body of `cmd_compare` after the resolve loop:

```python
    print(_render_table(analysis.compare(discs)))
    verdict = analysis.compare_verdict(discs)
    if verdict:
        print()
        print(verdict)
    footer = _ownership_footer(discs)
    if footer:
        print()
        print(footer)
    return 0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k cmd_compare -v`
Expected: PASS (2 passed).

- [ ] **Step 6: End-to-end check against a throwaway bag**

Run:
```bash
HOME=$(mktemp -d) bash -c '
  P="./.venv/bin/python"
  for d in "MVP Wave" "Innova Wraith"; do
    $P -c "from discbag.cli import main; import sys; sys.argv=[\"discbag\",\"add\",\"$d\",\"--yes\"]; main()"
  done
  $P -c "from discbag.cli import main; import sys; sys.argv=[\"discbag\",\"compare\",\"wave\",\"wraith\"]; main()"
'
```
Expected: a table with a Stability row, then a "Bottom line" block (Overlap / Key difference / How to use them), then a "You've thrown …" footer.

- [ ] **Step 7: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Render compare verdict and ownership footer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Documentation

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the README**

Read `README.md`, find the `compare` reference in the Analysis section, and expand it to match the house style. Content to convey:

```markdown
`compare` now shows more than the raw numbers. Alongside speed/glide/turn/fade it
adds a derived **Stability** row, and — when you compare exactly two discs — a plain
bottom line: how much the two overlap, their key difference (in relative terms), and
when to reach for each. If both discs are in your bag, it closes with how many rounds
you've thrown each. Comparing three or more discs shows the table plus a short note on
the most similar and most distinct.

    discbag compare wave wraith
```

- [ ] **Step 2: Update the CHANGELOG**

In `CHANGELOG.md`, under the top/unreleased `### Added` (or equivalent) section, add:

```markdown
- `discbag compare` now adds a derived Stability row and, for two discs, a
  rule-derived bottom line (overlap, key difference in relative terms, and how to
  use each), plus an ownership footer when both discs are in your bag.
```

- [ ] **Step 3: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (all green).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Document the enriched compare command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Command surface unchanged → Task 4 keeps `compare <name…>`. ✓
- Richer table with Stability row, stock numbers, no distance → Task 2. ✓
- Two-disc three-part verdict (Overlap/Key difference/How to use) → Task 3 `compare_verdict`. ✓
- Neutral `Overlap:` framing → Task 3 `_overlap_text`, `test_verdict_*`. ✓
- Relative wording, no absolute stability declaration → Task 3 `_trait_sentence`; `test_verdict_uses_relative_not_absolute_stability`. ✓
- Softened fade caveat → Task 3 `_how_to_use_text`; `test_verdict_how_to_use_has_softened_fade_caveat`. ✓
- Ownership footer only when both owned, real data → Task 4 `_ownership_footer`; both CLI tests. ✓
- 3+ degradation → Task 3 `_degraded_note`; `test_verdict_three_plus_is_degraded_note`. ✓
- Stability = broad shorthand; consolidate helper; leave `OwnedDisc.stability` → Task 1; Task 1 Step 6 runs full suite incl. `test_chart`. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `roles.stability_number`/`roles.stability_word` defined in Task 1 and used with those exact names in Tasks 2–3; `analysis.compare_verdict(discs) -> str|None` defined in Task 3 and called in Task 4; `_ownership_footer(discs)` and `_join_and(items)` defined and used within Task 4; `_flight_distance`, `roles.primary_role`, `OVERLAP_THRESHOLD` referenced exist in the current code. ✓
