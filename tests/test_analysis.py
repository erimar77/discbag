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


# ---------- compare_verdict ----------

def test_verdict_two_discs_has_three_labeled_sections():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert "Bottom line" in v
    assert "Overlap:" in v
    assert "Key difference:" in v
    assert "How to use them:" in v


def test_verdict_key_difference_matches_target_wording():
    v = analysis.compare_verdict([WAVE, WRAITH])
    # Relative, per-disc trait sentences (reproduces the approved example).
    assert "The Wave has more high-speed turn and a gentler finish." in v
    assert "The Wraith resists turning more and fades harder." in v


def test_verdict_uses_relative_not_absolute_stability():
    v = analysis.compare_verdict([WAVE, WRAITH])
    # No absolute "is overstable"/"is understable" declaration in the verdict.
    assert "is overstable" not in v
    assert "is understable" not in v


def test_verdict_same_slot_but_different_for_wave_wraith():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert "same broad distance driver slot" in v.lower()
    assert "meaningfully different" in v


def test_verdict_how_to_use_has_softened_fade_caveat():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert "finish left more strongly" in v
    assert "can still reflect the throw" in v
    # more-overstable disc (Wraith) is the one that finishes left more strongly
    assert "Expect the Wraith to finish left more strongly than the Wave" in v


def test_verdict_three_plus_is_degraded_note():
    third = Disc(name="Firebird", brand="Innova", category="Distance Driver",
                 speed=9, glide=3, turn=0, fade=4)
    v = analysis.compare_verdict([WAVE, WRAITH, third])
    assert "Key difference:" not in v          # no three-part verdict
    assert "Most similar:" in v
    assert "Most distinct:" in v
    # Wave & Wraith are the closest pair; Firebird the most distinct.
    assert "Wave" in v and "Wraith" in v and "Firebird" in v
