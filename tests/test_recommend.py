from discbag import recommend
from discbag.inventory import Disc

MAKO3 = Disc(name="Mako3", speed=5, glide=5, turn=0, fade=0)
WIZARD = Disc(name="Wizard", speed=2, glide=3, turn=0, fade=2)
LEOPARD = Disc(name="Leopard", speed=6, glide=5, turn=-2, fade=1)
FIREBIRD = Disc(name="Firebird", speed=9, glide=3, turn=0, fade=4)
DESTROYER = Disc(name="Destroyer", speed=12, glide=5, turn=-1, fade=3)


def filled_roles(result):
    return {f.role.name: f.disc for f in result.filled}


def test_build_bag_fills_role_with_qualifying_disc():
    result = recommend.build_bag([MAKO3])
    assert filled_roles(result).get("Straight mid") is MAKO3


def test_build_bag_reports_unfilled_roles_as_gaps():
    result = recommend.build_bag([WIZARD])  # only a putter
    gap_names = {r.name for r in result.gaps}
    assert "Utility driver" in gap_names
    assert "Straight mid" in gap_names


def test_build_bag_uses_distinct_discs_when_available():
    # A bag with a distinct qualifier for every role -> no disc is reused.
    bag = [
        WIZARD,                                             # Putting
        Disc(name="Pathfinder", speed=4, glide=5, turn=0, fade=1),   # Straight approach
        Disc(name="Zone", speed=4, glide=3, turn=0, fade=3),         # Overstable approach
        MAKO3,                                              # Straight mid
        Disc(name="Justice", speed=5, glide=4, turn=0, fade=3),      # Overstable mid
        LEOPARD,                                            # Understable fairway
        Disc(name="Teebird", speed=7, glide=5, turn=0, fade=2),      # Control fairway
        FIREBIRD,                                           # Utility driver
        DESTROYER,                                          # Distance driver
    ]
    result = recommend.build_bag(bag)
    discs = [f.disc for f in result.filled]
    assert len(discs) == len(set(id(d) for d in discs))
    assert not result.gaps


def test_build_bag_size_limits_fills():
    result = recommend.build_bag([MAKO3, WIZARD, LEOPARD, FIREBIRD, DESTROYER], size=2)
    assert len(result.filled) == 2


def test_build_bag_situation_narrows_roles():
    result = recommend.build_bag([WIZARD], situation="minimal")
    all_roles = {f.role.name for f in result.filled} | {r.name for r in result.gaps}
    # Minimal omits e.g. the understable fairway role.
    assert "Understable fairway" not in all_roles
    assert "Straight mid" in all_roles
