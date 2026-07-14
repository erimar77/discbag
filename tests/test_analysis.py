from discbag import analysis
from discbag.inventory import Disc

WIZARD = Disc(name="Wizard", brand="Gateway", category="Putter", speed=2, glide=3, turn=0, fade=2)
CHALLENGER = Disc(name="Challenger", brand="Discraft", category="Putter", speed=2, glide=3, turn=0, fade=2)
MAKO3 = Disc(name="Mako3", brand="Innova", category="Midrange", speed=5, glide=5, turn=0, fade=0)
BUZZZ = Disc(name="Buzzz", brand="Discraft", category="Midrange", speed=5, glide=4, turn=-1, fade=1)
DESTROYER = Disc(name="Destroyer", brand="Innova", category="Distance Driver", speed=12, glide=5, turn=-1, fade=3)
WAVE = Disc(name="Wave", brand="MVP", category="Distance Driver",
            speed=11, glide=5, turn=-2, fade=2)
WRAITH = Disc(name="Wraith", brand="Innova", category="Distance Driver",
              speed=11, glide=5, turn=-1, fade=3)


# ---------- overlap ----------

def test_overlap_groups_near_identical_discs():
    groups = analysis.overlap([WIZARD, CHALLENGER, MAKO3])
    # Wizard and Challenger have identical flight numbers -> one overlap group.
    assert any({d.name for d in g} == {"Wizard", "Challenger"} for g in groups)


def test_overlap_excludes_discs_with_no_close_neighbor():
    groups = analysis.overlap([WIZARD, CHALLENGER, DESTROYER])
    flat = {d.name for g in groups for d in g}
    assert "Destroyer" not in flat


def test_overlap_empty_when_all_distinct():
    assert analysis.overlap([MAKO3, DESTROYER]) == []


# ---------- compare ----------

def test_compare_builds_rows_for_each_metric():
    table = analysis.compare([MAKO3, BUZZZ])
    assert table.headers == ["Mako3", "Buzzz"]
    rows = {r.label: r.values for r in table.rows}
    assert rows["Speed"] == [5, 5]
    assert rows["Turn"] == [0, -1]
    assert rows["Fade"] == [0, 1]


def test_compare_includes_expected_role():
    table = analysis.compare([MAKO3])
    role_row = next(r for r in table.rows if r.label == "Role")
    assert role_row.values[0]  # a non-empty role label


def test_compare_includes_stability_row():
    table = analysis.compare([WAVE, WRAITH])
    stab = next(r for r in table.rows if r.label == "Stability")
    assert stab.values == ["neutral", "overstable"]   # Wave 0, Wraith 2


# ---------- choose ----------

def test_choose_headwind_prefers_overstable():
    bag = [MAKO3, DESTROYER, Disc(name="Firebird", speed=9, glide=3, turn=0, fade=4)]
    picks = analysis.choose(bag, wind="head", shape="straight", distance=300)
    # Into a headwind, the overstable Firebird should rank above the flippy Destroyer.
    order = [p.disc.name for p in picks]
    assert order.index("Firebird") < order.index("Destroyer")


def test_choose_short_straight_prefers_a_putter_or_mid():
    bag = [WIZARD, MAKO3, DESTROYER]
    picks = analysis.choose(bag, distance=60, shape="straight")
    assert picks[0].disc.name in {"Wizard", "Mako3"}


def test_choose_empty_bag_returns_empty():
    assert analysis.choose([], distance=100) == []


# ---------- practice ----------

def test_practice_prefers_straight_neutral_discs():
    bag = [MAKO3, DESTROYER, WIZARD]
    picks = analysis.practice(bag, count=1)
    # Mako3 (5/5/0/0) is the most neutral/straight -> best form disc.
    assert picks[0].name == "Mako3"


def test_practice_respects_count():
    bag = [MAKO3, BUZZZ, DESTROYER, WIZARD]
    assert len(analysis.practice(bag, count=2)) == 2
