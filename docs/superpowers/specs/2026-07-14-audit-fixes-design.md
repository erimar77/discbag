# Audit-fix correctness pass — design

**Date:** 2026-07-14
**Status:** Approved, pre-implementation

## Purpose

A targeted correctness and consistency pass addressing the verified findings from the project
audit. Scope is exactly the prioritized action list — no unrelated redesign, no broad cleanup,
and no reopening of the excluded findings (compare/score first-duplicate resolution, timeline
not seeding damaged events, the inaccurate test-count claim, forward-compat field drop) unless
implementation surfaces new evidence.

## Terminology (enforced throughout code, help, and docs)

- **Bag** = the discs you currently **carry** (`in_bag=True`, active).
- **Inventory** = all **active owned** discs (`inv.list_discs()`), carried or not.

Immediate-use commands operate on the **bag**; planning / collection-analysis commands operate on
**inventory**. "Bag" must not be used generically where the implementation means inventory.

| Operates on the **bag** (carried) | Operates on **inventory** (active owned) |
|-----------------------------------|------------------------------------------|
| `choose`, `practice`             | `build-bag`, `recommend`, `overlap`, `chart`, `maturity`, home-screen dashboard |

The home-screen dashboard is a collection-level glance and stays on inventory (its lightweight
"Practice" line included) — only the `choose` and `practice` **commands** move to the bag.

---

## Item 1 — `restore` returns a disc to the carry bag

- **Current:** `Inventory.set_status(name, "active")` (discbag/inventory.py) only ever *clears*
  `in_bag` (`if status != "active": u.in_bag = False`). Restoring an archived disc sets
  `status="active"` but leaves `in_bag=False`, so it never reappears in `discbag bag list`.
- **Intended:** restoring an **archived** disc returns it to the carry bag (`in_bag=True`). An
  already-active disc's `in_bag` is left untouched (so this never fights `bag remove`).
- **Affected:** `discbag/inventory.py` `set_status`; command `restore` (`cmd_restore`), no CLI
  change needed there.
- **Change:** in `set_status`'s `apply`, capture `was_active = (u.status or "active") == "active"`
  before reassigning, then:
  - `if status != "active": u.in_bag = False`
  - `elif not was_active: u.in_bag = True`  (restore from archived → back into the bag)
- **Compatibility:** `set_status("active")` is only reached via `restore`. The `elif not
  was_active` guard means re-activating an already-active disc (not user-reachable today) won't
  force it into the bag. No data migration.
- **Tests (tests/test_inventory.py):**
  - `restore` on a lost disc → `status == "active"` **and** `in_bag is True`, and it appears in
    `inv.filter(in_bag=True)`.
  - Archiving still sets `in_bag=False` (existing behavior unbroken).
- **Wording:** `p_restore` help "return an archived disc to the active bag" → "restore an archived
  disc to your carry bag".

## Item 2 — `bag add/remove` resolves individual copies (+ `--all`)

- **Current:** `cmd_bag` (discbag/cli.py) passes the mold-name string to
  `inv.set_in_bag(name, value)`, which mutates **every** copy of the mold. `bag remove mako3`
  with two Mako3 pulls both.
- **Intended:** `bag add`/`bag remove` disambiguate a single physical copy like the other
  single-disc commands (interactive prompt when ambiguous; hard error non-interactively). A new
  `--all` flag applies to every copy of the mold for intentional bulk changes.
- **Affected:** `discbag/cli.py` `cmd_bag` and the `p_bagcmd` parser. `Inventory.set_in_bag`
  already accepts either an `OwnedDisc` or a name (via `_mutate`/`_targets`), so no inventory
  change.
- **Change:** in `cmd_bag`, for `add`/`remove`, resolve targets with
  `_resolve(inv, name, args=args, allow_all=True)`; on `None`, return 1. Then
  `for d in targets: inv.set_in_bag(d, value)`. Add `p_bagcmd.add_argument("--all", ...)`.
