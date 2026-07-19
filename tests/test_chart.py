from discbag import chart
from discbag.inventory import Disc

UNDERSTABLE = Disc(name="Roadrunner", speed=9, glide=5, turn=-4, fade=1)  # stability -3
OVERSTABLE = Disc(name="Firebird", speed=9, glide=3, turn=0, fade=4)      # stability +4
NEUTRAL = Disc(name="Mako3", speed=5, glide=5, turn=0, fade=0)            # stability 0


def test_stability_is_turn_plus_fade():
    assert chart.stability(UNDERSTABLE) == -3
    assert chart.stability(OVERSTABLE) == 4
    assert chart.stability(NEUTRAL) == 0


def test_col_understable_is_left_of_overstable():
    left = chart._col(chart.stability(UNDERSTABLE))
    right = chart._col(chart.stability(OVERSTABLE))
    assert left < right


def test_render_includes_axis_labels_and_disc_names():
    out = chart.render([UNDERSTABLE, OVERSTABLE, NEUTRAL])
    assert "understable" in out.lower()
    assert "overstable" in out.lower()
    assert "speed" in out.lower()
    # legend lists the discs
    assert "Roadrunner" in out
    assert "Firebird" in out


def test_render_empty_bag_message():
    out = chart.render([])
    assert "empty" in out.lower()


def test_grid_places_understable_marker_left_of_overstable_marker():
    # On the same speed row, the understable disc's marker column < overstable's.
    a = Disc(name="Aaa", speed=9, glide=5, turn=-4, fade=1)  # stability -3
    b = Disc(name="Bbb", speed=9, glide=3, turn=0, fade=4)   # stability +4
    out = chart.render([a, b], kind="grid")
    row = next(line for line in out.splitlines() if "A" in line and "B" in line)
    assert row.index("A") < row.index("B")


def test_default_flight_chart_uses_braille():
    bag = [Disc(name="Mako3", speed=5, glide=5, turn=0, fade=0)]
    out = chart.render(bag)
    assert any(0x2800 <= ord(ch) <= 0x28FF for ch in out)


BAG = [
    Disc(name="Wizard", brand="Gateway", category="Putter", speed=2, glide=3, turn=0, fade=2),
    Disc(name="Mako3", brand="Innova", category="Midrange", speed=5, glide=5, turn=0, fade=0),
    Disc(name="Firebird", brand="Innova", category="Distance Driver", speed=9, glide=3, turn=0, fade=4),
]


def test_speed_chart_is_a_histogram_with_counts():
    out = chart.render(BAG, kind="speed")
    assert "speed" in out.lower()
    assert "#" in out  # bars


def test_speed_chart_handles_personal_complete_prototype():
    # A manufacturer-incomplete disc with complete personal_flight must not crash the
    # speed histogram (it participates via its personal speed).
    from discbag.inventory import OwnedDisc
    proto = OwnedDisc.from_db_record({"name": "Comanche", "brand": "Gateway", "category": "",
                                      "speed": None, "glide": None, "turn": None, "fade": None,
                                      "stability": ""})
    proto.user.personal_flight = {"speed": 10, "glide": 5, "turn": -1, "fade": 2}
    out = chart.render(list(BAG) + [proto], kind="speed")     # must not raise
    assert "speed" in out.lower()


def test_composition_chart_breaks_down_by_category():
    out = chart.render(BAG, kind="composition")
    assert "Putter" in out
    assert "Midrange" in out


def test_brands_chart_lists_manufacturers():
    out = chart.render(BAG, kind="brands")
    assert "Innova" in out
    assert "Gateway" in out


def test_stability_chart_shows_distribution():
    out = chart.render(BAG, kind="stability")
    assert "overstable" in out.lower()


def test_unknown_kind_falls_back_to_flight():
    assert chart.render(BAG, kind="flight") == chart.render(BAG)


# ---------- Unknown-flight discs ----------

def test_stability_chart_skips_unknown_flight():
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)   # glide/turn/fade None
    out = chart.render(BAG + [unknown], kind="stability")
    assert "Comanche" not in out


def test_grid_chart_skips_unknown_flight():
    unknown = Disc(name="Comanche", brand="Gateway", speed=10)
    out = chart.render(BAG + [unknown], kind="grid")
    assert "Comanche" not in out


# ---------- manufacturer-incomplete + personal-complete prototypes ----------

def test_stability_uses_effective_flight_for_prototype():
    from tests.conftest import prototype_disc
    d = prototype_disc()   # personal turn=-1, fade=2 -> stability 1
    assert chart.stability(d) == 1


def test_grid_renders_prototype_via_personal_numbers_without_crashing():
    from tests.conftest import prototype_disc
    d = prototype_disc()   # raw d.speed/glide/turn/fade are all None
    out = chart.render([d], kind="grid")
    assert "Comanche" in out
    assert "10/5/-1/2" in out          # personal numbers, not raw manufacturer None
    assert "stability +1" in out


def test_default_braille_chart_renders_prototype_without_crashing():
    from tests.conftest import prototype_disc
    d = prototype_disc()
    out = chart.render([d])
    assert "Comanche" in out


def test_stability_chart_includes_prototype_without_crashing():
    from tests.conftest import prototype_disc
    d = prototype_disc()
    out = chart.render([d], kind="stability")
    assert "overstable" in out.lower()   # doesn't crash; still renders the buckets


def test_grid_shows_manufacturer_numbers_for_complete_disc_regression():
    # Regression guard: a manufacturer-complete disc with no personal_flight is
    # byte-for-byte unchanged since effective flight == manufacturer flight.
    out = chart.render([UNDERSTABLE], kind="grid")
    assert "9/5/-4/1" in out
    assert chart.stability(NEUTRAL) == 0
