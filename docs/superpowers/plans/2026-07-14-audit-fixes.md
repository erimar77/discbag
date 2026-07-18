# Audit-Fix Correctness Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the verified audit findings — restore-to-bag, per-copy bag ops, carry-bag semantics, input validation, the `score --situation` no-op, `build-bag --size` gap labeling, and history damage state — plus matching docs.

**Architecture:** Small, targeted changes to existing modules (`inventory.py`, `cli.py`, `recommend.py`) following current patterns. Each task is independently testable. No unrelated refactoring.

**Tech Stack:** Python 3.9+, argparse, dataclasses, pytest. Runner: `./.venv/bin/python -m pytest`.

## Global Constraints

- **Terminology:** **bag** = carried discs (`inv.filter(in_bag=True)`); **inventory** = active owned discs (`inv.list_discs()`). Immediate-use commands (`choose`, `practice`) use the **bag**; planning/collection commands (`build-bag`, `recommend`, `overlap`, `chart`, `maturity`, dashboard) use **inventory**. Never say "bag" where the code means inventory.
- **Scope is the 8 items below.** Do not reopen excluded findings; do not restructure unrelated commands. Concurrent-write locking (Item 9) is out of scope.
- No inventory JSON schema change; no migration.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Full suite must stay green.

---

### Task 1: `restore` returns a disc to the carry bag

