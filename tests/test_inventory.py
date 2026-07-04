import json

from discbag import inventory
from discbag.inventory import Disc, OwnedDisc, UserData

MAKO3 = {"name": "Mako3", "brand": "Innova", "category": "Midrange",
         "speed": 5, "glide": 5, "turn": 0, "fade": 0, "stability": "Stable"}


def make_inv(tmp_path):
    return inventory.Inventory(path=tmp_path / "inventory.json")


# ---------- Disc (manufacturer / mold) ----------

def test_disc_is_manufacturer_only():
    d = Disc.from_db_record(MAKO3)
    assert d.name == "Mako3"
    assert (d.speed, d.glide, d.turn, d.fade) == (5, 5, 0, 0)
    # Manufacturer records carry no user fields.
    assert not hasattr(d, "plastic")


# ---------- OwnedDisc separates manufacturer from user data ----------

def test_owned_from_db_record_caches_manufacturer_and_holds_user_data():
    disc = OwnedDisc.from_db_record(MAKO3, plastic="Star", weight=175, color="orange")
    # manufacturer accessors delegate to the cached mold snapshot
    assert disc.name == "Mako3"
    assert disc.brand == "Innova"
    assert (disc.speed, disc.glide, disc.turn, disc.fade) == (5, 5, 0, 0)
    # user data lives under .user
    assert disc.user.plastic == "Star"
    assert disc.user.weight == 175
    assert disc.user.color == "orange"


def test_owned_user_defaults():
    disc = OwnedDisc.from_db_record(MAKO3)
    u = disc.user
    assert u.favorite is False
    assert u.tags == []
    assert u.role == ""
    assert u.use_count == 0
    assert u.last_used is None
    assert u.personal_flight is None


def test_owned_roundtrips_through_dict_keeping_sections_separate():
    disc = OwnedDisc.from_db_record(MAKO3, plastic="Star", weight=175)
    data = disc.to_dict()
    assert data["brand"] == "Innova" and data["mold"] == "Mako3"
    assert "cached" in data and "user" in data
    assert data["user"]["plastic"] == "Star"
    back = OwnedDisc.from_dict(data)
    assert back.name == "Mako3"
    assert back.user.plastic == "Star"
    assert back.speed == 5


def test_refresh_from_db_updates_cached_not_user():
    disc = OwnedDisc.from_db_record(MAKO3, plastic="Star")
    disc.user.notes = "my favorite"
    # DB now says the mold fades a touch more.
    updated = dict(MAKO3, fade=1)
    disc.refresh_from_db([updated])
    assert disc.fade == 1          # manufacturer data refreshed
    assert disc.user.plastic == "Star"     # user data untouched
    assert disc.user.notes == "my favorite"


def test_refresh_from_db_keeps_cache_when_mold_absent():
    disc = OwnedDisc.from_db_record(MAKO3, plastic="Star")
    disc.refresh_from_db([])  # mold not in DB anymore
    assert disc.speed == 5     # falls back to cached snapshot


# ---------- Inventory ----------

def test_add_and_list(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Leopard", speed=6, turn=-2, fade=1)))
    assert [d.name for d in inv.list_discs()] == ["Mako3", "Leopard"]


def test_add_persists_new_format(tmp_path):
    path = tmp_path / "inventory.json"
    inv = inventory.Inventory(path=path)
    inv.add(OwnedDisc.from_db_record(
        dict(MAKO3, name="Wizard", brand="Gateway", category="Putter",
             speed=2, glide=3, turn=0, fade=2, stability="Overstable"),
        plastic="SS Chalky"))
    reloaded = inventory.Inventory(path=path)
    discs = reloaded.list_discs()
    assert len(discs) == 1
    assert discs[0].name == "Wizard"
    assert discs[0].user.plastic == "SS Chalky"


# ---------- per-disc identity (multiple copies of a mold) ----------

def test_add_assigns_a_unique_id(tmp_path):
    inv = make_inv(tmp_path)
    a = inv.add(OwnedDisc.from_db_record(MAKO3))
    b = inv.add(OwnedDisc.from_db_record(MAKO3))
    assert a.id and b.id and a.id != b.id


def test_ids_persist_across_reload(tmp_path):
    path = tmp_path / "inventory.json"
    inv = inventory.Inventory(path=path)
    orig = inv.add(OwnedDisc.from_db_record(MAKO3)).id
    assert inventory.Inventory(path=path).list_discs()[0].id == orig


def test_load_backfills_missing_ids(tmp_path):
    path = tmp_path / "inventory.json"
    rec = OwnedDisc.from_db_record(MAKO3).to_dict()
    rec.pop("id", None)                          # legacy record without an id
    path.write_text(json.dumps([rec]))
    d = inventory.Inventory(path=path).list_discs()[0]
    assert d.id
    assert json.loads(path.read_text())[0]["id"] == d.id   # persisted


def test_match_prefers_exact_then_falls_back_to_substring(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Eagle")))
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="EagleX")))
    assert [d.name for d in inv.match("eagle")] == ["Eagle"]         # exact wins
    assert {d.name for d in inv.match("eag")} == {"Eagle", "EagleX"} # else substring


