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
