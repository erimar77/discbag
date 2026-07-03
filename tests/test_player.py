import json

from discbag import player
from discbag.player import PlayerProfile
from discbag.inventory import Disc

UNDERSTABLE_DD = Disc(name="Sidewinder", speed=13, glide=5, turn=-4, fade=1)
OVERSTABLE_DD = Disc(name="Nuke OS", speed=13, glide=5, turn=0, fade=4)
OVERSTABLE_9 = Disc(name="Firebird", speed=9, glide=3, turn=0, fade=4)
UNDERSTABLE_10 = Disc(name="Sword", speed=10, glide=5, turn=-3, fade=1)
MAKO3 = Disc(name="Mako3", speed=5, glide=5, turn=0, fade=0)
DESTROYER = Disc(name="Destroyer", speed=12, glide=5, turn=-1, fade=3)


# ---------- required power uses speed + turn + fade ----------

def test_understable_driver_needs_less_power_than_overstable_driver():
    assert player.required_power(UNDERSTABLE_DD) < player.required_power(OVERSTABLE_DD)


def test_overstable_9_can_need_more_power_than_understable_10():
    assert player.required_power(OVERSTABLE_9) > player.required_power(UNDERSTABLE_10)


def test_power_level_buckets_and_is_estimated():
    level, estimated = player.power_level(DESTROYER)
    assert level in {"Beginner", "Intermediate", "Advanced", "Elite"}
    assert estimated is True  # derived from flight numbers


def test_explicit_override_takes_precedence_and_is_not_estimated():
    disc = Disc(name="Scream", brand="Gateway", speed=12, glide=5, turn=-1, fade=2)
    overrides = {("gateway", "scream"): {"level": "Advanced", "distance": 375}}
    level, estimated = player.power_level(disc, overrides=overrides)
    assert level == "Advanced"
    assert estimated is False


# ---------- player power ----------

def test_power_speed_grows_with_distance():
    weak = PlayerProfile(max_distance=250)
    strong = PlayerProfile(max_distance=425)
    assert player.power_speed(weak) < player.power_speed(strong)


def test_power_speed_prefers_explicit_driver_speed():
    p = PlayerProfile(max_distance=250, driver_speed=11)
    assert player.power_speed(p) == 11


def test_power_speed_none_without_info():
    assert player.power_speed(PlayerProfile()) is None


# ---------- player-adjusted behavior ----------

def test_low_power_makes_a_driver_behave_overstable():
    weak = PlayerProfile(max_distance=250)
    speed, glide, turn, fade = player.adjusted_numbers(DESTROYER, weak)
    # Destroyer (turn -1, fade 3) plays much more overstable for a weak arm.
    assert turn > -1
    assert fade > 3


def test_high_power_leaves_a_driver_near_rated():
    strong = PlayerProfile(max_distance=430)
    speed, glide, turn, fade = player.adjusted_numbers(DESTROYER, strong)
    assert abs(turn - (-1)) < 0.6
    assert abs(fade - 3) < 0.6


def test_adjusted_numbers_no_profile_returns_manufacturer():
    assert player.adjusted_numbers(MAKO3, None) == (5, 5, 0, 0)


# ---------- persistence ----------

def test_profile_roundtrips_to_disk(tmp_path):
    path = tmp_path / "profile.json"
    p = PlayerProfile(experience="intermediate", hand="right", putt_hand="left",
                      max_distance=275, typical_distance=250, fairway_speed=7)
    player.save_profile(p, path=path)
    loaded = player.load_profile(path=path)
    assert loaded.experience == "intermediate"
    assert loaded.hand == "right"
    assert loaded.putt_hand == "left"   # throws right, putts left
    assert loaded.max_distance == 275
    assert loaded.fairway_speed == 7


def test_load_profile_missing_returns_empty(tmp_path):
    loaded = player.load_profile(path=tmp_path / "nope.json")
    assert isinstance(loaded, PlayerProfile)
    assert loaded.max_distance is None
