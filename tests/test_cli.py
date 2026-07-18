import argparse
import pytest

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


def test_cmd_history_prints_summary_and_timeline(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.record_use("mako3", "2026-07-13T00:00:00+00:00", session_type="practice")
    inv.set_status("mako3", "lost", reason="hole 7 water", when="2026-09-18T00:00:00+00:00")
    cli.cmd_history(_ns(name=["mako3"]), inv)
    out = capsys.readouterr().out
    assert "Status: Lost" in out                     # summary block, unchanged
    assert "History" in out                          # timeline section
    assert "2026-07-13  Practice session (+1)" in out
    assert "2026-09-18  Lost (hole 7 water)" in out


def test_cmd_history_damaged_retire_is_one_combined_line(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    cli.cmd_damaged(_ns(name=["mako3"], reason=None, retire=True, unset=False), inv)
    cli.cmd_history(_ns(name=["mako3"]), inv)
    out = capsys.readouterr().out
    assert "Damaged and retired" in out
    assert out.count("Damaged and retired") == 1     # single atomic event, one line


def test_cmd_list_hides_archived_unless_requested(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.add(OwnedDisc.from_db_record(dict(MAKO3, name="Leopard", speed=6)))
    inv.set_status("leopard", "sold")
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None, all=False, ids=False), inv)
    assert "Leopard" not in capsys.readouterr().out
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None, all=True, ids=False), inv)
    assert "Leopard" in capsys.readouterr().out


def test_cmd_list_ids_shows_ids(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    the_id = inv.all_discs()[0].id
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None,
                     all=False, ids=True), inv)
    assert the_id in capsys.readouterr().out


