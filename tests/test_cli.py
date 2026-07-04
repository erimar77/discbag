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


def test_humanize_age_handles_naive_and_aware_mix():
    # A --date backfill stores a naive date; "now" is tz-aware. Must compare, not crash.
    assert cli.humanize_age("2026-07-02", now_iso="2026-07-03T12:00:00+00:00") == "yesterday"


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
    assert "Speed ~6.9" in out
    # values are capitalized for display
    assert "Right" in out and "Left" in out and "Backhand" in out


def test_format_profile_shows_preferred_brands():
    from discbag.player import PlayerProfile
    out = cli.format_profile(PlayerProfile(max_distance=283, preferred_brands=["Innova", "MVP"]))
    assert "Preferences" in out
    assert "Innova, MVP" in out


def _ns(**kw):
    from argparse import Namespace
    return Namespace(**kw)


def test_cmd_used_records_a_round_by_default(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    cli.cmd_used(_ns(discs=["mako3"], date="2026-07-03", session_type="round"), inv)
    u = inv.list_discs()[0].user
    assert u.round_count == 1 and u.practice_count == 0
    assert "round use" in capsys.readouterr().out


def test_cmd_used_records_a_practice_session(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    cli.cmd_used(_ns(discs=["mako3"], date="2026-07-03", session_type="practice"), inv)
    u = inv.list_discs()[0].user
    assert u.practice_count == 1 and u.round_count == 0
    assert "practice use" in capsys.readouterr().out


def _inv_with_mako(tmp_path):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    return inv


def test_cmd_remove_archives_and_preserves_history(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.record_use("mako3", "2026-07-03T00:00:00+00:00")
    cli.cmd_remove(_ns(name=["mako3"], status="lost", reason="Left at hole 18"), inv)
    out = capsys.readouterr().out
    assert "archived" in out.lower() and "Lost" in out
    assert inv.list_discs() == []                       # gone from active bag
    assert inv.all_discs()[0].user.use_count == 1       # history kept


def test_cmd_delete_cancelled_keeps_disc(tmp_path, capsys, monkeypatch):
    inv = _inv_with_mako(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _="": "n")
    rc = cli.cmd_delete(_ns(name=["mako3"], yes=False), inv)
    assert rc == 1
    assert len(inv.all_discs()) == 1                    # nothing erased


def test_cmd_delete_with_yes_erases(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.set_status("mako3", "lost")
    cli.cmd_delete(_ns(name=["mako3"], yes=True), inv)
    assert inv.all_discs() == []                        # erased even when archived


def test_cmd_restore_reactivates(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.set_status("mako3", "retired", reason="worn")
    cli.cmd_restore(_ns(name=["mako3"]), inv)
    assert [d.name for d in inv.list_discs()] == ["Mako3"]


def test_cmd_history_reports_status_reason_and_sessions(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.record_use("mako3", "2026-05-01T00:00:00+00:00")
    inv.record_use("mako3", "2026-07-03T00:00:00+00:00", session_type="practice")
    inv.set_status("mako3", "lost", reason="Woodland Park 18")
    cli.cmd_history(_ns(name=["mako3"]), inv)
    out = capsys.readouterr().out
    assert "Lost" in out
    assert "Woodland Park 18" in out
    assert "Rounds: 1" in out and "Practices: 1" in out
    assert "2026-05-01" in out            # first used


def test_cmd_list_hides_archived_unless_requested(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Leopard", speed=6)))
    inv.set_status("leopard", "sold")
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None, all=False), inv)
    assert "Leopard" not in capsys.readouterr().out
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None, all=True), inv)
    assert "Leopard" in capsys.readouterr().out


# ---------- home-screen dashboard ----------

def _bag(tmp_path, *records):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    for r in records:
        inv.add(OwnedDisc.from_db_record(r))
    return inv


LEOPARD = {"name": "Leopard", "brand": "Innova", "category": "Fairway Driver",
           "speed": 6, "glide": 5, "turn": -2, "fade": 1, "stability": "Understable"}


def test_dashboard_title_uses_profile_name_else_generic(tmp_path):
    from discbag.player import PlayerProfile
    inv = _bag(tmp_path, MAKO3)
    assert cli.render_dashboard(inv, PlayerProfile(name="Eric")).startswith("Eric's Disc Bag")
    assert cli.render_dashboard(inv, PlayerProfile()).startswith("Your Disc Bag")


def test_dashboard_inventory_counts_exclude_archived(tmp_path):
    from discbag.player import PlayerProfile
    inv = _bag(tmp_path, MAKO3, LEOPARD)
    inv.set_favorite("mako3", True)
    inv.set_status("leopard", "lost")            # archived -> not active, not counted
    out = cli.render_dashboard(inv, PlayerProfile())
    assert "Active discs   1" in out
    assert "Favorites      1" in out


def test_dashboard_player_section_and_empty_hint(tmp_path):
    from discbag.player import PlayerProfile
    inv = _bag(tmp_path, MAKO3)
    full = cli.render_dashboard(inv, PlayerProfile(max_distance=283, hand="right"))
    assert "283 ft" in full and "Arm power" in full and "Right" in full
    empty = cli.render_dashboard(inv, PlayerProfile())
    assert "No profile yet" in empty


def test_dashboard_recent_activity_is_relative(tmp_path):
    from discbag.player import PlayerProfile
    inv = _bag(tmp_path, MAKO3)
    inv.record_use("mako3", "2026-07-02T00:00:00+00:00", session_type="round")
    inv.record_use("mako3", "2026-07-03T00:00:00+00:00", session_type="practice")
    out = cli.render_dashboard(inv, PlayerProfile(), today="2026-07-03T12:00:00+00:00")
    assert "Last round     Yesterday" in out
    assert "Last practice  Today" in out


def test_dashboard_suggestions_come_from_the_engine(tmp_path):
    from discbag.player import PlayerProfile
    inv = _bag(tmp_path, MAKO3)                    # only a straight mid -> many roles missing
    out = cli.render_dashboard(inv, PlayerProfile())
    assert "Suggestions" in out
    assert "Missing roles" in out
    assert "Mako3" in out                          # a real practice suggestion


def test_dashboard_color_is_opt_in_and_stays_parseable(tmp_path):
    from discbag.player import PlayerProfile
    inv = _bag(tmp_path, MAKO3)
    prof = PlayerProfile(name="Eric", max_distance=283, hand="right")
    colored = cli.render_dashboard(inv, prof, color=True)
    plain = cli.render_dashboard(inv, prof, color=False)
    assert "\033[" in colored          # ANSI styling when asked
    assert "\033[" not in plain        # never when piped / in tests
    assert "Eric's Disc Bag" in colored  # the data is still there under the styling


def test_dashboard_empty_bag_onboards(tmp_path):
    from discbag.player import PlayerProfile
    inv = _bag(tmp_path)
    out = cli.render_dashboard(inv, PlayerProfile())
    assert "empty" in out.lower()
    assert "discbag add" in out


def test_top_level_help_is_grouped(tmp_path):
    help_text = cli.build_parser().format_help()
    for group in ("Common Commands", "Organization", "Analysis", "Advanced"):
        assert group in help_text


def test_subcommand_help_still_works():
    # build-bag --help exits (argparse) after printing its own help — unchanged behavior.
    import pytest
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["build-bag", "--help"])


def test_main_no_args_shows_dashboard_not_argparse_help(tmp_path, monkeypatch, capsys):
    from discbag import inventory, player
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    monkeypatch.setattr(cli, "Inventory", lambda: inv)
    monkeypatch.setattr(cli.player, "load_profile", lambda: player.PlayerProfile(name="Eric"))
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Eric's Disc Bag" in out
    assert "usage: discbag" not in out            # NOT argparse help
