from discbag import inventory
from discbag.inventory import OwnedDisc, UserData

MAKO3 = {"name": "Mako3", "brand": "Innova", "category": "Midrange",
         "speed": 5, "glide": 5, "turn": 0, "fade": 0, "stability": "Stable"}
WIZARD = {"name": "Wizard", "brand": "Gateway", "category": "Putter",
          "speed": 2, "glide": 3, "turn": 0, "fade": 2, "stability": "Overstable"}


def inv_with(tmp_path, *records):
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    for r in records:
        inv.add(OwnedDisc.from_db_record(r))
    return inv


def test_in_bag_defaults_true():
    assert UserData().in_bag is True


def test_add_tag_and_persist(tmp_path):
    path = tmp_path / "inventory.json"
    inv = inv_with(tmp_path, MAKO3)
    assert inv.add_tag("mako3", "field-work") == 1
    assert inventory.Inventory(path=path).list_discs()[0].user.tags == ["field-work"]


def test_add_tag_is_idempotent(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    inv.add_tag("mako3", "putting")
    inv.add_tag("mako3", "putting")
    assert inv.list_discs()[0].user.tags == ["putting"]


def test_remove_tag(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    inv.add_tag("mako3", "putting")
    assert inv.remove_tag("mako3", "putting") == 1
    assert inv.list_discs()[0].user.tags == []


def test_set_role(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    assert inv.set_role("mako3", "dead straight") == 1
    assert inv.list_discs()[0].user.role == "dead straight"


def test_set_favorite_toggles(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    inv.set_favorite("mako3", True)
    assert inv.list_discs()[0].user.favorite is True
    inv.set_favorite("mako3", False)
    assert inv.list_discs()[0].user.favorite is False


def test_set_in_bag(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    assert inv.set_in_bag("mako3", False) == 1
    assert inv.list_discs()[0].user.in_bag is False


def test_find_by_name_matches_all_of_a_mold(tmp_path):
    inv = inv_with(tmp_path, MAKO3, MAKO3)  # two Mako3s (e.g. two plastics)
    assert len(inv.find_by_name("mako3")) == 2


def test_unknown_disc_returns_zero(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    assert inv.add_tag("nonexistent", "x") == 0


def test_filter_by_tag(tmp_path):
    inv = inv_with(tmp_path, MAKO3, WIZARD)
    inv.add_tag("wizard", "putting")
    names = [d.name for d in inv.filter(tag="putting")]
    assert names == ["Wizard"]


def test_filter_by_favorite_and_in_bag(tmp_path):
    inv = inv_with(tmp_path, MAKO3, WIZARD)
    inv.set_favorite("mako3", True)
    inv.set_in_bag("wizard", False)
    assert [d.name for d in inv.filter(favorite=True)] == ["Mako3"]
    assert [d.name for d in inv.filter(in_bag=True)] == ["Mako3"]


def test_record_use_increments_and_timestamps(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    assert inv.record_use("mako3", "2026-07-03T12:00:00+00:00") == 1
    u = inv.list_discs()[0].user
    assert u.use_count == 1
    assert u.last_used == "2026-07-03T12:00:00+00:00"
    assert u.use_dates == ["2026-07-03T12:00:00+00:00"]


def test_record_use_accumulates(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    inv.record_use("mako3", "2026-07-01T00:00:00+00:00")
    inv.record_use("mako3", "2026-07-03T00:00:00+00:00")
    u = inv.list_discs()[0].user
    assert u.use_count == 2
    assert u.last_used == "2026-07-03T00:00:00+00:00"
    assert len(u.use_dates) == 2


def test_record_use_unknown_returns_zero(tmp_path):
    inv = inv_with(tmp_path, MAKO3)
    assert inv.record_use("nope", "2026-07-03") == 0


def test_legacy_throw_count_migrates_to_use_count():
    from discbag.inventory import UserData
    assert UserData.from_dict({"throw_count": 7}).use_count == 7
