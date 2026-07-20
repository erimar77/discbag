from datetime import date, datetime

import pytest

from discbag import db, export, recommend
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


def test_repeated_builds_with_the_same_injected_clock_agree():
    # NOTE: this only proves build() is stable given an identical injected
    # clock -- it would still pass if generated_at came from datetime.now(),
    # since both calls here use the same GENERATED_AT constant either way.
    # The real "export never calls datetime.now()" guarantee is enforced in
    # tests/test_export_invariants.py (test_generated_at_is_the_only_time_field_and_comes_from_injection).
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
              date_added="2025-03-11",
              last_used="2026-07-07")
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


def test_catalog_summary_reports_manufacturer_flight_not_personal_flight():
    # An owned disc with recorded personal numbers must still publish the
    # mold's own manufacturer flight in `catalog[]` -- catalog_map is keyed
    # by catalog_id, so this mold's summary would otherwise contradict the
    # same mold's manufacturer.flight wherever else it's referenced, and
    # would depend on which owned copy happened to populate the map first.
    # The disc's *own* personal numbers still belong in its inventory record.
    d = owned(personal_flight={"speed": 9, "glide": 9, "turn": 9, "fade": 9})
    out = build([d])
    assert out["catalog"]["gateway-wizard"]["flight"] == {
        "speed": 2, "glide": 3, "turn": 0, "fade": 2}
    assert out["inventory"][0]["computed"]["effective_flight"] == {
        "speed": 9.0, "glide": 9.0, "turn": 9.0, "fade": 9.0}


def test_catalog_map_deduplicates_repeated_molds():
    out = build([owned(disc_id="id-1"), owned(disc_id="id-2")])
    assert list(out["catalog"]) == ["gateway-wizard"]


def test_catalog_map_excludes_unreferenced_records():
    unreferenced = {"name": "Destroyer", "brand": "Innova", "category": "Distance Driver",
                    "stability": "Overstable", "speed": 12, "glide": 5, "turn": -1, "fade": 3}
    out = build([owned()], catalog=[unreferenced])
    assert "innova-destroyer" not in out["catalog"]


def test_catalog_map_deduplicates_identical_summaries_without_error():
    # Two owned discs of the exact same mold with identical cached data --
    # e.g. two physical copies of the same disc -- must collapse into ONE
    # catalog entry and must not be treated as a collision. This is the
    # ordinary, constant case: it happens every time a mold is owned twice.
    a = owned(disc_id="id-1", speed=2, glide=3, turn=0, fade=2)
    b = owned(disc_id="id-2", speed=2, glide=3, turn=0, fade=2)
    out = build([a, b])
    assert list(out["catalog"]) == ["gateway-wizard"]
    assert out["catalog"]["gateway-wizard"]["flight"] == {
        "speed": 2, "glide": 3, "turn": 0, "fade": 2}


def test_catalog_map_raises_when_the_same_catalog_id_carries_different_data():
    # Two owned discs share a catalog_id (same brand + mold name) but carry
    # different cached flight numbers -- e.g. one locally-authored, one
    # catalog-sourced under the same brand+name. There is no correct way to
    # pick a winner between two genuinely different summaries, so this must
    # fail loudly (regardless of which order the discs are passed in) rather
    # than silently keeping one and dropping the other.
    low_id = owned(disc_id="id-a", speed=2, glide=3, turn=0, fade=2)
    high_id = owned(disc_id="id-b", speed=9, glide=3, turn=-1, fade=1)
    for pair in ([low_id, high_id], [high_id, low_id]):
        with pytest.raises(ValueError, match="gateway-wizard"):
            build(pair)


def test_catalog_map_raises_on_a_true_catalog_id_slug_collision():
    # catalog_id is derived from brand + name and is NOT injective: brand
    # "A" + name "B C" and brand "A B" + name "C" both slug to "a-b-c". Two
    # owned discs landing on opposite sides of that boundary, with differing
    # flight numbers, must be caught -- not silently merged into one entry.
    left = owned(disc_id="id-left", brand="A", name="B C",
                 speed=5, glide=5, turn=0, fade=0)
    right = owned(disc_id="id-right", brand="A B", name="C",
                  speed=9, glide=3, turn=-1, fade=1)
    assert db.catalog_id(left) == db.catalog_id(right) == "a-b-c"  # confirm the fixture collides

    with pytest.raises(ValueError, match="a-b-c") as excinfo:
        build([left, right])
    message = str(excinfo.value)
    assert "'A' 'B C'" in message      # names the first colliding mold
    assert "'A B' 'C'" in message      # names the second colliding mold


# ---------- coverage / gaps ----------

def test_coverage_reports_every_role_with_priority_and_reason():
    from discbag.roles import ROLES
    out = build([owned()])
    coverage = out["analysis"]["coverage"]
    assert len(coverage) == len(ROLES)
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
    # A neutral midrange qualifies for the "Straight mid" role, the gap a
    # lone-putter bag is missing next — unlike a distance driver, which would
    # never qualify and would leave candidates empty for reasons unrelated to
    # what this test checks.
    catalog = [{"name": "Roc3", "brand": "Innova", "category": "Midrange",
                "stability": "Understable", "speed": 5, "glide": 4, "turn": 0, "fade": 1}]
    out = build([owned()], catalog=catalog)
    nxt = out["analysis"]["next_purchase"]
    assert nxt["role"]
    assert nxt["reason"]
    assert nxt["candidates"]
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


