"""Contract invariants for the export schema.

These guard the properties the dashboard depends on: reproducible bytes, a
serializer that never becomes a second analysis surface, and snapshots that
render with no discbag installation.
"""

# Updating the golden fixture is an explicit act. Regenerate it with the command
# in docs/superpowers/plans/2026-07-20-export-json.md Task 10 Step 3, read the
# diff, and commit the regenerated fixture in the SAME commit as the schema
# change that motivated it. A silent regeneration hides a contract break.

import ast
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from discbag import export
from tests.test_export import ANALYSIS_DATE, GENERATED_AT, build, owned, twins

FIXTURE = Path(__file__).parent / "fixtures" / "export_snapshot.json"

# export.py may lean on the engine; nothing else may lean on export.py.
# "discbag" (bare) covers `from discbag import __version__, analysis, ...` --
# the package-level import itself, plus the __version__ constant it pulls in,
# which is metadata, not engine logic. It is intentionally NOT allowed to act
# as a wildcard prefix for arbitrary "discbag.whatever" -- see the matching
# logic in test_export_imports_only_the_approved_allowlist below.
ALLOWED_IMPORTS = {"discbag", "discbag.__version__", "discbag.analysis",
                   "discbag.db", "discbag.history", "discbag.inventory",
                   "discbag.maturity", "discbag.player", "discbag.recommend",
                   "discbag.roles"}


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


# The rule under test is "no ENGINE module imports export" -- not "no module
# in the package other than export.py imports export". discbag/ also holds
# cli.py, the command dispatcher: `discbag export` necessarily makes cli.py
# call into export.build_export(), so cli.py importing discbag.export is the
# feature working as designed, not a leaf-boundary violation. Listing the
# engine modules explicitly (rather than gitignoring cli.py with a bare
# exclusion) keeps the intent visible and keeps a newly added engine module
# covered by default -- a module has to be deliberately added here, so
# nothing slips through by omission the way a "not cli.py" exclusion would
# let a new consumer module slip through undetected.
#
# Do not "fix" this back to excluding cli.py by name: cli.py is the
# consumer/entry point, not an engine module, and it is EXPECTED to import
# export. If you find yourself wanting to add cli.py to this set, that is a
# sign the invariant should be re-examined, not silently satisfied.
_ENGINE_MODULE_NAMES = {
    "analysis.py", "braille.py", "chart.py", "db.py", "history.py",
    "inventory.py", "maturity.py", "player.py", "recommend.py", "roles.py",
}


def _engine_modules():
    pkg = Path(export.__file__).parent
    modules = [p for p in pkg.glob("*.py") if p.name in _ENGINE_MODULE_NAMES]
    # Fail loudly if the on-disk package and the explicit set above drift,
    # rather than silently under-covering a newly added engine module.
    found_names = {p.name for p in modules}
    assert found_names == _ENGINE_MODULE_NAMES, (
        f"_ENGINE_MODULE_NAMES is out of sync with discbag/*.py: "
        f"missing={_ENGINE_MODULE_NAMES - found_names} "
        f"extra_on_disk={found_names - _ENGINE_MODULE_NAMES}. Update the "
        f"explicit set above (not by adding a bare exclusion) to match "
        f"reality.")
    return modules


@pytest.mark.parametrize("module_path", _engine_modules(), ids=lambda p: p.name)
def test_no_engine_module_imports_export(module_path):
    assert not any(name.startswith("discbag.export") or name == "export"
                   for name in _imported_modules(module_path))


def test_export_imports_only_the_approved_allowlist():
    discbag_imports = {n for n in _imported_modules(export.__file__)
                       if n.split(".")[0] == "discbag"}
    # Sub-attribute forms like "discbag.roles.assess" resolve to their module.
    # The bare "discbag" entry must NOT act as a "discbag.anything" wildcard
    # prefix -- it only satisfies an exact "discbag" import (the package
    # itself). Without excluding it from the prefix check, EVERY submodule
    # import (e.g. "discbag.cli") would trivially match "discbag." and this
    # test would pass no matter what export.py imports.
    prefixable = ALLOWED_IMPORTS - {"discbag"}
    for name in discbag_imports:
        assert name in ALLOWED_IMPORTS or any(
            name.startswith(allowed + ".") for allowed in prefixable), name


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