**Files:**
- Modify: `discbag/inventory.py` (`set_status`)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Produces: `set_status(name, "active")` now sets `in_bag=True` when the disc was previously archived.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_inventory.py`:

```python
def test_restore_returns_disc_to_carry_bag(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.set_status("mako3", "lost", reason="hole 7")      # archived: in_bag -> False
    assert inv.all_discs()[0].user.in_bag is False
    inv.set_status("mako3", "active")                     # restore
    u = inv.all_discs()[0].user
    assert u.status == "active" and u.in_bag is True
    assert inv.filter(in_bag=True)                        # shows up in the carry bag
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_inventory.py -k restore_returns -v`
Expected: FAIL — `assert False is True` (in_bag stayed False).

- [ ] **Step 3: Implement**

In `discbag/inventory.py`, `set_status`'s `apply` function, replace:

```python
        def apply(u):
            u.status = status
            u.status_reason = reason
            u.status_date = when
            if status != "active":
                u.in_bag = False
            u.log_event(_status_event(when, status, reason))
```

with:

```python
        def apply(u):
            was_active = (u.status or "active") == "active"
            u.status = status
            u.status_reason = reason
            u.status_date = when
            if status != "active":
                u.in_bag = False
            elif not was_active:          # restoring from an archived state → back in the bag
                u.in_bag = True
            u.log_event(_status_event(when, status, reason))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_inventory.py -k "restore_returns or damaged or status" -v`
Expected: PASS (new test passes; existing status/archive tests still pass).

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add discbag/inventory.py tests/test_inventory.py
git commit -m "Fix: restore returns a disc to the carry bag (in_bag)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `bag add/remove` resolves individual copies (+ `--all`)

**Files:**
- Modify: `discbag/cli.py` (`cmd_bag`, `p_bagcmd` parser)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing `_resolve(inv, name, args=args, allow_all=True)`; `inv.set_in_bag(disc, value)` (accepts an `OwnedDisc`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_bag_remove_targets_one_copy(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    target = inv.all_discs()[1]
    # Non-interactive resolve-by-id path: pass the id so it targets one copy.
    cli.cmd_bag(_ns(action="remove", name=["mako3"], id=target.id, all=False), inv)
    assert inv.find_by_id(target.id).user.in_bag is False
    assert inv.all_discs()[0].user.in_bag is True          # the other copy untouched


def test_bag_remove_all_pulls_every_copy(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    cli.cmd_bag(_ns(action="remove", name=["mako3"], id=None, all=True), inv)
    assert all(d.user.in_bag is False for d in inv.all_discs())


def test_bag_remove_ambiguous_non_interactive_errors(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    rc = cli.cmd_bag(_ns(action="remove", name=["mako3"], id=None, all=False), inv)
    assert rc == 1
    assert all(d.user.in_bag is True for d in inv.all_discs())   # nothing changed
```

Note: `_resolve` already supports `--id` targeting via `args.id` and `--all` via `args.all` (it reads `getattr(args, "all", False)`). Passing `id`/`all` on the namespace exercises those paths without a tty.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "test_bag_remove" -v`
Expected: FAIL — current `cmd_bag` ignores `--id`/`--all` and mutates all copies (or `_ns` lacks fields the new code reads).

- [ ] **Step 3: Rewrite `cmd_bag`'s add/remove branch**

In `discbag/cli.py`, replace the non-`list` portion of `cmd_bag` (from `name = " ".join(args.name)` to the end) with the following. Note `_resolve` handles `--all` but not `--id`, so `--id` is handled directly here, exactly as `cmd_edit` does:

```python
    name = " ".join(args.name).strip()
    disc_id = getattr(args, "id", None)
    if disc_id:
        disc = inv.find_by_id(disc_id)
        if disc is None:
            print(f"No disc with id '{disc_id}'.", file=sys.stderr)
            return 1
        targets = [disc]
    else:
        targets = _resolve(inv, name, args=args, allow_all=True)
        if targets is None:
            return 1
    value = args.action == "add"
    for d in targets:
        inv.set_in_bag(d, value)
    label = name or targets[0].name
    verb = "Put" if value else "Pulled"
    where = "in the bag" if value else "out of the bag"
    print(f"{verb} {len(targets)} {label} disc(s) {where}.")
    return 0
```

- [ ] **Step 4: Add `--id` and `--all` to the `bag` parser**

In `discbag/cli.py`, the `p_bagcmd` block, add after the `name` argument:

```python
    p_bagcmd.add_argument("--id", dest="id", help="target one copy by id (see 'list --ids')")
    p_bagcmd.add_argument("--all", action="store_true",
                          help="apply to every copy of the mold")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "test_bag_remove" -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Fix: bag add/remove targets one copy; add --all for bulk

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Carry-bag semantics for `choose` and `practice`

**Files:**
- Modify: `discbag/cli.py` (`cmd_choose`, `cmd_practice`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `inv.filter(in_bag=True)` (active discs currently carried).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def _bag_with(tmp_path, *specs):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    for mold, speed, turn, fade in specs:
        rec = {"name": mold, "brand": "Innova", "category": "x",
               "speed": speed, "glide": 5, "turn": turn, "fade": fade, "stability": ""}
        inv.add(OwnedDisc.from_db_record(rec))
    return inv


def test_choose_uses_carry_bag_not_inventory(tmp_path, capsys):
    inv = _bag_with(tmp_path, ("Destroyer", 12, -1, 3), ("Teebird", 7, 0, 2))
    inv.set_in_bag("destroyer", False)               # pulled from the carry bag
    cli.cmd_choose(_ns(distance=350, wind=None, shape="straight"), inv)
    out = capsys.readouterr().out
    assert "Destroyer" not in out                    # out-of-bag disc not recommended


def test_practice_uses_carry_bag(tmp_path, capsys):
    inv = _bag_with(tmp_path, ("Mako3", 5, 0, 0), ("Firebird", 9, 0, 4))
    inv.set_in_bag("firebird", False)
    cli.cmd_practice(_ns(count=3), inv)
    out = capsys.readouterr().out
    assert "Firebird" not in out


def test_build_bag_still_uses_full_inventory(tmp_path, capsys):
    # Planning reasons over inventory, including out-of-bag discs.
    inv = _bag_with(tmp_path, ("Destroyer", 12, -1, 3))
    inv.set_in_bag("destroyer", False)
    cli.cmd_build_bag(_ns(size=None, situation=None, goal="coverage", rotate=False), inv)
    out = capsys.readouterr().out
    assert "Destroyer" in out                         # still considered for planning


def test_choose_empty_carry_bag_message(tmp_path, capsys):
    inv = _bag_with(tmp_path, ("Mako3", 5, 0, 0))
    inv.set_in_bag("mako3", False)                     # nothing carried
    cli.cmd_choose(_ns(distance=200, wind=None, shape=None), inv)
    out = capsys.readouterr().out
    assert "no discs in your bag" in out.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "carry_bag or practice_uses or empty_carry or still_uses" -v`
Expected: FAIL — `choose`/`practice` currently use `list_discs()`, so the out-of-bag disc is recommended and the empty message differs.

- [ ] **Step 3: Point `choose`/`practice` at the carry bag**

In `discbag/cli.py`, `cmd_choose`: change the `analysis.choose(inv.list_discs(), ...)` call to `analysis.choose(inv.filter(in_bag=True), ...)`, and change the empty message to:

```python
    if not picks:
        print("No discs in your bag. Put discs in with: discbag bag add <name>")
        return 0
```

In `cmd_practice`: change `analysis.practice(inv.list_discs(), ...)` to `analysis.practice(inv.filter(in_bag=True), ...)`, and change its empty message identically:

```python
    if not picks:
        print("No discs in your bag. Put discs in with: discbag bag add <name>")
        return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "carry_bag or practice_uses or empty_carry or still_uses" -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Update the help text**

In `discbag/cli.py`: `p_choose` help `"pick the best disc from your bag for a shot"` → `"pick the best disc from your carry bag for a shot"`; `p_prac` help `"discs to throw for a form-focused practice session"` → `"carry-bag discs to throw for a form-focused practice session"`.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Fix: choose and practice operate on the carry bag, not all inventory

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Reusable numeric/date validation

**Files:**
- Modify: `discbag/cli.py` (add validators; wire onto parsers; extend datetime import)
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `cli._positive_int(s) -> int` (raises `argparse.ArgumentTypeError` on `< 1`); `cli._iso_date(s) -> str` (raises on non-`YYYY-MM-DD`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
import argparse
import pytest


def test_positive_int_validator():
    assert cli._positive_int("3") == 3
    for bad in ("0", "-1", "abc"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._positive_int(bad)


def test_iso_date_validator():
    assert cli._iso_date("2026-07-03") == "2026-07-03"
    for bad in ("not-a-date", "2026-13-40", "07/03/2026"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._iso_date(bad)


def test_parser_rejects_bad_date_and_count():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["round-used", "mako3", "--date", "not-a-date"])
    with pytest.raises(SystemExit):
        parser.parse_args(["practice", "--count", "-1"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "validator or rejects_bad" -v`
Expected: FAIL — `AttributeError: module 'discbag.cli' has no attribute '_positive_int'`.

- [ ] **Step 3: Add the validators**

In `discbag/cli.py`, change the datetime import (line 5) to include `date`:

```python
from datetime import date, datetime, timezone
```

Add these functions near the top (after the imports, before the first command):

```python
def _positive_int(s):
    """argparse type: a positive integer (>= 1)."""
    try:
        value = int(s)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be a positive integer")
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _iso_date(s):
    """argparse type: a date in YYYY-MM-DD form (returns the original string)."""
    try:
        date.fromisoformat(s)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be a date in YYYY-MM-DD form")
    return s
```

- [ ] **Step 4: Wire the validators onto the parsers**

In `discbag/cli.py`:
- `p_prac` `--count`: `type=int` → `type=_positive_int`.
- `p_bag` (build-bag) `--size`/`-n`: `type=int` → `type=_positive_int`.
- `p_rec` `--per-slot`: `type=int` → `type=_positive_int`.
- The used-family `--date` (`p_used.add_argument("--date", ...)`): add `type=_iso_date`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "validator or rejects_bad" -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Add reusable positive-int and ISO-date argparse validators

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Remove the `score --situation` no-op

**Files:**
- Modify: `discbag/recommend.py` (`score_disc`), `discbag/cli.py` (`cmd_score` call site, `p_score` parser)
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `recommend.score_disc(disc, role, goal="coverage", profile=None, today=None)` (no `situation`); score output has no "Scenario adjustment" component.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_score_has_no_scenario_component(tmp_path, capsys):
    from discbag import recommend, roles
    from discbag.inventory import Disc
    disc = Disc(name="Buzzz", brand="Discraft", category="Midrange",
                speed=5, glide=4, turn=-1, fade=1)
    role = roles.primary_role(disc)
    scored = recommend.score_disc(disc, role)
    assert not any("Scenario" in c.label for c in scored.components)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k scenario_component -v`
Expected: FAIL — the always-present `ScoreComponent("Scenario adjustment", 0)` is in `components`.

- [ ] **Step 3: Remove `situation` from `score_disc`**

In `discbag/recommend.py`, change the signature and drop the scenario component:

```python
def score_disc(disc, role, goal="coverage", profile=None, today=None):
    """Explainable score of a disc for a role under a goal: components + total."""
    fit = roles.fit_score(disc, role)
    components = [ScoreComponent("Role fit", round(100 - fit * _POINT_SCALE))]
    for label, value in _goal_components(goal, disc, profile, today):
        components.append(ScoreComponent(label, round(-value * _POINT_SCALE)))
    total = sum(c.points for c in components)
    internal = fit + _goal_penalty(goal, disc, profile, today)
    return DiscScore(disc=disc, role=role, components=components, total=total, internal=internal)
```

- [ ] **Step 4: Update the `cmd_score` call and remove `--situation` from `score`**

In `discbag/cli.py`, `cmd_score`: change the call `recommend.score_disc(disc, role, args.goal, profile, today, args.situation)` to `recommend.score_disc(disc, role, args.goal, profile, today)`.

In the `p_score` parser block, delete the line `p_score.add_argument("--situation", choices=_SITUATIONS)` and change `p_score.set_defaults(func=cmd_score, situation=None)` to `p_score.set_defaults(func=cmd_score)`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k scenario_component -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (no test used `score --situation`).

- [ ] **Step 7: Commit**

```bash
git add discbag/recommend.py discbag/cli.py tests/test_cli.py
git commit -m "Remove no-op score --situation and its always-zero component

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `build-bag --size` separates gaps from size omissions

**Files:**
- Modify: `discbag/recommend.py` (`BagResult`, `build_bag`), `discbag/cli.py` (`cmd_build_bag` output)
- Test: `tests/test_recommend.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `BagResult` gains `omitted: list` (roles trimmed by `--size` that had a qualifying disc); `gaps` stays genuine-unfilled roles.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_recommend.py`:

```python
def test_build_bag_size_separates_omitted_from_gaps():
    bag = [MAKO3, WIZARD, LEOPARD, FIREBIRD, DESTROYER]
    genuine = {r.name for r in recommend.build_bag(bag).gaps}   # no-size genuine gaps
    result = recommend.build_bag(bag, size=1)
    assert len(result.filled) == 1
    omitted = {r.name for r in result.omitted}
    assert omitted                                              # some roles were trimmed
    assert omitted.isdisjoint(genuine)                         # trimmed != genuine gaps
    assert {r.name for r in result.gaps} == genuine            # gaps unchanged by size


def test_build_bag_no_size_has_empty_omitted():
    result = recommend.build_bag([MAKO3, WIZARD])
    assert result.omitted == []
```

Add to `tests/test_cli.py`:

```python
def test_cmd_build_bag_labels_size_omissions_separately(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    for mold, sp, tu, fa in [("Mako3", 5, 0, 0), ("Wizard", 2, 0, 2),
                             ("Leopard", 6, -2, 1), ("Firebird", 9, 0, 4)]:
        inv.add(OwnedDisc.from_db_record(
            {"name": mold, "brand": "Innova", "category": "x",
             "speed": sp, "glide": 5, "turn": tu, "fade": fa, "stability": ""}))
    cli.cmd_build_bag(_ns(size=1, situation=None, goal="coverage", rotate=False), inv)
    out = capsys.readouterr().out
    assert "Left out to fit" in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_recommend.py tests/test_cli.py -k "omitted or size_omissions or empty_omitted" -v`
Expected: FAIL — `BagResult` has no `omitted`; CLI prints no "Left out" section.

- [ ] **Step 3: Add `omitted` to `BagResult` and compute it in `build_bag`**

In `discbag/recommend.py`, change the import (line 21) to `from dataclasses import dataclass, field`, and update `BagResult`:

```python
@dataclass
class BagResult:
    filled: list             # RoleFill, in role-priority order
    gaps: list               # roles.Role with no qualifying disc
    omitted: list = field(default_factory=list)   # roles trimmed only to honor --size
```

In `build_bag`, replace the `if size is not None:` block and the return with:

```python
    omitted = []
    if size is not None:
        kept = sorted(fills, key=lambda f: f.score)[:size]
        kept_ids = {id(f) for f in kept}
        omitted = [f.role for f in fills if id(f) not in kept_ids]
        fills = sorted(kept, key=lambda f: f.role.priority)

    return BagResult(filled=fills, gaps=gaps, omitted=omitted)
```

(Note: `gaps` is no longer reassigned after the size trim — it stays the genuine-unfilled set computed in the loop.)

- [ ] **Step 4: Print the omitted section in `cmd_build_bag`**

In `discbag/cli.py`, `cmd_build_bag`, after the existing `if result.gaps:` block, add:

```python
    if result.omitted:
        print("\nLeft out to fit the size limit:")
        for role in result.omitted:
            print(f"  {role.name:<22} {role.use}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_recommend.py tests/test_cli.py -k "omitted or size_omissions or empty_omitted or size_limits" -v`
Expected: PASS (incl. the existing `test_build_bag_size_limits_fills`).

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add discbag/recommend.py discbag/cli.py tests/test_recommend.py tests/test_cli.py
git commit -m "Fix: build-bag --size distinguishes real gaps from size omissions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `history` shows current damaged state

**Files:**
- Modify: `discbag/cli.py` (`cmd_history` summary)
- Test: `tests/test_cli.py`

**Interfaces:** none new.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def test_history_shows_current_damaged_state(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.set_damaged("mako3", True, reason="cracked", when="2026-07-01T00:00:00+00:00")
    cli.cmd_history(_ns(name=["mako3"]), inv)
    out = capsys.readouterr().out
    assert "Damaged: yes" in out


def test_history_no_damaged_line_when_undamaged(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    cli.cmd_history(_ns(name=["mako3"]), inv)
    assert "Damaged" not in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "history_shows_current_damaged or no_damaged_line" -v`
Expected: FAIL — no "Damaged" line in the summary.

- [ ] **Step 3: Add the Damaged line to the summary**

In `discbag/cli.py`, `cmd_history`, after the `print(f"  Status: {(u.status or 'active').capitalize()}")` line, add:

```python
    if u.damaged:
        print("  Damaged: yes")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_cli.py -k "history_shows_current_damaged or no_damaged_line" -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Fix: history summary shows current damaged state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: Documentation

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: Update the README**

In `README.md`:
- **Organization / `restore`:** state it returns the disc to your **carry bag**.
- **`bag`:** note that `bag add`/`bag remove` act on one copy (prompting when ambiguous) and that `--all` applies to every copy of the mold.
- **Analysis:** make explicit that **`choose` and `practice` use your carry bag**, while **`build-bag`, `recommend`, `overlap`, `chart`, and `maturity` use your full active inventory**. A good spot is a one-line note under the Analysis block: `Live-shot commands (choose, practice) read your carry bag; planning commands read your whole inventory.`
- **`score`:** remove any `--situation` from the `score` synopsis/prose (it's gone from `score`; it remains on `build-bag`).
- Scan the command reference for generic "bag" that means inventory and correct it per the terminology table.

- [ ] **Step 2: Update the CHANGELOG**

In `CHANGELOG.md`, add a "Fixed" section (or entries under the top section):

```markdown
### Fixed
- `restore` now returns a disc to your carry bag, not just active inventory.
- `bag add`/`bag remove` act on a single copy (with `--all` for every copy of a mold),
  matching the rest of the CLI.
- `choose` and `practice` now read your carry bag; planning commands still use your
  full inventory.
- Rejected invalid `--date` values and non-positive `--count`/`--size`/`--per-slot`.
- `build-bag --size` distinguishes genuine coverage gaps from roles left out to fit the size.
- `history` shows a disc's current damaged state.
- Removed the no-op `score --situation` and its always-zero "Scenario adjustment" line.
```

- [ ] **Step 3: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: PASS (docs-only).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Docs: match audit-fix behavior (bag/inventory terms, restore, score, validation)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Item 1 restore→bag → Task 1. ✓
- Item 2 bag per-copy + `--all` → Task 2. ✓
- Item 3 carry-bag semantics (choose/practice) + inventory unchanged for planning → Task 3. ✓
- Item 4 validation (positive-int, ISO-date) → Task 4. ✓
- Item 5 remove score `--situation` + zero component → Task 5. ✓
- Item 6 build-bag gaps vs omitted → Task 6. ✓
- Item 7 history damaged state → Task 7. ✓
- Item 8 docs → Task 8. ✓
- Item 9 concurrency → out of scope (not a task). ✓

**Placeholder scan:** No TBD/TODO; every code step has complete code.

**Type consistency:** `_positive_int`/`_iso_date` defined in Task 4 and referenced in the same task's parser wiring; `BagResult.omitted` defined in Task 6 and rendered in the same task's CLI step; `score_disc` new signature (Task 5) matches its updated call site; `set_status` change (Task 1) matches its existing callers (only `restore` passes `"active"`); `_resolve`, `inv.set_in_bag`, `inv.filter`, `inv.find_by_id`, `build_parser`, `roles.primary_role`, `recommend.ScoreComponent`/`DiscScore` all exist in the current codebase.
