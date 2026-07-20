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

def verdict_text(discs):
    """The rendered verdict, so the existing wording assertions keep testing
    exactly what the CLI prints."""
    from discbag.cli import render_compare_verdict
    v = analysis.compare_verdict(discs)
    return None if v is None else render_compare_verdict(v)


def test_verdict_two_discs_has_three_labeled_sections():
    v = verdict_text([WAVE, WRAITH])
    assert "Bottom line" in v
    assert "Overlap:" in v
    assert "Key difference:" in v
    assert "How to use them:" in v


def test_verdict_key_difference_matches_target_wording():
    v = verdict_text([WAVE, WRAITH])
    # Relative, per-disc trait sentences (reproduces the approved example).
    assert "The Wave has more high-speed turn and a gentler finish." in v
    assert "The Wraith resists turning more and fades harder." in v


def test_verdict_key_difference_no_awkward_double_and():
    # Disc that differs on all three axes as two "has" phrases + one verb phrase.
    a = Disc(name="Alpha", brand="X", category="Distance Driver",
             speed=12, glide=5, turn=-3, fade=3)
    b = Disc(name="Bravo", brand="Y", category="Distance Driver",
             speed=9, glide=4, turn=-1, fade=1)
    v = verdict_text([a, b])
    assert "ceiling and fades harder" not in v      # the awkward chain is gone
    assert "; it also fades harder" in v


def test_verdict_uses_relative_not_absolute_stability():
    v = verdict_text([WAVE, WRAITH])
    # No absolute "is overstable"/"is understable" declaration in the verdict.
    assert "is overstable" not in v
    assert "is understable" not in v


def test_verdict_same_slot_but_different_for_wave_wraith():
    v = verdict_text([WAVE, WRAITH])
    assert "same broad distance driver slot" in v.lower()
    assert "meaningfully different" in v


def test_verdict_how_to_use_has_softened_fade_caveat():
    v = verdict_text([WAVE, WRAITH])
    assert "finish left more strongly" in v
    assert "can still reflect the throw" in v
    # more-overstable disc (Wraith) is the one that finishes left more strongly
    assert "Expect the Wraith to finish left more strongly than the Wave" in v


def test_verdict_equal_stability_uses_direct_flight_language():
    # Same derived stability (turn+fade=1), different turn/fade split. An over/under
    # "reach for" pick would conflate turn with fade and contradict itself, so the
    # how-to-use section falls back to direct flight language.
    a = Disc(name="Alpha", brand="X", category="Fairway Driver",
             speed=7, glide=5, turn=-1, fade=2)     # more turn, more fade
    b = Disc(name="Beta", brand="Y", category="Fairway Driver",
             speed=7, glide=5, turn=0, fade=1)      # resists turning, gentler
    v = verdict_text([a, b])
    assert "more movement before the fade" not in v          # no contradictory advice
    assert "The Alpha has more turn and more fade." in v
    assert "The Beta resists turning more and finishes more gently." in v


def test_verdict_no_fabricated_use_split_when_finish_is_same():
    # Same turn AND fade, differ only in glide -> no invented "reach for X vs Y" split.
    a = Disc(name="Aviar", brand="Innova", category="Putter",
             speed=2, glide=3, turn=0, fade=2)
    b = Disc(name="Wizard", brand="Gateway", category="Putter",
             speed=2, glide=5, turn=0, fade=2)
    v = verdict_text([a, b])
    assert "Reach for" not in v
    assert "can still reflect the throw" not in v          # no caveat
    assert "no meaningful finish difference" in v


def test_verdict_three_plus_is_degraded_note():
    third = Disc(name="Firebird", brand="Innova", category="Distance Driver",
                 speed=9, glide=3, turn=0, fade=4)
    v = verdict_text([WAVE, WRAITH, third])
    assert "Key difference:" not in v          # no three-part verdict
    assert "Most similar:" in v
    assert "Most distinct:" in v
    # Wave & Wraith are the closest pair; Firebird the most distinct.
    assert "Wave" in v and "Wraith" in v and "Firebird" in v


def test_verdict_returns_structured_fields_for_two_discs():
    v = analysis.compare_verdict([WAVE, WRAITH])
    assert v.degraded_note is None
    assert "same broad distance driver slot" in v.overlap_text.lower()
    assert "The Wave has more high-speed turn and a gentler finish." in v.key_difference
    assert "finish left more strongly" in v.how_to_use


def test_verdict_structured_contains_no_section_headings():
    # Headings are presentation and belong to the CLI renderer, not the engine.
    v = analysis.compare_verdict([WAVE, WRAITH])
    for text in (v.overlap_text, v.key_difference, v.how_to_use):
        assert "Bottom line" not in text
        assert "Overlap:" not in text
        assert "Key difference:" not in text
        assert "How to use them:" not in text


def test_verdict_three_plus_sets_only_degraded_note():
    third = Disc(name="Firebird", brand="Innova", category="Distance Driver",
                 speed=9, glide=3, turn=0, fade=4)
    v = analysis.compare_verdict([WAVE, WRAITH, third])
    assert v.overlap_text is None
    assert v.key_difference is None
    assert v.how_to_use is None
    assert "Most similar:" in v.degraded_note