def test_maturity_is_computed_for_an_archived_only_bag():
    # No active discs, but the inventory is non-empty: assess_phase has a
    # designed "Discovery" branch for this case and it must not be discarded.
    out = build([owned(disc_id="id-lost", status="lost")])
    m = out["analysis"]["maturity"]
    assert m is not None
    assert m["phase"] == "Discovery"


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


def test_scenario_bags_goal_default_reads_from_analysis_defaults():
    """Regression test: scenario_bags must use ANALYSIS_DEFAULTS["goal"], not hardcoded.

    This test verifies that when scenario_bags calls _bag_result without a goal,
    it reads from ANALYSIS_DEFAULTS["goal"] instead of using a hardcoded literal.
    """
    from unittest import mock

    original_goal = export.ANALYSIS_DEFAULTS["goal"]
    try:
        # Set up a disc inventory
        discs = [owned(disc_id="id-wizard")]

        # Patch the recommend.build_bag to capture which goal was actually used
        original_build_bag = recommend.build_bag
        captured_goals = []

        def capturing_build_bag(*args, **kwargs):
            captured_goals.append(kwargs.get("goal"))
            return original_build_bag(*args, **kwargs)

        with mock.patch.object(recommend, "build_bag", side_effect=capturing_build_bag):
            # Change ANALYSIS_DEFAULTS["goal"] and rebuild
            export.ANALYSIS_DEFAULTS["goal"] = "development"
            build(discs)

        # Verify that scenario_bags called build_bag with goal="development"
        # (from ANALYSIS_DEFAULTS), not "coverage" (hardcoded).
        # scenario_bags makes 3 calls (for windy, woods, minimal), so check them all.
        scenario_goals = captured_goals[-3:]  # Last 3 calls are scenario_bags
        assert all(g == "development" for g in scenario_goals), (
            f"Expected scenario_bags to use development goal, but got: {scenario_goals}. "
            "The goal default may be hardcoded instead of reading from ANALYSIS_DEFAULTS."
        )

    finally:
        export.ANALYSIS_DEFAULTS["goal"] = original_goal


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
    from tests.conftest import prototype_disc

    proto = prototype_disc()
    proto.id = "id-proto"
    out = build([owned(), unknown_flight_disc(), owned(disc_id="id-lost", status="lost"), proto])
    for entry in out["analysis"]["exclusions"]:
        assert entry["reason"] in {"incomplete_flight_data", "inactive_status",
                                   "incomplete_manufacturer_data"}


def test_exclusions_are_sorted_by_id_then_reason():
    out = build([owned(disc_id="id-z"), unknown_flight_disc("id-a"),
                 owned(disc_id="id-m", status="lost")])
    keys = [(e["inventory_id"], e["reason"]) for e in out["analysis"]["exclusions"]]
    assert keys == sorted(keys)


def test_no_exclusions_when_every_disc_participates():
    assert build([owned()])["analysis"]["exclusions"] == []


def test_manufacturer_incomplete_disc_is_excluded_from_pairwise_only():
    """flight_known is True (via personal_flight), so this disc is NOT
    incomplete_flight_data and DOES appear in coverage. But compare_verdict()
    gates on manufacturer completeness, not flight_known, so pairwise_comparisons
    silently drops it unless _exclusions reports incomplete_manufacturer_data."""
    from tests.conftest import prototype_disc
    d = prototype_disc()
    d.id = "id-proto"
    out = build([owned(), d])

    entry = next(e for e in out["analysis"]["exclusions"]
                 if e["inventory_id"] == "id-proto")
    assert entry["reason"] == "incomplete_manufacturer_data"
    assert entry["excluded_from"] == ["pairwise_comparisons"]

    # The two conditions are genuinely distinct: this disc still appears in
    # coverage because flight_known(d) is True.
    covered_ids = {i for rc in out["analysis"]["coverage"] for i in rc["disc_ids"]}
    assert "id-proto" in covered_ids


def test_disc_that_is_both_inactive_and_flight_unknown_gets_both_reasons():
    d = unknown_flight_disc()
    d.user.status = "lost"
    out = build([d])
    reasons = {e["reason"] for e in out["analysis"]["exclusions"]
               if e["inventory_id"] == "id-unknown"}
    assert reasons == {"inactive_status", "incomplete_flight_data"}


def test_no_exclusion_names_gaps_or_next_purchase():
    d = unknown_flight_disc()
    d.user.status = "lost"
    out = build([owned(), d, owned(disc_id="id-lost2", status="lost")])
    for entry in out["analysis"]["exclusions"]:
        assert "gaps" not in entry["excluded_from"]
        assert "next_purchase" not in entry["excluded_from"]