- **Compatibility:** users with duplicate copies who relied on the old bulk behavior now get a
  prompt (or must pass `--all`). This matches `tag`/`untag`/`favorite`. Single-copy usage is
  unchanged.
- **Tests (tests/test_cli.py):**
  - Two Mako3 in bag; `bag remove` targeting one copy (by resolved disc) pulls exactly that copy;
    the other stays `in_bag=True`.
  - `bag remove mako3 --all` pulls both copies.
  - Ambiguous `bag remove mako3` non-interactively (no tty) → returns 1, neither copy changed.
  - `bag add`/`remove` on a uniquely-named disc still works with no prompt.
- **Wording:** `p_bagcmd` help unchanged ("manage which owned discs are currently carried"); add
  `--all` help "apply to every copy of the mold". Output line keeps reporting the count acted on.

## Item 3 — Carry-bag semantics applied consistently

- **Current:** `cmd_choose` and `cmd_practice` call `analysis.choose`/`analysis.practice` with
  `inv.list_discs()` (all active inventory), so a disc pulled from the bag is still recommended.
  `choose` help says "pick the best disc from your bag".
- **Intended:** `choose` and `practice` operate on the **carry bag** (`inv.filter(in_bag=True)`).
  All planning/collection commands (`build-bag`, `recommend`, `overlap`, `chart`, `maturity`,
  dashboard) continue to use inventory — no behavior change to those, only wording/docs.
- **Affected:** `discbag/cli.py` `cmd_choose`, `cmd_practice`; help text on `p_choose`,
  `p_prac`. No `analysis` change (they take the disc list as a parameter).
- **Change:** replace `inv.list_discs()` with `inv.filter(in_bag=True)` in `cmd_choose` and
  `cmd_practice`. Update the empty-result message to distinguish an empty carry bag: "No discs in
  your bag. Put discs in with: discbag bag add <name>".