def test_verdict_none_for_fewer_than_two_discs():
    assert analysis.compare_verdict([WAVE]) is None
    assert analysis.compare_verdict([]) is None


def test_degraded_note_pair_selection_is_order_independent_on_ties():
    # Four discs on a line (by speed only -- glide/turn/fade held equal) built
    # so the two endpoints tie for "most distinct" (max total flight-distance
    # to the other three), and the two closest neighbor-pairs also tie for
    # "most similar" (Alpha-Bravo at distance 1, Charlie-Delta at distance 1).
    # WHICH pair is reported, and which single disc is "most distinct", must
    # not depend on bag order -- that's what disc_identity_key's tiebreak is
    # for. It does NOT promise the two names *within* the selected pair print
    # in the same order regardless of bag order: naming order is plain list-
    # position order (as it was pre-tiebreak), and reversing the bag reverses
    # which of the pair's two discs is encountered first. That is intentional
    # -- see _degraded_note's comment on why the identity key must not also
    # decide print order within the pair (that reordered every non-tied
    # 3+-disc comparison too, not just ties).
    alpha = Disc(name="Alpha", brand="X", category="Putter",
                speed=1, glide=3, turn=0, fade=0)
    bravo = Disc(name="Bravo", brand="X", category="Putter",
                speed=2, glide=3, turn=0, fade=0)
    charlie = Disc(name="Charlie", brand="X", category="Distance Driver",
                   speed=8, glide=3, turn=0, fade=0)
    delta = Disc(name="Delta", brand="X", category="Distance Driver",
                speed=9, glide=3, turn=0, fade=0)
    bag = [alpha, bravo, charlie, delta]

    import re
    pattern = re.compile(r"Most similar: (\w+) and (\w+)\. Most distinct: (\w+)\.")

    forward = analysis.compare_verdict(bag).degraded_note
    reverse = analysis.compare_verdict(list(reversed(bag))).degraded_note
    fwd_a, fwd_b, fwd_distinct = pattern.match(forward).groups()
    rev_a, rev_b, rev_distinct = pattern.match(reverse).groups()

    assert {fwd_a, fwd_b} == {rev_a, rev_b} == {"Alpha", "Bravo"}
    assert fwd_distinct == rev_distinct == "Alpha"


# ---------- Unknown-flight discs ----------

def test_choose_excludes_unknown_flight():
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)   # glide/turn/fade None
    picks = analysis.choose([known, unknown], distance=300, shape="straight")
    assert all(p.disc is not unknown for p in picks)


def test_overlap_excludes_unknown_flight():
    a = Disc(name="Buzzz", brand="Discraft", category="Midrange", speed=5, glide=4, turn=-1, fade=1)
    b = Disc(name="Buzzz2", brand="Discraft", category="Midrange", speed=5, glide=4, turn=-1, fade=1)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    groups = analysis.overlap([a, b, unknown])
    flat = [d for g in groups for d in g]
    assert unknown not in flat


def test_compare_renders_dash_for_unknown_flight():
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    table = analysis.compare([known, unknown])
    rows = {r.label: r.values for r in table.rows}
    assert rows["Glide"][1] == "—" and rows["Turn"][1] == "—"      # Unknown disc → dashes
    assert rows["Speed"][1] == 10                                    # a known field still shows


def test_compare_verdict_skipped_when_a_disc_is_unknown():
    known = Disc(name="Wraith", brand="Innova", category="Distance Driver",
                 speed=11, glide=5, turn=-1, fade=3)
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    assert analysis.compare_verdict([known, unknown]) is None       # can't reason without flight


# ---------- manufacturer-incomplete + personal-complete prototypes ----------

def test_choose_includes_prototype_reasoned_on_personal_numbers():
    from tests.conftest import prototype_disc
    d = prototype_disc()   # raw d.speed/turn/fade are all None
    picks = analysis.choose([d], distance=280, shape="straight")
    assert len(picks) == 1
    assert picks[0].disc is d


def test_overlap_includes_prototypes_that_fly_alike():
    from tests.conftest import prototype_disc
    d1 = prototype_disc(name="Comanche1")
    d2 = prototype_disc(name="Comanche2")
    groups = analysis.overlap([d1, d2])
    assert any({dd.name for dd in g} == {"Comanche1", "Comanche2"} for g in groups)


def test_compare_prototype_renders_dash_for_manufacturer_cells():
    from tests.conftest import prototype_disc
    d = prototype_disc()
    table = analysis.compare([WRAITH, d])
    rows = {r.label: r.values for r in table.rows}
    assert rows["Speed"][1] == "—"
    assert rows["Glide"][1] == "—"
    assert rows["Turn"][1] == "—"
    assert rows["Fade"][1] == "—"


def test_compare_verdict_none_when_manufacturer_incomplete_but_personal_complete():
    from tests.conftest import prototype_disc
    d = prototype_disc()
    assert analysis.compare_verdict([WRAITH, d]) is None
