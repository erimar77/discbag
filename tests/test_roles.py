import math

from discbag import roles
from discbag.inventory import Disc, OwnedDisc

# Canonical discs by their manufacturer flight numbers.
MAKO3 = Disc(name="Mako3", brand="Innova", category="Midrange", speed=5, glide=5, turn=0, fade=0)
BUZZZ = Disc(name="Buzzz", brand="Discraft", category="Midrange", speed=5, glide=4, turn=-1, fade=1)
WIZARD = Disc(name="Wizard", brand="Gateway", category="Putter", speed=2, glide=3, turn=0, fade=2)
ROC = Disc(name="Roc", brand="Innova", category="Midrange", speed=4, glide=4, turn=0, fade=3)
LEOPARD = Disc(name="Leopard", brand="Innova", category="Fairway", speed=6, glide=5, turn=-2, fade=1)
FIREBIRD = Disc(name="Firebird", brand="Innova", category="Fairway", speed=9, glide=3, turn=0, fade=4)
DESTROYER = Disc(name="Destroyer", brand="Innova", category="Distance", speed=12, glide=5, turn=-1, fade=3)
TEEBIRD = Disc(name="Teebird", brand="Innova", category="Fairway", speed=7, glide=5, turn=0, fade=2)


def role(name):
    return next(r for r in roles.ROLES if r.name == name)


# ---------- role definitions are flight-driven ----------

def test_roles_defined_by_flight_not_speed_alone():
    # Straight mid is characterised by neutral turn and minimal fade, per the spec.
    mid = role("Straight mid")
    assert mid.turn[0] <= 0 <= mid.turn[1]
    assert mid.fade[0] <= 1 <= mid.fade[1]


def test_utility_requires_big_fade():
    util = role("Utility driver")
    assert util.fade[0] >= 4  # fade >= 4 defines a utility driver


# ---------- qualifies ----------

def test_straight_mid_qualification():
    assert roles.qualifies(MAKO3, role("Straight mid"))
    assert roles.qualifies(BUZZZ, role("Straight mid"))
    assert not roles.qualifies(FIREBIRD, role("Straight mid"))


def test_utility_qualification():
    assert roles.qualifies(FIREBIRD, role("Utility driver"))
    assert not roles.qualifies(DESTROYER, role("Utility driver"))  # only fade 3


def test_putting_and_overstable_approach():
    assert roles.qualifies(WIZARD, role("Putting"))
    assert roles.qualifies(ROC, role("Overstable approach"))


def test_understable_fairway_takes_flippy_sub_7_speed():
    assert roles.qualifies(LEOPARD, role("Understable fairway"))


# ---------- effective flight prefers personal numbers ----------

def test_effective_flight_uses_personal_when_present():
    disc = OwnedDisc.from_db_record(
        {"name": "Leopard", "brand": "Innova", "speed": 6, "glide": 5, "turn": -2, "fade": 1})
    # This player's beat-in Leopard flips more and fades less.
    disc.user.personal_flight = {"speed": 6, "glide": 5, "turn": -3, "fade": 0.5}
    f = roles.effective_flight(disc)
    assert f.turn == -3 and f.fade == 0.5


def test_effective_flight_falls_back_to_manufacturer():
    f = roles.effective_flight(MAKO3)
    assert (f.speed, f.turn, f.fade) == (5, 0, 0)


# ---------- assessment with reasons ----------

def test_assess_marks_covered_and_missing_with_reasons():
    assessment = roles.assess([MAKO3, BUZZZ])
    mid = next(rc for rc in assessment if rc.role.name == "Straight mid")
    assert mid.covered is True
    assert {d.name for d in mid.discs} == {"Mako3", "Buzzz"}
    assert mid.reason  # explains why they satisfy it

    util = next(rc for rc in assessment if rc.role.name == "Utility driver")
    assert util.covered is False
    assert util.discs == []
    assert "utility" in util.reason.lower()


def test_multiple_discs_can_share_a_role():
    mid = next(rc for rc in roles.assess([MAKO3, BUZZZ]) if rc.role.name == "Straight mid")
    assert len(mid.discs) == 2


# ---------- suggestions & best next ----------

def test_suggest_returns_qualifying_unowned_discs():
    catalog = [FIREBIRD, DESTROYER, MAKO3]
    picks = roles.suggest(role("Utility driver"), owned=[], catalog=catalog, n=3)
    names = [p.disc.name for p in picks]
    assert "Firebird" in names
    assert "Destroyer" not in names  # doesn't qualify as utility


