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
    assert u.throw_count == 0
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


def test_remove_by_mold_name(tmp_path):
    inv = make_inv(tmp_path)
    inv.add(OwnedDisc.from_db_record(MAKO3))
    assert inv.remove("mako3") == 1
    assert inv.list_discs() == []


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
