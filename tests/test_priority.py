from discbag import roles
from discbag.player import PlayerProfile
from discbag.inventory import Disc

MAKO3 = Disc(name="Mako3", speed=5, glide=5, turn=0, fade=0)
BUZZZ = Disc(name="Buzzz", speed=5, glide=4, turn=-1, fade=1)
WIZARD = Disc(name="Wizard", speed=2, glide=3, turn=0, fade=2)

# A low-power player and a strong player.
WEAK = PlayerProfile(max_distance=260, typical_distance=245)
STRONG = PlayerProfile(max_distance=430)

# A bag that already behaves overstable for a weak arm.
LOWPOWER_BAG = [
    WIZARD, MAKO3, BUZZZ,
    Disc(name="Leopard", speed=6, glide=5, turn=-2, fade=1),
    Disc(name="River", speed=7, glide=7, turn=-1, fade=1),
    Disc(name="Roadrunner", speed=9, glide=5, turn=-4, fade=1),
]


def cov(assessment, role_name):
    return next(c for c in assessment if c.role.name == role_name)


def test_covered_role_is_satisfied():
    a = roles.assess([MAKO3, BUZZZ], profile=WEAK)
    assert cov(a, "Straight mid").priority == "Satisfied"


def test_utility_is_low_priority_for_weak_player():
    a = roles.assess(LOWPOWER_BAG, profile=WEAK)
    util = cov(a, "Utility driver")
    assert util.covered is False
    assert util.priority == "Low"
    assert "overstable" in util.priority_reason.lower()


def test_utility_is_higher_priority_for_strong_player():
    # Strong player, bag that does NOT already behave overstable for them.
    a = roles.assess(LOWPOWER_BAG, profile=STRONG)
    assert cov(a, "Utility driver").priority in {"High", "Medium"}


def test_missing_neutral_fairway_stays_useful_for_weak_player():
    # Control fairway is throwable at low power -> not demoted to Low.
    a = roles.assess([WIZARD, MAKO3], profile=WEAK)
    assert cov(a, "Control fairway").priority in {"High", "Medium"}


def test_no_profile_leaves_priority_by_essentialness():
    a = roles.assess([MAKO3], profile=None)
    # Missing putting (priority 1) is High; nothing is demoted without a profile.
    assert cov(a, "Putting").priority == "High"
    assert all(c.priority != "Low" for c in a)


def test_best_next_skips_low_priority_when_useful_role_missing():
    # Weak player missing both a useful role (control fairway) and utility (low value).
    bag = [WIZARD, MAKO3, BUZZZ]
    catalog = [
        Disc(name="Teebird", brand="Innova", speed=7, glide=5, turn=0, fade=2),   # control fairway
        Disc(name="Firebird", brand="Innova", speed=9, glide=3, turn=0, fade=4),  # utility
    ]
    nxt = roles.best_next(bag, catalog, profile=WEAK)
    assert nxt is not None
    # It should prefer the immediately-useful role over the low-value utility.
    assert nxt.coverage.role.name != "Utility driver"


def test_behaves_flight_uses_player_adjustment():
    f = roles.behaves_flight(Disc(name="Destroyer", speed=12, glide=5, turn=-1, fade=3), WEAK)
    assert f.fade > 3  # plays more overstable for a weak arm
