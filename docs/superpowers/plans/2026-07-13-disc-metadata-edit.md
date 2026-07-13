# Disc Metadata Editing (`discbag edit`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `discbag edit` command that corrects a physical disc's inventory metadata in place without touching its career or history.

**Architecture:** A new `Inventory.update_metadata()` owns all metadata mutation: it overwrites only the fields passed, logs no history event, and — when the manufacturer/mold identity changes — internally re-resolves the identity through the same `db.find_disc` resolver `add` uses and refreshes the cached flight snapshot. A thin `cmd_edit` CLI wrapper resolves the target disc (interactive prompt by default, `--id` for scripting) and calls it. A small `list --ids` flag surfaces ids for `--id` discovery.

**Tech Stack:** Python 3.14, argparse CLI, dataclasses, JSON-file persistence, pytest.

## Global Constraints

- **No history events on edit.** `update_metadata()` must never call `log_event`. Editing metadata is not part of a disc's career. This is the load-bearing guarantee.
- **Metadata correction only.** Editable fields: manufacturer (`brand`), mold, plastic, weight, color, condition, notes. `role`/`favorite`/`tag`/`flight`/lifecycle keep their own commands and are out of scope.
- **`--location` is intentionally omitted** in this iteration.
- **One place populates cached flight data.** The identity refresh reuses `db.find_disc` (the resolver `add` uses) — no duplicated lookup logic.
- **Reuse `_disc_descriptor`** for ambiguity prompts; do not introduce a second formatter.
- **ids stay hidden** except via explicit `list --ids`.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Run the full suite with `pytest -q` before each commit; it must stay green.

---

### Task 1: `Inventory.update_metadata()`

**Files:**
- Modify: `discbag/inventory.py` (add method to the `Inventory` class, after the `replace` method)
- Test: `tests/test_inventory.py`

**Interfaces:**
- Consumes: `db.find_disc(query, discs) -> (best_record_or_None, alts)` from `discbag/db.py`; `Disc.from_db_record(record)`.
- Produces: `Inventory.update_metadata(disc, *, brand=None, mold=None, plastic=None, weight=None, color=None, condition=None, notes=None, db_discs=None) -> (identity_changed: bool, matched_record_or_None: dict|None)`. `None` for any field means "leave unchanged". Logs no event. Saves once.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_inventory.py`:

```python
# ---------- update_metadata: metadata correction, no career event ----------

ROADRUNNER = {"name": "Roadrunner", "brand": "Innova", "category": "Fairway",
              "speed": 9, "glide": 5, "turn": -4, "fade": 1,
              "stability": "Understable"}