def test_cmd_list_hides_ids_by_default(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    the_id = inv.all_discs()[0].id
    cli.cmd_list(_ns(tag=None, favorite=False, in_bag=False, status=None,
                     all=False, ids=False), inv)
    assert the_id not in capsys.readouterr().out


# ---------- lost / damaged / replace lifecycle verbs ----------

def test_cmd_lost_archives_with_lost_status(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.record_use("mako3", "2026-07-03T00:00:00+00:00")
    cli.cmd_lost(_ns(name=["mako3"], reason="hole 7 water"), inv)
    out = capsys.readouterr().out
    assert "Lost" in out and "hole 7 water" in out
    assert inv.list_discs() == []                        # gone from the active bag
    archived = inv.all_discs()[0].user
    assert archived.status == "lost" and archived.use_count == 1   # history kept


def test_cmd_damaged_flags_but_keeps_carrying(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    cli.cmd_damaged(_ns(name=["mako3"], reason="cracked", retire=False, unset=False), inv)
    out = capsys.readouterr().out
    assert "damaged" in out.lower()
    d = inv.list_discs()[0]                               # still active & carried
    assert d.user.damaged is True and d.user.status == "active"


def test_history_active_damaged_disc_shows_no_lifecycle_reason(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    cli.cmd_damaged(_ns(name=["mako3"], reason="cracked rim", retire=False, unset=False), inv)
    capsys.readouterr()                                  # discard the damaged output
    cli.cmd_history(_ns(name=["mako3"]), inv)
    out = capsys.readouterr().out
    assert "Status: Active" in out
    assert "Reason:" not in out          # active disc has no lifecycle reason line


def test_cmd_damaged_retire_archives_as_broken(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    cli.cmd_damaged(_ns(name=["mako3"], reason=None, retire=True, unset=False), inv)
    assert inv.list_discs() == []
    u = inv.all_discs()[0].user
    assert u.status == "broken" and u.damaged is True


def test_cmd_damaged_unset_clears_the_flag(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.set_damaged("mako3", True)
    cli.cmd_damaged(_ns(name=["mako3"], reason=None, retire=False, unset=True), inv)
    assert inv.list_discs()[0].user.damaged is False


def test_cmd_damaged_rejects_retire_with_unset(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    rc = cli.cmd_damaged(_ns(name=["mako3"], reason=None, retire=True, unset=True), inv)
    assert rc == 1
    assert inv.list_discs()[0].user.status == "active"   # nothing changed


def test_cmd_replace_archives_old_and_adds_fresh(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    inv.record_use("mako3", "2026-05-01T00:00:00+00:00")
    cli.cmd_replace(_ns(name=["mako3"], status="broken", reason="worn",
                        plastic=None, weight=None, color=None), inv)
    out = capsys.readouterr().out
    assert "archived" in out.lower() and "fresh" in out.lower()
    active = inv.list_discs()
    assert len(active) == 1 and active[0].user.use_count == 0     # fresh history
    archived = [d for d in inv.all_discs() if not d.user.is_active]
    assert archived[0].user.status == "broken" and archived[0].user.use_count == 1


def test_cmd_replace_overrides_plastic(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    cli.cmd_replace(_ns(name=["mako3"], status=None, reason=None,
                        plastic="Champion", weight=171, color=None), inv)
    assert inv.list_discs()[0].user.plastic == "Champion"


def test_format_owned_shows_damaged_marker(tmp_path):
    disc = OwnedDisc.from_db_record(MAKO3)
    disc.user.damaged = True
    assert "Damaged" in cli.format_owned(disc)


def test_disc_row_shows_damaged_for_active_disc(tmp_path, capsys):
    disc = OwnedDisc.from_db_record(MAKO3)
    disc.user.damaged = True
    cli._print_disc_row(disc)
    assert "damaged" in capsys.readouterr().out.lower()


def test_lost_damaged_replace_are_registered_commands():
    parser = cli.build_parser()
    for cmd in ("lost", "damaged", "replace"):
        assert parser.parse_args([cmd, "mako3"]).func is not None


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


# ---------- multiple copies of a mold: disambiguation ----------

ROAD = {"name": "Roadrunner", "brand": "Innova", "category": "Fairway Driver",
        "speed": 7, "glide": 5, "turn": -4, "fade": 1, "stability": "Understable"}


def _two_roadrunners(tmp_path):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(ROAD, plastic="Champion", weight=171))
    inv.add(OwnedDisc.from_db_record(ROAD, plastic="Star", weight=163))
    return inv


def test_resolve_single_match_never_prompts(tmp_path, monkeypatch):
    inv = _bag(tmp_path, MAKO3)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)   # even interactive
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("prompted!")))
    got = cli._resolve(inv, "mako3")
    assert [d.name for d in got] == ["Mako3"]


def test_resolve_ambiguous_noninteractive_errors_and_lists(tmp_path, monkeypatch, capsys):
    inv = _two_roadrunners(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    assert cli._resolve(inv, "roadrunner") is None
    res = capsys.readouterr()
    blob = res.out + res.err
    assert "Champion" in blob and "Star" in blob     # both copies listed
    assert "171g" in blob                            # distinguishing detail


def test_resolve_interactive_prompt_picks_the_chosen_copy(tmp_path, monkeypatch):
    inv = _two_roadrunners(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "2")
    got = cli._resolve(inv, "roadrunner")
    assert len(got) == 1 and got[0].user.plastic == "Star"


def test_favorite_all_flag_targets_every_copy(tmp_path):
    inv = _two_roadrunners(tmp_path)
    cli.cmd_favorite(_ns(disc="roadrunner", unset=False, all=True), inv)
    assert all(d.user.favorite for d in inv.list_discs())


def test_remove_archives_only_the_chosen_copy(tmp_path, monkeypatch):
    inv = _two_roadrunners(tmp_path)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *_: "1")
    cli.cmd_remove(_ns(name=["roadrunner"], status=None, reason=None), inv)
    active = inv.list_discs()
    archived = [d for d in inv.all_discs() if not d.user.is_active]
    assert [d.user.plastic for d in active] == ["Star"]
    assert [d.user.plastic for d in archived] == ["Champion"]


def test_sync_targets_only_the_resolved_disc(tmp_path, monkeypatch):
    inv = _bag(tmp_path, MAKO3, dict(MAKO3, name="Leopard", speed=6, fade=1))
    monkeypatch.setattr(cli.db, "load_db",
                        lambda: {"discs": [dict(MAKO3, fade=2), dict(MAKO3, name="Leopard", speed=6, fade=4)]})
    cli.cmd_sync(_ns(disc="mako3", all=False), inv)
    by = {d.name: d.fade for d in inv.list_discs()}
    assert by["Mako3"] == 2      # refreshed
    assert by["Leopard"] == 1    # untouched — not targeted


def test_sync_all_refreshes_every_copy(tmp_path, monkeypatch):
    inv = _two_roadrunners(tmp_path)
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [dict(ROAD, fade=3)]})
    cli.cmd_sync(_ns(disc="roadrunner", all=True), inv)
    assert all(d.fade == 3 for d in inv.list_discs())


def test_sync_no_arg_refreshes_whole_bag(tmp_path, monkeypatch):
    inv = _bag(tmp_path, MAKO3, dict(MAKO3, name="Leopard", speed=6, fade=1))
    monkeypatch.setattr(cli.db, "load_db",
                        lambda: {"discs": [dict(MAKO3, fade=2), dict(MAKO3, name="Leopard", speed=6, fade=4)]})
    cli.cmd_sync(_ns(disc=None, all=False), inv)
    fades = sorted(d.fade for d in inv.list_discs())
    assert fades == [2, 4]


def _two_makos(tmp_path):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    return inv


def _edit_ns(**over):
    base = dict(name=[], id=None, manufacturer=None, mold=None, plastic=None,
                weight=None, color=None, condition=None, notes=None)
    base.update(over)
    return _ns(**base)


def test_cmd_edit_updates_metadata_in_place(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": []})
    inv = _inv_with_mako(tmp_path)
    cli.cmd_edit(_edit_ns(name=["mako3"], plastic="Champion", weight=171,
                          color="Orange"), inv)
    u = inv.all_discs()[0].user
    assert u.plastic == "Champion" and u.weight == 171 and u.color == "Orange"
    assert "Updated" in capsys.readouterr().out


def test_cmd_edit_requires_a_field(tmp_path, capsys):
    inv = _inv_with_mako(tmp_path)
    rc = cli.cmd_edit(_edit_ns(name=["mako3"]), inv)
    assert rc == 1
    assert "at least one field" in capsys.readouterr().err.lower()
    assert inv.all_discs()[0].user.plastic == ""       # nothing changed


def test_cmd_edit_ambiguous_name_errors_without_guessing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": []})
    inv = _two_makos(tmp_path)
    rc = cli.cmd_edit(_edit_ns(name=["mako3"], plastic="Star"), inv)
    assert rc == 1
    combined = capsys.readouterr()
    assert "match" in (combined.out + combined.err).lower()
    assert all(d.user.plastic == "" for d in inv.all_discs())   # neither modified


def test_cmd_edit_by_id_targets_one_copy(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": []})
    inv = _two_makos(tmp_path)
    target = inv.all_discs()[1]
    cli.cmd_edit(_edit_ns(id=target.id, plastic="Star"), inv)
    assert inv.find_by_id(target.id).user.plastic == "Star"
    assert inv.all_discs()[0].user.plastic == ""       # the other copy untouched


ROADRUNNER = {"name": "Roadrunner", "brand": "Innova", "category": "Fairway",
              "speed": 9, "glide": 5, "turn": -4, "fade": 1,
              "stability": "Understable"}


def test_cmd_edit_identity_change_prints_match_success(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [ROADRUNNER]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    typo = {"name": "Roadruner", "brand": "Innova", "category": "Fairway",
            "speed": 0, "glide": 0, "turn": 0, "fade": 0, "stability": ""}
    inv.add(OwnedDisc.from_db_record(typo))
    disc = inv.all_discs()[0]
    cli.cmd_edit(_edit_ns(id=disc.id, mold="Roadrunner"), inv)
    out = capsys.readouterr().out
    assert "Matched:" in out
    assert "9/5/-4/1" in out


def test_cmd_edit_identity_change_no_match_warns_on_stderr(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": []})
    inv = _inv_with_mako(tmp_path)
    rc = cli.cmd_edit(_edit_ns(name=["mako3"], mold="Nonexistent Mold"), inv)
    assert rc == 0
    assert inv.all_discs()[0].mold == "Nonexistent Mold"
    assert "no database match" in capsys.readouterr().err.lower()


WAVE = {"name": "Wave", "brand": "MVP", "category": "Distance Driver",
        "speed": 11, "glide": 5, "turn": -2, "fade": 2, "stability": ""}
WRAITH = {"name": "Wraith", "brand": "Innova", "category": "Distance Driver",
          "speed": 11, "glide": 5, "turn": -1, "fade": 3, "stability": ""}


def test_cmd_compare_prints_table_verdict_and_footer(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [WAVE, WRAITH]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(WAVE))
    inv.add(OwnedDisc.from_db_record(WRAITH))
    for i in range(2):
        inv.record_use("wave", f"2026-07-0{i+1}T00:00:00+00:00")
    for i in range(3):
        inv.record_use("wraith", f"2026-07-0{i+1}T00:00:00+00:00")
    inv.set_favorite("wave", True)
    cli.cmd_compare(_ns(discs=["wave", "wraith"]), inv)
    out = capsys.readouterr().out
    assert "Stability" in out                       # richer table
    assert "Bottom line" in out and "Overlap:" in out
    assert "Key difference:" in out and "How to use them:" in out
    assert "You've thrown" in out                   # ownership footer
    # Footer names rounds for each disc, with the unit on each.
    assert "the wave 2 rounds" in out.lower() and "the wraith 3 rounds" in out.lower()
    assert "favorite" in out.lower()                # Wave is a favorite


def test_cmd_compare_no_footer_when_no_rounds_thrown(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [WAVE, WRAITH]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(WAVE))
    inv.add(OwnedDisc.from_db_record(WRAITH))        # both owned, zero rounds thrown
    cli.cmd_compare(_ns(discs=["wave", "wraith"]), inv)
    out = capsys.readouterr().out
    assert "Bottom line" in out                      # verdict still shows
    assert "You've thrown" not in out                # but no footer with zero rounds


def test_cmd_compare_single_disc_has_no_footer(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [WAVE]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(WAVE))
    inv.record_use("wave", "2026-07-01T00:00:00+00:00")
    cli.cmd_compare(_ns(discs=["wave"]), inv)
    out = capsys.readouterr().out
    assert "You've thrown" not in out                # no footer for a 1-disc compare


def test_cmd_compare_footer_uses_singular_and_plural_rounds(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [WAVE, WRAITH]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(WAVE))
    inv.add(OwnedDisc.from_db_record(WRAITH))
    inv.record_use("wave", "2026-07-01T00:00:00+00:00")              # 1 round  -> singular
    for i in range(2):
        inv.record_use("wraith", f"2026-07-0{i+1}T00:00:00+00:00")   # 2 rounds -> plural
    cli.cmd_compare(_ns(discs=["wave", "wraith"]), inv)
    out = capsys.readouterr().out.lower()
    assert "the wave 1 round" in out and "1 rounds" not in out       # singular grammar
    assert "the wraith 2 rounds" in out


def test_cmd_compare_no_footer_when_a_disc_is_db_only(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    monkeypatch.setattr(cli.db, "load_db", lambda: {"discs": [WAVE, WRAITH]})
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(WAVE))         # only Wave owned; Wraith from DB
    cli.cmd_compare(_ns(discs=["wave", "wraith"]), inv)
    out = capsys.readouterr().out
    assert "Bottom line" in out                     # verdict still shows
    assert "You've thrown" not in out                # but no ownership footer


def test_cmd_maturity_developed(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    # A covered, settled, well-used bag. Monkeypatch not needed: give real coverage
    # via a broad speed spread and heavy concentrated usage.
    specs = [("Aviar", 2, 0, 2), ("Wizard", 2, 0, 1), ("Roc", 5, 0, 3),
             ("Buzzz", 5, -1, 1), ("Leopard", 6, -2, 1), ("Teebird", 7, 0, 2),
             ("Firebird", 9, 0, 4), ("Wraith", 11, -1, 3), ("Destroyer", 12, -1, 3)]
    for i, (mold, sp, tu, fa) in enumerate(specs):
        rec = {"name": mold, "brand": "Innova", "category": "x",
               "speed": sp, "glide": 5, "turn": tu, "fade": fa, "stability": ""}
        uses = 30 if i < 2 else 1                       # concentrate on 2 discs
        inv.add(OwnedDisc.from_db_record(rec, use_count=uses, last_used="2026-07-10",
                                         date_added="2025-01-01"))
    cli.cmd_maturity(_ns(), inv)
    out = capsys.readouterr().out
    assert "Collection Maturity" in out
    assert "Why:" in out
    # phase is one of the three labels
    assert any(p in out for p in ("Discovery", "Developing", "Developed"))


def test_cmd_maturity_empty_bag(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    cli.cmd_maturity(_ns(), inv)
    out = capsys.readouterr().out
    assert "Discovery" in out
    assert "empty" in out.lower()


def test_bag_remove_targets_one_copy(tmp_path, capsys, monkeypatch):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    target = inv.all_discs()[1]
    # Non-interactive resolve-by-id path: pass the id so it targets one copy.
    cli.cmd_bag(_ns(action="remove", name=["mako3"], id=target.id, all=False), inv)
    assert inv.find_by_id(target.id).user.in_bag is False
    assert inv.all_discs()[0].user.in_bag is True          # the other copy untouched


def test_bag_remove_all_pulls_every_copy(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    cli.cmd_bag(_ns(action="remove", name=["mako3"], id=None, all=True), inv)
    assert all(d.user.in_bag is False for d in inv.all_discs())


def test_bag_remove_ambiguous_non_interactive_errors(tmp_path, capsys):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    inv.add(OwnedDisc.from_db_record(MAKO3))
    inv.add(OwnedDisc.from_db_record(MAKO3))
    rc = cli.cmd_bag(_ns(action="remove", name=["mako3"], id=None, all=False), inv)
    assert rc == 1
    assert all(d.user.in_bag is True for d in inv.all_discs())   # nothing changed


def _bag_with(tmp_path, *specs):
    from discbag import inventory
    inv = inventory.Inventory(path=tmp_path / "inventory.json")
    for mold, speed, turn, fade in specs:
        rec = {"name": mold, "brand": "Innova", "category": "x",
               "speed": speed, "glide": 5, "turn": turn, "fade": fade, "stability": ""}
        inv.add(OwnedDisc.from_db_record(rec))
    return inv


def test_choose_uses_carry_bag_not_inventory(tmp_path, capsys):
    inv = _bag_with(tmp_path, ("Destroyer", 12, -1, 3), ("Teebird", 7, 0, 2))
    inv.set_in_bag("destroyer", False)               # pulled from the carry bag
    cli.cmd_choose(_ns(distance=350, wind=None, shape="straight"), inv)
    out = capsys.readouterr().out
    assert "Destroyer" not in out                    # out-of-bag disc not recommended


def test_practice_uses_carry_bag(tmp_path, capsys):
    inv = _bag_with(tmp_path, ("Mako3", 5, 0, 0), ("Firebird", 9, 0, 4))
    inv.set_in_bag("firebird", False)
    cli.cmd_practice(_ns(count=3), inv)
    out = capsys.readouterr().out
    assert "Firebird" not in out


def test_build_bag_still_uses_full_inventory(tmp_path, capsys):
    # Planning reasons over inventory, including out-of-bag discs.
    inv = _bag_with(tmp_path, ("Destroyer", 12, -1, 3))
    inv.set_in_bag("destroyer", False)
    cli.cmd_build_bag(_ns(size=None, situation=None, goal="coverage", rotate=False), inv)
    out = capsys.readouterr().out
    assert "Destroyer" in out                         # still considered for planning


def test_choose_empty_carry_bag_message(tmp_path, capsys):
    inv = _bag_with(tmp_path, ("Mako3", 5, 0, 0))
    inv.set_in_bag("mako3", False)                     # nothing carried
    cli.cmd_choose(_ns(distance=200, wind=None, shape=None), inv)
    out = capsys.readouterr().out
    assert "no discs in your bag" in out.lower()


def test_positive_int_validator():
    assert cli._positive_int("3") == 3
    for bad in ("0", "-1", "abc"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._positive_int(bad)


def test_iso_date_validator():
    assert cli._iso_date("2026-07-03") == "2026-07-03"
    for bad in ("not-a-date", "2026-13-40", "07/03/2026"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._iso_date(bad)


def test_parser_rejects_bad_date_and_count():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["round-used", "mako3", "--date", "not-a-date"])
    with pytest.raises(SystemExit):
        parser.parse_args(["practice", "--count", "-1"])


def test_score_has_no_scenario_component(tmp_path, capsys):
    from discbag import recommend, roles
    from discbag.inventory import Disc
    disc = Disc(name="Buzzz", brand="Discraft", category="Midrange",
                speed=5, glide=4, turn=-1, fade=1)
    role = roles.primary_role(disc)
    scored = recommend.score_disc(disc, role)
    assert not any("Scenario" in c.label for c in scored.components)
