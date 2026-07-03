from discbag import cli
from discbag.inventory import Disc, OwnedDisc


def test_flight_str_formats_four_numbers():
    d = Disc(name="Leopard", speed=6, glide=5, turn=-2, fade=1)
    assert cli.flight_str(d) == "6 / 5 / -2 / 1"


def test_flight_str_drops_trailing_zero_decimals():
    d = Disc(name="Half", speed=7, glide=5, turn=-1.5, fade=2)
    assert cli.flight_str(d) == "7 / 5 / -1.5 / 2"


def test_humanize_age_days():
    # 3 days between the snapshot stamp and "now"
    age = cli.humanize_age("2026-06-20T12:00:00+00:00", now_iso="2026-06-23T12:00:00+00:00")
    assert age == "3 days ago"


def test_humanize_age_today():
    age = cli.humanize_age("2026-06-23T08:00:00+00:00", now_iso="2026-06-23T12:00:00+00:00")
    assert age == "today"


def test_humanize_age_handles_missing():
    assert cli.humanize_age(None) == "unknown"


MAKO3 = {"name": "Mako3", "brand": "Innova", "category": "Midrange",
         "speed": 5, "glide": 5, "turn": 0, "fade": 0, "stability": "Stable"}


def test_format_owned_shows_user_and_manufacturer_data():
    disc = OwnedDisc.from_db_record(
        MAKO3, plastic="Star", weight=175, color="orange", condition="Used")
    disc.user.role = "Straight Midrange"
    out = cli.format_owned(disc)
    # manufacturer facts
    assert "Innova Mako3" in out
    assert "5 / 5 / 0 / 0" in out
    # user data
    assert "Star" in out
    assert "175" in out
    assert "orange" in out.lower()
    assert "Used" in out
    assert "Straight Midrange" in out


def test_format_owned_omits_blank_user_fields():
    disc = OwnedDisc.from_db_record(MAKO3)  # no plastic/weight/etc
    out = cli.format_owned(disc)
    assert "Weight" not in out
    assert "Condition" not in out


def test_parse_flight_numbers_slash_form():
    pf = cli.parse_flight("6/5/-1/2")
    assert pf == {"speed": 6, "glide": 5, "turn": -1, "fade": 2}


def test_parse_flight_rejects_wrong_count():
    assert cli.parse_flight("6/5/-1") is None


def test_format_owned_shows_personal_flight():
    disc = OwnedDisc.from_db_record(
        {"name": "Leopard", "brand": "Innova", "speed": 6, "glide": 5, "turn": -2, "fade": 1})
    disc.user.personal_flight = {"speed": 6, "glide": 5, "turn": -1, "fade": 2,
                                 "avg_distance": 255, "confidence": 5}
    out = cli.format_owned(disc)
    assert "Personal" in out
    assert "6 / 5 / -1 / 2" in out
    assert "255" in out


def test_format_profile_sections_units_and_comfort():
    from discbag.player import PlayerProfile
    prof = PlayerProfile(experience="beginner", hand="right", putt_hand="left",
                         style="backhand", typical_distance=250, max_distance=283,
                         spin_rate=900.0)
    out = cli.format_profile(prof)
    for section in ("Experience", "Throwing", "Performance", "Comfort Zone",
                    "Estimated Arm Power"):
        assert section in out
    # units + no stray precision
    assert "283 ft" in out
    assert "900 rpm" in out
    assert "900.0" not in out
    # derived comfort zone and arm power
    assert "2-7" in out
    assert "~Speed 6.9" in out
    # values are capitalized for display
    assert "Right" in out and "Left" in out and "Backhand" in out