def test_update_metadata_sets_fields_without_logging_event(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    disc = inv.all_discs()[0]
    before = len(disc.user.events or [])
    inv.update_metadata(disc, plastic="Champion", weight=171, color="Orange",
                        condition="New", notes="clear champ")
    u = inv.all_discs()[0].user
    assert u.plastic == "Champion" and u.weight == 171
    assert u.color == "Orange" and u.condition == "New" and u.notes == "clear champ"
    # The core guarantee: metadata edits are not career/history events.
    assert len(u.events or []) == before


def test_update_metadata_preserves_history_and_flags(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.record_use("mako3", "2026-07-03T00:00:00+00:00")
    inv.set_favorite("mako3", True)
    inv.add_tag("mako3", "workhorse")
    disc = inv.all_discs()[0]
    inv.update_metadata(disc, color="Blue")
    u = inv.all_discs()[0].user
    assert u.color == "Blue"
    assert u.use_count == 1
    assert u.favorite is True
    assert "workhorse" in u.tags


def test_update_metadata_none_leaves_fields_unchanged(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3, plastic="Star", color="orange"))
    disc = inv.all_discs()[0]
    inv.update_metadata(disc, weight=175)          # only weight provided
    u = inv.all_discs()[0].user
    assert u.weight == 175
    assert u.plastic == "Star"                     # untouched
    assert u.color == "orange"                     # untouched


def test_update_metadata_identity_change_refreshes_cached(tmp_path):
    inv = make_inv(tmp_path)
    # Added under a typo'd mold with placeholder flight numbers.
    typo = {"name": "Roadruner", "brand": "Innova", "category": "Fairway",
            "speed": 0, "glide": 0, "turn": 0, "fade": 0, "stability": ""}
    inv.add(OwnedDisc.from_db_record(typo))
    disc = inv.all_discs()[0]
    identity_changed, matched = inv.update_metadata(
        disc, mold="Roadrunner", db_discs=[ROADRUNNER])
    assert identity_changed is True
    assert matched is not None
    d = inv.all_discs()[0]
    assert d.mold == "Roadrunner"
    assert (d.speed, d.glide, d.turn, d.fade) == (9, 5, -4, 1)


def test_update_metadata_identity_change_no_match_keeps_cached(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    disc = inv.all_discs()[0]
    before = (disc.speed, disc.glide, disc.turn, disc.fade)
    identity_changed, matched = inv.update_metadata(
        disc, mold="Nonexistent Mold", db_discs=[])
    assert identity_changed is True
    assert matched is None
    d = inv.all_discs()[0]
    assert d.mold == "Nonexistent Mold"            # string still applied
    assert (d.speed, d.glide, d.turn, d.fade) == before   # cached untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_inventory.py -k update_metadata -v`
Expected: FAIL — `AttributeError: 'Inventory' object has no attribute 'update_metadata'`

- [ ] **Step 3: Implement `update_metadata`**

In `discbag/inventory.py`, add this method to the `Inventory` class, immediately after the `replace` method:

```python
    def update_metadata(self, disc, *, brand=None, mold=None, plastic=None,
                        weight=None, color=None, condition=None, notes=None,
                        db_discs=None):
        """Correct one physical disc's inventory metadata in place (the `edit`
        command). Overwrites only the fields passed — ``None`` means leave
        unchanged. Never logs a history event: metadata correction is not part
        of a disc's career, so history, usage, favorite, tags, lifecycle status,
        and the event log are all left intact.

        ``brand`` (manufacturer) and ``mold`` are the disc's identity; the cached
        flight snapshot is derived from them. If either changes, the cached
        snapshot is refreshed here via the same resolver ``add`` uses
        (``db.find_disc``) so callers never have to remember to. Returns
        ``(identity_changed, matched_record_or_None)`` so the CLI can report the
        lookup outcome. On no DB match the identity strings are still applied and
        the cached snapshot is left untouched.
        """
        from discbag import db

        identity_changed = False
        if brand is not None and brand != disc.brand:
            disc.brand = brand
            identity_changed = True
        if mold is not None and mold != disc.mold:
            disc.mold = mold
            identity_changed = True

        u = disc.user
        if plastic is not None:
            u.plastic = plastic
        if weight is not None:
            u.weight = weight
        if color is not None:
            u.color = color
        if condition is not None:
            u.condition = condition
        if notes is not None:
            u.notes = notes

        matched = None
        if identity_changed and db_discs is not None:
            best, _ = db.find_disc(f"{disc.brand} {disc.mold}", db_discs)
            if best is not None:
                disc.cached = Disc.from_db_record(best)
                matched = best

        self._save()
        return identity_changed, matched
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_inventory.py -k update_metadata -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full inventory suite**

Run: `pytest tests/test_inventory.py -q`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add discbag/inventory.py tests/test_inventory.py
git commit -m "Add Inventory.update_metadata for in-place metadata correction

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `discbag edit` command

**Files:**
- Modify: `discbag/cli.py` (add `cmd_edit`; register the `edit` subparser; add to `_HELP_GROUPS`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Inventory.update_metadata(...)` (Task 1); existing `_resolve(inv, name, include_archived=True) -> [OwnedDisc]|None`; `inv.find_by_id(id) -> OwnedDisc|None`; `db.load_db() -> {"discs": [...]}`.
- Produces: `cmd_edit(args, inv) -> int`. Argparse `Namespace` fields it reads: `name` (list), `id`, `manufacturer`, `mold`, `plastic`, `weight`, `color`, `condition`, `notes`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
def _two_makos(tmp_path):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    return inv


def _edit_ns(**over):
    base = dict(name=[], id=None, manufacturer=None, mold=None, plastic=None,
                weight=None, color=None, condition=None, notes=None)
    base.update(over)
    return _ns(**base)


def test_cmd_edit_updates_metadata_in_place(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": []})
    inv = _inv_with_mako(tmp_path)
    cli.cmd_edit(_edit_ns(name=["mako3"], plastic="Champion", weight=171,
                          color="Orange"), inv)
    u = inv.all_discs()[0].user
    assert u.plastic == "Champion" and u.weight == 171 and u.color == "Orange"
    assert "Updated" in capsys.readouterr().out


def test_cmd_edit_requires_a_field(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    rc = cli.cmd_edit(_edit_ns(name=["mako3"]), inv)
    assert rc == 1
    assert "at least one field" in capsys.readouterr().err.lower()
    assert inv.all_discs()[0].user.plastic == ""       # nothing changed


def test_cmd_edit_ambiguous_name_errors_without_guessing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": []})
    inv = _two_makos(tmp_path)
    rc = cli.cmd_edit(_edit_ns(name=["mako3"], plastic="Star"), inv)
    assert rc == 1
    combined = capsys.readouterr()
    assert "match" in (combined.out + combined.err).lower()
    assert all(d.user.plastic == "" for d in inv.all_discs())   # neither modified


def test_cmd_edit_by_id_targets_one_copy(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": []})
    inv = _two_makos(tmp_path)
    target = inv.all_discs()[1]
    cli.cmd_edit(_edit_ns(id=target.id, plastic="Star"), inv)
    assert inv.find_by_id(target.id).user.plastic == "Star"
    assert inv.all_discs()[0].user.plastic == ""       # the other copy untouched
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -k cmd_edit -v`
Expected: FAIL — `AttributeError: module 'discbag.cli' has no attribute 'cmd_edit'`

- [ ] **Step 3: Implement `cmd_edit`**

In `discbag/cli.py`, add this function next to the other command functions (e.g. immediately after `cmd_replace`):

```python
def cmd_edit(args, inv):
    """Correct a disc's inventory metadata in place (plastic, color, weight,
    condition, notes, or the manufacturer/mold identity). Metadata correction
    only: it changes nothing about the disc's career and logs no history event.
    Changing the manufacturer/mold refreshes the cached flight numbers from the
    database. A unique name is edited directly; an ambiguous name prompts (or is
    a hard error non-interactively); `--id` targets one copy for scripting."""
    edits = {
        "brand": args.manufacturer,
        "mold": args.mold,
        "plastic": args.plastic,
        "weight": args.weight,
        "color": args.color,
        "condition": args.condition,
        "notes": args.notes,
    }
    if all(v is None for v in edits.values()):
        print("Nothing to edit — pass at least one field, e.g. --plastic Champion.",
              file=sys.stderr)
        return 1

    disc_id = getattr(args, "id", None)
    if disc_id:
        disc = inv.find_by_id(disc_id)
        if disc is None:
            print(f"No disc with id '{disc_id}'.", file=sys.stderr)
            return 1
    else:
        name = " ".join(args.name).strip() if args.name else ""
        if not name:
            print("Name a disc to edit, or pass --id.", file=sys.stderr)
            return 1
        targets = _resolve(inv, name, include_archived=True)
        if targets is None:
            return 1
        disc = targets[0]

    db_discs = db.load_db().get("discs", [])
    identity_changed, matched = inv.update_metadata(disc, db_discs=db_discs, **edits)

    print(f"Updated {disc.brand} {disc.name}.")
    if identity_changed:
        if matched is not None:
            print(f"  Matched: {matched['brand']} {matched['name']} "
                  f"({matched['speed']}/{matched['glide']}/"
                  f"{matched['turn']}/{matched['fade']})")
        else:
            print("  Warning: no database match for the new identity; flight "
                  "numbers left unchanged. Run 'discbag updatedb' or check the "
                  "spelling.", file=sys.stderr)
    return 0
```

- [ ] **Step 4: Register the subparser**

In `discbag/cli.py`, in the parser-building section (near the `p_restore`/`p_lost`/`p_replace` registrations), add:

```python
    p_edit = sub.add_parser("edit",
                            help="correct a disc's inventory metadata (no history event)")
    p_edit.add_argument("name", nargs="*", help="disc name (omit if using --id)")
    p_edit.add_argument("--id", dest="id",
                        help="target one copy by id (discover ids with 'list --ids')")
    p_edit.add_argument("--manufacturer", help="correct the manufacturer/brand")
    p_edit.add_argument("--mold", help="correct the mold name")
    p_edit.add_argument("--plastic")
    p_edit.add_argument("--weight", type=int)
    p_edit.add_argument("--color")
    p_edit.add_argument("--condition", help="e.g. New, Used, Beat-in")
    p_edit.add_argument("--notes")
    p_edit.set_defaults(func=cmd_edit)
```

- [ ] **Step 5: Add to the help groups**

In `discbag/cli.py`, in the `_HELP_GROUPS` `"Organization"` group, add an `edit` entry after the `role` line:

```python
        ("role", "set a personal role label"),
        ("edit", "correct a disc's metadata (no history event)"),
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -k cmd_edit -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Verify end-to-end against a throwaway bag**

Run:
```bash
HOME=$(mktemp -d) bash -c '
  python -c "from discbag.cli import main; import sys;
sys.argv=[\"discbag\",\"add\",\"Innova Roadrunner\",\"--yes\"]; main()"
  python -c "from discbag.cli import main; import sys;
sys.argv=[\"discbag\",\"edit\",\"roadrunner\",\"--plastic\",\"Champion\",\"--color\",\"Clear\"]; main()"
  python -c "from discbag.cli import main; import sys;
sys.argv=[\"discbag\",\"show\",\"roadrunner\"]; main()"
'
```
Expected: the `edit` prints `Updated Innova Roadrunner.` and `show` reflects plastic `Champion`, color `Clear`.

- [ ] **Step 8: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Add discbag edit command for metadata correction

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `discbag list --ids`

**Files:**
- Modify: `discbag/cli.py` (`cmd_list` + the `p_list` subparser)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: existing `cmd_list(args, inv)`; `OwnedDisc.id`.
- Produces: `list --ids` prints each disc's id on its own indented line beneath the disc's row. Default output is unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_cmd_list_ids_shows_ids(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    the_id = inv.all_discs()[0].id
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None,
                     all=False, ids=True), inv)
    assert the_id in capsys.readouterr().out


def test_cmd_list_hides_ids_by_default(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    the_id = inv.all_discs()[0].id
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None,
                     all=False, ids=False), inv)
    assert the_id not in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -k list_ids -v`
Expected: `test_cmd_list_ids_shows_ids` FAILs (id not printed); `test_cmd_list_hides_ids_by_default` passes.

- [ ] **Step 3: Print ids when requested**

In `discbag/cli.py`, in `cmd_list`, change the final render loop from:

```python
    for d in discs:
        _print_disc_row(d)
    return 0
```

to:

```python
    show_ids = getattr(args, "ids", False)
    for d in discs:
        _print_disc_row(d)
        if show_ids:
            print(f"      id: {d.id}")
    return 0
```

- [ ] **Step 4: Add the `--ids` flag**

In `discbag/cli.py`, in the `p_list` block, add after the `--all` argument:

```python
    p_list.add_argument("--ids", action="store_true",
                        help="show each disc's internal id (for 'edit --id')")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_cli.py -k list_ids -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add discbag/cli.py tests/test_cli.py
git commit -m "Add list --ids to surface disc ids for edit --id

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the README**

In `README.md`, in the command reference (near the `remove`/`replace`/`restore` commands), add an `edit` entry. Match the surrounding formatting; use this content:

```markdown
### `edit` — correct a disc's metadata

Fix or fill in a disc's physical details after adding it. This is metadata
correction only — it changes nothing about the disc's career and adds no history
event.

    discbag edit roadrunner --plastic Champion --color Clear
    discbag edit roadrunner --plastic Star --color Orange --weight 171

Editable fields: `--manufacturer`, `--mold`, `--plastic`, `--weight`, `--color`,
`--condition`, `--notes`. Changing the manufacturer or mold re-derives the disc's
cached flight numbers from the database.

When a name matches more than one copy (e.g. two Roadrunners), `edit` lists them
and asks you to choose. For scripting, target a copy directly by id:

    discbag list --ids
    discbag edit --id 1a2b3c4d --color Clear
```

- [ ] **Step 2: Update the CHANGELOG**

In `CHANGELOG.md`, under the current unreleased/top section, add:

```markdown
- `discbag edit` corrects a disc's inventory metadata (plastic, weight, color,
  condition, notes, manufacturer, mold) in place, without creating a history
  event. Changing the manufacturer/mold refreshes cached flight numbers from the
  database.
- `discbag list --ids` prints disc ids, for targeting a specific copy with
  `discbag edit --id`.
```

- [ ] **Step 3: Run the full suite once more**

Run: `pytest -q`
Expected: PASS (all green, including the new tests).

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "Document the edit command and list --ids

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Purpose / metadata-correction-only → Tasks 1–2, Global Constraints. ✓
- No history events (hard guarantee) → Task 1 Step 1 `test_update_metadata_sets_fields_without_logging_event`. ✓
- Command shape / flags mirror add / `--id` → Task 2 parser + tests. ✓
- At least one field required → Task 2 `test_cmd_edit_requires_a_field`. ✓
- `--location` omitted → not added anywhere; noted in Global Constraints. ✓
- Editable fields (metadata + identity) → Task 1 method + Task 2 flags. ✓
- Cached flight follows identity, reuse `db.find_disc`, inventory owns refresh → Task 1 method + refresh tests. ✓
- Interactive-by-default disambiguation, error non-interactively, include archived → Task 2 uses `_resolve(..., include_archived=True)`; `test_cmd_edit_ambiguous_name_errors_without_guessing`. ✓
- `--id` power-user path → Task 2 `test_cmd_edit_by_id_targets_one_copy`. ✓
- Reuse `_disc_descriptor` (no new formatter) → `_resolve`/`_print_matches` already use it; no new formatter introduced. ✓
- `list --ids` discovery surface → Task 3. ✓
- `update_metadata` API shape → Task 1 Interfaces. ✓
- `edit --interactive` explicitly out of scope → not implemented. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete code. ✓

**Type consistency:** `update_metadata` signature and its `(identity_changed, matched)` return are identical in Task 1's definition and Task 2's call site; `edits` dict keys (`brand`, `mold`, `plastic`, `weight`, `color`, `condition`, `notes`) match the method's keyword parameters; `find_by_id`, `_resolve`, `db.load_db`, `_disc_descriptor` all exist in the codebase as referenced. ✓