def test_mutation_on_one_disc_leaves_its_twin_untouched(tmp_path):
    inv = make_inv(tmp_path)
    r1 = inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Roadrunner"), plastic="Champion"))
    r2 = inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Roadrunner"), plastic="Star"))
    assert inv.set_favorite(r1, True) == 1       # passing the disc targets that copy
    assert r1.user.favorite is True and r2.user.favorite is False
    reloaded = inventory.Inventory(path=inv.path)
    favs = [d for d in reloaded.list_discs() if d.user.favorite]
    assert [d.user.plastic for d in favs] == ["Champion"]


def test_mutation_by_name_still_hits_all_copies(tmp_path):
    # Back-compat / bulk: a mold-name string targets every matching copy.
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Roadrunner"), plastic="Champion"))
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Roadrunner"), plastic="Star"))
    assert inv.add_tag("roadrunner", "beat-in") == 2


def test_delete_one_disc_by_identity(tmp_path):
    inv = make_inv(tmp_path)
    keep = inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Roadrunner"), plastic="Champion"))
    drop = inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Roadrunner"), plastic="Star"))
    assert inv.delete(drop) == 1
    remaining = inv.all_discs()
    assert len(remaining) == 1 and remaining[0].id == keep.id


def test_delete_hard_removes_by_mold_name(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    assert inv.delete("mako3") == 1
    assert inv.list_discs() == []
    assert inv.all_discs() == []


# ---------- disc lifecycle (status) ----------

def test_new_disc_is_active(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    assert inv.list_discs()[0].user.status == "active"


def test_archiving_hides_from_active_but_keeps_in_all(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.record_use("mako3", "2026-07-03T00:00:00+00:00")
    assert inv.set_status("mako3", "lost", reason="Left at Woodland Park 18") == 1
    # gone from the active inventory the engine sees...
    assert inv.list_discs() == []
    # ...but retained, with its history, in the full record
    archived = inv.all_discs()
    assert len(archived) == 1
    u = archived[0].user
    assert u.status == "lost"
    assert u.status_reason == "Left at Woodland Park 18"
    assert u.use_count == 1        # history preserved
    assert u.in_bag is False       # archiving takes it out of the carry bag


def test_restore_reactivates_a_disc(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.set_status("mako3", "retired", reason="worn out")
    assert inv.set_status("mako3", "active") == 1
    assert [d.name for d in inv.list_discs()] == ["Mako3"]
    assert inv.list_discs()[0].user.status_reason is None


def test_delete_removes_even_when_archived(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.set_status("mako3", "lost")
    assert inv.delete("mako3") == 1        # delete reaches archived discs
    assert inv.all_discs() == []


def test_filter_by_status(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Leopard")))
    inv.set_status("leopard", "sold")
    assert [d.name for d in inv.filter(status="sold")] == ["Leopard"]
    assert [d.name for d in inv.filter()] == ["Mako3"]                 # active only
    assert {d.name for d in inv.filter(include_archived=True)} == {"Mako3", "Leopard"}


def test_first_used_is_earliest_entry():
    from discbag.inventory import UserData
    u = UserData.from_dict({"use_dates": [
        {"date": "2026-07-03T00:00:00+00:00", "session_type": "round"},
        {"date": "2026-05-01T00:00:00+00:00", "session_type": "practice"},
    ]})
    assert u.first_used == "2026-05-01T00:00:00+00:00"


# ---------- migration from the old flat format ----------

def test_load_migrates_old_flat_records(tmp_path):
    path = tmp_path / "inventory.json"
    old = [{"name": "Wizard", "brand": "Gateway", "category": "Putter",
            "speed": 2, "glide": 3, "turn": 0, "fade": 2, "stability": "Overstable",
            "plastic": "SS Chalky", "weight": 175, "color": "blue", "notes": "grippy"}]
    path.write_text(json.dumps(old))

    inv = inventory.Inventory(path=path)
    discs = inv.list_discs()
    assert len(discs) == 1
    d = discs[0]
    assert isinstance(d, OwnedDisc)
    assert d.name == "Wizard" and d.brand == "Gateway"
    assert d.speed == 2 and d.fade == 2
    assert d.user.plastic == "SS Chalky"
    assert d.user.weight == 175
    assert d.user.color == "blue"
    assert d.user.notes == "grippy"


def test_migration_writes_backup(tmp_path):
    path = tmp_path / "inventory.json"
    old = [{"name": "Mako3", "brand": "Innova", "category": "Midrange",
            "speed": 5, "glide": 5, "turn": 0, "fade": 0, "stability": "Stable"}]
    path.write_text(json.dumps(old))

    inventory.Inventory(path=path)
    backup = path.with_suffix(".json.bak")
    assert backup.exists()
    assert json.loads(backup.read_text()) == old
