from discbag import history
from discbag.inventory import UserData


def _user(*events):
    return UserData(events=list(events))


def test_added_and_use_labels():
    u = _user(
        {"date": "2026-07-12", "type": "added"},
        {"date": "2026-07-13", "type": "use", "session_type": "practice"},
        {"date": "2026-07-15", "type": "use", "session_type": "round"},
    )
    assert history.timeline(u) == [
        ("2026-07-12", "Added"),
        ("2026-07-13", "Practice session (+1)"),
        ("2026-07-15", "Round (+1)"),
    ]


def test_status_labels_with_and_without_reason_and_restore():
    u = _user(
        {"date": "2026-09-18", "type": "status", "status": "lost", "reason": "hole 7 water"},
        {"date": "2026-09-20", "type": "status", "status": "active", "reason": None},
        {"date": "2026-09-25", "type": "status", "status": "retired", "reason": None},
    )
    assert history.timeline(u) == [
        ("2026-09-18", "Lost (hole 7 water)"),
        ("2026-09-20", "Restored"),
        ("2026-09-25", "Retired"),
    ]


def test_damaged_and_combined_retire_labels():
    u = _user(
        {"date": "2026-08-01", "type": "damaged", "reason": "cracked rim"},
        {"date": "2026-08-12", "type": "damaged_retired", "reason": None},
    )
    assert history.timeline(u) == [
        ("2026-08-01", "Damaged (cracked rim)"),
        ("2026-08-12", "Damaged and retired"),
    ]


def test_oldest_first_and_same_day_keeps_insertion_order():
    u = _user(
        {"date": "2026-08-12", "type": "damaged", "reason": None},
        {"date": "2026-07-12", "type": "added"},
        {"date": "2026-08-12", "type": "status", "status": "broken", "reason": None},
    )
    assert history.timeline(u) == [
        ("2026-07-12", "Added"),
        ("2026-08-12", "Damaged"),          # same day, insertion order preserved
        ("2026-08-12", "Broken"),
    ]


def test_undated_and_unknown_events_are_dropped_not_raised():
    u = _user(
        {"type": "added"},                                   # no date
        {"date": "2026-07-13", "type": "flight_updated"},    # unknown type (future)
        {"date": "2026-07-14", "type": "status", "status": "mangled"},  # unknown status
        {"date": "2026-07-15", "type": "use", "session_type": "round"},
    )
    assert history.timeline(u) == [("2026-07-15", "Round (+1)")]


def test_empty_log_yields_empty_timeline():
    assert history.timeline(UserData(events=None)) == []
    assert history.timeline(UserData(events=[])) == []


def test_every_persistable_status_has_a_label():
    # Guards against a new lifecycle status slipping through unlabelled.
    for status in ("active", "lost", "retired", "broken", "sold", "gifted"):
        u = _user({"date": "2026-01-01", "type": "status", "status": status})
        assert history.timeline(u), f"status {status!r} rendered no label"
