from discbag import braille
from discbag.inventory import Disc


def test_single_dot_top_left_is_correct_pattern():
    c = braille.Canvas(2, 4)
    c.set(0, 0)
    # Top-left braille dot is 0x2800 + 0x01.
    assert c.render() == chr(0x2801)


def test_setting_all_dots_in_a_cell_is_full_block():
    c = braille.Canvas(2, 4)
    for x in range(2):
        for y in range(4):
            c.set(x, y)
    assert c.render() == chr(0x28FF)  # all 8 dots set


def test_out_of_bounds_is_ignored():
    c = braille.Canvas(2, 4)
    c.set(99, 99)  # no error, no dot
    c.set(-1, 0)
    assert c.render() == chr(0x2800)  # blank braille cell


def test_render_has_expected_row_count():
    c = braille.Canvas(4, 8)  # 2 char-cols x 2 char-rows
    lines = c.render().split("\n")
    assert len(lines) == 2
    assert all(len(line) == 2 for line in lines)


def test_flight_scatter_includes_axes_and_legend():
    bag = [
        Disc(name="Wizard", brand="Gateway", speed=2, glide=3, turn=0, fade=2),
        Disc(name="Destroyer", brand="Innova", speed=12, glide=5, turn=-1, fade=3),
    ]
    out = braille.flight_scatter(bag)
    assert "understable" in out.lower()
    assert "overstable" in out.lower()
    assert "speed" in out.lower()
    assert "Wizard" in out and "Destroyer" in out
    # Contains braille block characters.
    assert any(0x2800 <= ord(ch) <= 0x28FF for ch in out)