- **Compatibility:** a user who has never used `bag add/remove` keeps every active disc `in_bag`
  by default (that's the `UserData` default), so `choose`/`practice` behave as before for them.
  Only users who curated their carry bag see the (intended) narrowing.
- **Tests (tests/test_cli.py):**
  - `choose` with one disc `in_bag=False` does **not** recommend it; a `build-bag`/`recommend`
    over the same inventory **does** still consider it (planning uses inventory).
  - `practice` excludes an out-of-bag disc.
  - `choose`/`practice` on an empty carry bag (all pulled) prints the "No discs in your bag"
    message and returns 0.
- **Wording:** `p_choose` help "pick the best disc from your bag for a shot" (clarify it's the
  carry bag in the README/prose); `p_prac` help "discs from your bag to throw for a form-focused
  practice session".

## Item 4 — Reusable numeric/date validation

- **Current:** `--count` (`practice`), `--size`/`-n` (`build-bag`), `--per-slot` (`recommend`) are
  bare `type=int` with no floor — `practice --count -1` becomes `sorted(...)[:-1]` (all but the
  last disc). `--date` (the `round-used`/`practice-used`/`used` family) is stored raw with no ISO
  check, so `--date not-a-date` persists garbage into the event log.
- **Intended:** positive integers only for the counts; ISO `YYYY-MM-DD` for `--date`. Invalid
  input is rejected by argparse *before* any command runs, so nothing is persisted.
- **Affected:** `discbag/cli.py` — two new module-level validators and the parser definitions for
  `p_prac` (`--count`), `p_bag` (`--size`/`-n`), `p_rec` (`--per-slot`), and the `--date`
  argument on the used-command family.
- **Change:** add:
  - `_positive_int(s)` → `int(s)` if ≥ 1, else `raise argparse.ArgumentTypeError("must be a positive integer")`.
  - `_iso_date(s)` → returns `s` if `date.fromisoformat(s)` parses, else
    `raise argparse.ArgumentTypeError("must be a date in YYYY-MM-DD form")`.
  Wire `type=_positive_int` onto `--count`/`--size`/`--per-slot`, and `type=_iso_date` onto `--date`.
- **Compatibility:** argparse `type=` runs only on strings the user passes, not on defaults
  (`count`/`per-slot` default to `3` as ints), so defaults are unaffected. Future dates are **not**
  rejected (only format is validated) — backdating is a legitimate use and same-day/timezone edges
  shouldn't error; deferred unless requested.
- **Tests (tests/test_cli.py):**
  - `_positive_int("3") == 3`; `_positive_int("-1")` and `_positive_int("0")` raise
    `argparse.ArgumentTypeError`.
  - `_iso_date("2026-07-03") == "2026-07-03"`; `_iso_date("not-a-date")` and `_iso_date("2026-13-40")`
    raise.
  - Integration: `cli.main(["round-used", "mako3", "--date", "not-a-date"])` exits non-zero and
    the inventory records no use (nothing persisted).
- **Wording:** no visible help changes; argparse emits the standard `error:` message.

## Item 5 — Remove the `score --situation` no-op

- **Current:** `recommend.score_disc(..., situation=None)` never reads `situation` and always
  appends `ScoreComponent("Scenario adjustment", 0)`. `cmd_score` passes `args.situation`; the
  `score` parser exposes `--situation` (+ shortcut flags). The output therefore shows a permanent
  zero component and implies scenario reasoning that never happened. (`build-bag`/`explain` keep
  `--situation`, where it legitimately narrows which roles are built.)
- **Intended:** `score` no longer accepts `--situation`, and the always-zero component is gone.
- **Affected:** `discbag/recommend.py` `score_disc`; `discbag/cli.py` `cmd_score` (call site,
  ~line 877) and the `p_score` parser (drop `--situation` and its `situation=None` default).
- **Change:** remove the `situation` parameter from `score_disc` and delete the
  `components.append(ScoreComponent("Scenario adjustment", 0))` line. Update the `cmd_score` call
  to `score_disc(disc, role, args.goal, profile, today)`. Remove `--situation` from `p_score`.
  The other two `score_disc` call sites (cli.py:800, recommend.py:239) already omit `situation`,
  so they're unaffected.
- **Compatibility:** `score --situation windy` now errors with argparse's "unrecognized arguments"
  — acceptable, since it previously did nothing. `build-bag`/`explain` `--situation` untouched.
- **Tests (tests/test_cli.py / test that exercises score output):**
  - `score` output for a disc contains no "Scenario adjustment" line.
  - `score_disc(...)` component labels do not include "Scenario adjustment".
- **Wording:** remove `--situation` from any `score` docs/examples.

## Item 6 — `build-bag --size` separates gaps from size omissions

- **Current:** `recommend.build_bag` (discbag/recommend.py), after applying `size`, computes
  `gaps = [r for r in wanted if r.name not in kept_names]` — which folds in roles that **were**
  filled but got trimmed by the size cap. `cmd_build_bag` then prints them all under "Roles to
  fill:", telling a 3-disc travel bag that covered roles need filling.
- **Intended:** genuine uncovered roles (no qualifying disc) are reported separately from roles
  omitted only to honor `--size`.
- **Affected:** `discbag/recommend.py` `BagResult` (+ `build_bag`); `discbag/cli.py`
  `cmd_build_bag` output. `build_bag_explained` (used by `explain`) is a different path and is
  untouched.
- **Change:** add an `omitted` list field to `BagResult` (default empty). In `build_bag`, keep
  `gaps` as the roles with no available fill (computed as today, **before** the size trim). When
  `size` trims fills, set `omitted = [f.role for f in fills if f not in kept]` (roles that had a
  disc but were dropped). `cmd_build_bag` prints "Roles to fill:" for `gaps` and, only when
  `omitted` is non-empty, a separate "Left out to fit the size limit:" section.
- **Compatibility:** `BagResult` gains a field with a default, so existing construction/consumers
  keep working. Without `--size`, `omitted` is empty and output is unchanged.
- **Tests (tests/test_recommend.py):**
  - `build_bag(bag, size=N)` where a role has a qualifying disc but is trimmed → that role is in
    `omitted`, not `gaps`.
  - A genuinely unfilled role (no qualifying disc) is in `gaps`, not `omitted`.
  - Without `size`, `omitted == []` and `gaps` matches prior behavior.
  - CLI: `cmd_build_bag` with `--size` prints "Left out to fit" for omitted roles and does not
    list them under "Roles to fill".
- **Wording:** new CLI section header "Left out to fit the size limit:".

## Item 7 — `history` shows current damaged state

- **Current:** `cmd_history` (discbag/cli.py) prints status/uses/rounds/practices/first/last/reason
  but never the current `damaged` flag. An active damaged disc's damage is invisible in its history
  summary. (Legacy pre-event-log damage also lacks a timeline event, but seeding one is
  out of scope — see excluded C2; we show current **state**, not a fabricated event.)
- **Intended:** the history summary shows the disc's current damaged state when set — as state,
  never as an invented historical event.
- **Affected:** `discbag/cli.py` `cmd_history` summary block only.
- **Change:** in the summary, after the Status line, add `if u.damaged: print("  Damaged: yes")`.
  The timeline section is untouched (it still shows real `damaged`/`damaged_retired` events when
  they were recorded).
- **Compatibility:** additive; no data change. Non-damaged discs print no Damaged line.
- **Tests (tests/test_cli.py):**
  - `history` on an active damaged disc includes "Damaged: yes" in the summary.
  - `history` on a non-damaged disc has no "Damaged" line.
- **Wording:** new summary line "Damaged: yes".

## Item 8 — Documentation, help text, and examples

- **Current:** README says `restore` brings a disc "back to the bag" (matched only after Item 1);
  frames the carry bag and `choose` inconsistently with implementation; documents `score`'s
  behavior without noting `--situation`'s removal; uses "bag" in spots where it means inventory.
- **Intended:** docs and help match the shipped behavior and the terminology table above.
- **Affected:** `README.md`, `CHANGELOG.md`, and the argparse `help=` strings noted per item.
- **Change:**
  - README: state `restore` returns a disc to your **carry bag**; make explicit that `choose`
    and `practice` use the **carry bag** while `build-bag`/`recommend`/`overlap`/`chart`/`maturity`
    use **inventory**; document `bag ... --all`; ensure no `score --situation` reference remains.
  - CHANGELOG: one "Fixed"/"Changed" entry summarizing the correctness pass.
  - Audit the command-reference prose for generic "bag" that means inventory and correct it.
- **Compatibility:** docs only.
- **Tests:** none (docs). The full suite must stay green.

## Item 9 — Concurrent-write locking (out of scope)

Deferred. discbag loads the whole inventory at `__init__` and rewrites on every mutation; an
advisory lock spanning load–mutate–save is **not** trivial or isolated in this architecture (it
would restructure the load/save lifecycle). Per the directive, it stays out of the main
implementation scope. Left as a documented known limitation for a single-user local tool.

---

## Compatibility summary

- No inventory JSON schema changes; no migration. `BagResult` gains a defaulted field.
- Behavior changes visible to users: `restore` now carries the disc; `bag add/remove` disambiguates
  duplicates (or needs `--all`); `choose`/`practice` narrow to the carry bag (a no-op for users who
  never curated `in_bag`); `score --situation` is removed; `build-bag --size` output gains a "Left
  out to fit" section; `history` gains a Damaged line.

## Edge cases to cover

- Restore of a disc that was never in the bag before archiving still lands `in_bag=True` (intended:
  restore = carry it).
- `bag remove` on a mold you own one of: unique match, no prompt.
- `choose`/`practice` when the carry bag is empty but inventory isn't → distinct "No discs in your
  bag" message, not "inventory empty".
- `--count`/`--size`/`--per-slot` at exactly `1` are accepted; `0` and negatives rejected.
- `build-bag --size N` larger than the number of fills → `omitted` empty, no "Left out" section.
- `history` on a disc that is both archived and damaged shows both Status and Damaged lines.