def test_suggest_prefers_preferred_brand_on_close_fit():
    from discbag.player import PlayerProfile
    legacy = Disc(name="Fighter", brand="Legacy", speed=10, glide=3, turn=0, fade=5)
    innova = Disc(name="Firebird2", brand="Innova", speed=9, glide=3, turn=0, fade=4)
    prof = PlayerProfile(preferred_brands=["Innova"])
    picks = roles.suggest(role("Utility driver"), [], [legacy, innova], n=2, profile=prof)
    assert picks[0].disc.brand == "Innova"          # promoted when the fit is close
    assert {p.disc.name for p in picks} == {"Fighter", "Firebird2"}  # both still included


def test_suggest_keeps_clearly_better_fit_over_preference():
    from discbag.player import PlayerProfile
    best = Disc(name="Best", brand="Legacy", speed=10, glide=3, turn=0, fade=4)   # near-ideal
    far = Disc(name="Far", brand="Innova", speed=13, glide=3, turn=0, fade=6)
    prof = PlayerProfile(preferred_brands=["Innova"])
    picks = roles.suggest(role("Utility driver"), [], [best, far], n=2, profile=prof)
    assert picks[0].disc.name == "Best"             # too far apart to promote


def test_suggest_preferred_only_filters_to_preferred_brands():
    from discbag.player import PlayerProfile
    legacy = Disc(name="Fighter", brand="Legacy", speed=10, glide=3, turn=0, fade=5)
    innova = Disc(name="Firebird2", brand="Innova", speed=9, glide=3, turn=0, fade=4)
    prof = PlayerProfile(preferred_brands=["Innova"])
    picks = roles.suggest(role("Utility driver"), [], [legacy, innova], n=5,
                          profile=prof, preferred_only=True)
    assert [p.disc.brand for p in picks] == ["Innova"]


def test_suggest_excludes_owned_molds():
    catalog = [FIREBIRD]
    picks = roles.suggest(role("Utility driver"), owned=[FIREBIRD], catalog=catalog, n=3)
    assert picks == []


def test_best_next_picks_highest_priority_missing_role():
    # Bag with only a straight mid -> putting (priority 1) is the top missing role.
    catalog = [WIZARD, FIREBIRD]
    nxt = roles.best_next([MAKO3], catalog)
    assert nxt is not None
    assert nxt.coverage.role.name == "Putting"
    assert nxt.reason


def test_best_next_none_when_all_required_roles_covered():
    full = [WIZARD, ROC, MAKO3, FIREBIRD, LEOPARD, TEEBIRD, DESTROYER,
            Disc(name="Justice", speed=5, glide=4, turn=0, fade=3),   # overstable mid
            Disc(name="Zone", speed=4, glide=3, turn=0, fade=3)]      # overstable approach
    assert roles.best_next(full, []) is None


# ---------- situations select a subset of roles ----------

def test_windy_situation_includes_overstable_roles():
    names = {r.name for r in roles.roles_for_situation("windy")}
    assert "Utility driver" in names
    assert "Overstable mid" in names


def test_minimal_situation_is_smaller_than_full():
    assert len(roles.roles_for_situation("minimal")) < len(roles.ROLES)


# ---------- stability helpers ----------

def test_stability_number_is_turn_plus_fade():
    from discbag import roles
    from discbag.inventory import Disc
    d = Disc(name="X", speed=11, glide=5, turn=-2, fade=3)
    assert roles.stability_number(d) == 1.0


def test_stability_word_thresholds():
    from discbag import roles
    assert roles.stability_word(-2) == "very understable"
    assert roles.stability_word(-1) == "understable"
    assert roles.stability_word(0) == "neutral"
    assert roles.stability_word(2) == "overstable"
    assert roles.stability_word(3) == "very overstable"


# ---------- flight_known ----------

def test_flight_known_manufacturer_complete():
    from discbag.inventory import Disc
    assert roles.flight_known(Disc(name="B", speed=5, glide=4, turn=-1, fade=1)) is True
    assert roles.flight_known(Disc(name="C", speed=10)) is False        # glide/turn/fade None


def test_flight_known_via_personal(tmp_path):
    from discbag.inventory import OwnedDisc
    rec = {"name": "Comanche", "brand": "Gateway", "category": "",
           "speed": 10, "glide": None, "turn": None, "fade": None, "stability": ""}
    d = OwnedDisc.from_db_record(rec)
    assert roles.flight_known(d) is False
    d.user.personal_flight = {"speed": 10, "glide": 5, "turn": -1, "fade": 2}
    assert roles.flight_known(d) is True                                # personal completes it


def test_personal_incomplete_does_not_satisfy():
    from discbag.inventory import OwnedDisc
    d = OwnedDisc.from_db_record({"name": "X", "brand": "Y", "speed": None,
                                  "glide": None, "turn": None, "fade": None, "stability": ""})
    d.user.personal_flight = {"speed": 10}                              # partial
    assert roles.flight_known(d) is False
