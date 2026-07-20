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
