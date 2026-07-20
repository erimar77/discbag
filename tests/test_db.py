import json

import pytest

from discbag import db

# Mirrors the raw shape returned by the DiscIt API: flight numbers are strings.
RAW_SAMPLE = [
    {"name": "Mako3", "brand": "Innova", "category": "Midrange",
     "speed": "5", "glide": "5", "turn": "0", "fade": "0", "stability": "Stable"},
    {"name": "Leopard", "brand": "Innova", "category": "Control Driver",
     "speed": "6", "glide": "5", "turn": "-2", "fade": "1", "stability": "Understable"},
    {"name": "Leopard3", "brand": "Innova", "category": "Control Driver",
     "speed": "7", "glide": "5", "turn": "-2", "fade": "1", "stability": "Understable"},
    {"name": "Wizard", "brand": "Gateway", "category": "Putter",
     "speed": "2", "glide": "3", "turn": "0", "fade": "2", "stability": "Overstable"},
]


# ---------- normalize_name ----------

def test_normalize_lowercases_and_trims():
    assert db.normalize_name("  Mako3  ") == "mako3"


def test_normalize_strips_plastic_and_run_tokens():
    # "ss" (Gateway Super Soft) and "chalky" (a run) are not part of the disc identity.
    assert db.normalize_name("Gateway Wizard SS Chalky") == "gateway wizard"


def test_normalize_strips_weight_tokens():
    assert db.normalize_name("Star Destroyer 175g") == "destroyer"


# ---------- find_disc ----------

def test_find_disc_exact_name():
    best, alts = db.find_disc("mako3", RAW_SAMPLE)
    assert best["name"] == "Mako3"


def test_find_disc_matches_base_disc_ignoring_plastic_and_brand():
    best, alts = db.find_disc("Gateway Wizard SS Chalky", RAW_SAMPLE)
    assert best["name"] == "Wizard"
    assert best["brand"] == "Gateway"


def test_find_disc_returns_alternatives_for_ambiguous_query():
    best, alts = db.find_disc("leopard", RAW_SAMPLE)
    assert best["name"] == "Leopard"
    assert any(a["name"] == "Leopard3" for a in alts)


def test_find_disc_returns_none_when_no_match():
    best, alts = db.find_disc("zzzunknowndisc", RAW_SAMPLE)
    assert best is None
    assert alts == []


# ---------- update_db ----------

def test_update_db_coerces_numbers_and_stamps_timestamp(tmp_path):
    path = tmp_path / "discs.json"
    result = db.update_db(
        path=path,
        fetcher=lambda url: RAW_SAMPLE,
        now=lambda: "2026-06-23T12:00:00",
    )
    saved = json.loads(path.read_text())
    assert saved["last_updated"] == "2026-06-23T12:00:00"
    assert len(saved["discs"]) == 4
    mako = next(d for d in saved["discs"] if d["name"] == "Mako3")
    assert mako["speed"] == 5 and mako["turn"] == 0  # coerced from strings to ints
    leopard = next(d for d in saved["discs"] if d["name"] == "Leopard")
    assert leopard["turn"] == -2
    assert result["count"] == 4


def test_update_db_leaves_existing_snapshot_intact_on_fetch_error(tmp_path):
    path = tmp_path / "discs.json"
    path.write_text(json.dumps({"last_updated": "old", "discs": [{"name": "Keeper"}]}))

    def boom(url):
        raise OSError("network down")

    with pytest.raises(OSError):
        db.update_db(path=path, fetcher=boom, now=lambda: "new")

    saved = json.loads(path.read_text())
    assert saved["last_updated"] == "old"
    assert saved["discs"][0]["name"] == "Keeper"


# ---------- load_db ----------

def test_load_db_seeds_from_bundled_when_runtime_missing(tmp_path):
    runtime = tmp_path / "discs.json"
    bundled = tmp_path / "bundled.json"
    bundled.write_text(json.dumps({"last_updated": "2026-01-01T00:00:00", "discs": RAW_SAMPLE}))

    loaded = db.load_db(path=runtime, bundled_path=bundled)
    assert loaded["last_updated"] == "2026-01-01T00:00:00"
    assert len(loaded["discs"]) == 4
    assert runtime.exists()  # seeded a runtime copy


def test_load_db_reads_runtime_when_present(tmp_path):
    runtime = tmp_path / "discs.json"
    runtime.write_text(json.dumps({"last_updated": "runtime", "discs": []}))
    bundled = tmp_path / "bundled.json"
    bundled.write_text(json.dumps({"last_updated": "bundled", "discs": RAW_SAMPLE}))

    loaded = db.load_db(path=runtime, bundled_path=bundled)
    assert loaded["last_updated"] == "runtime"


# ---------- catalog_id ----------

def test_catalog_id_from_record_dict():
    assert db.catalog_id({"brand": "Gateway", "name": "Wizard"}) == "gateway-wizard"


def test_catalog_id_normalizes_case_space_and_punctuation():
    assert db.catalog_id({"brand": "Lone Star Discs", "name": "Artemis"}) == \
        "lone-star-discs-artemis"
    assert db.catalog_id({"brand": "Innova", "name": "Mako3"}) == "innova-mako3"
    assert db.catalog_id({"brand": "Gateway", "name": "Wizard SS"}) == "gateway-wizard-ss"


def test_catalog_id_accepts_an_object_with_brand_and_name():
    from discbag.inventory import Disc
    d = Disc(name="Wizard", brand="Gateway", category="Putter",
             speed=2, glide=3, turn=0, fade=2)
    assert db.catalog_id(d) == "gateway-wizard"


def test_catalog_id_omits_empty_parts_without_leaving_a_stray_hyphen():
    assert db.catalog_id({"brand": "", "name": "Wizard"}) == "wizard"
    assert db.catalog_id({"brand": "Gateway", "name": ""}) == "gateway"


def test_catalog_id_is_deterministic():
    rec = {"brand": "Gateway", "name": "Wizard"}
    assert db.catalog_id(rec) == db.catalog_id(rec)
