"""Render a disc's event log as a chronological timeline for the ``history`` command.

The event log (``UserData.events``) stores structured dicts; this module maps them to
display labels. It is deliberately forgiving: an event whose ``type`` or ``status`` it does
not recognize is skipped, not raised, so a newer version's event kinds degrade gracefully
in an older one.
"""

# Every lifecycle status set_status() can persist maps to a label. `active` reads as a
# restoration (the disc came back to the bag).
_STATUS_LABELS = {
    "active": "Restored",
    "lost": "Lost",
    "retired": "Retired",
    "broken": "Broken",
    "sold": "Sold",
    "gifted": "Gifted",
}


def _with_reason(base, reason):
    return f"{base} ({reason})" if reason else base


def _label(event):
    """The display label for one event, or None if it should be skipped."""
    kind = event.get("type")
    if kind == "added":
        return "Added"
    if kind == "use":
        return ("Practice session (+1)" if event.get("session_type") == "practice"
                else "Round (+1)")
    if kind == "status":
        base = _STATUS_LABELS.get(event.get("status"))
        return _with_reason(base, event.get("reason")) if base else None
    if kind == "damaged":
        return _with_reason("Damaged", event.get("reason"))
    if kind == "damaged_retired":
        return _with_reason("Damaged and retired", event.get("reason"))
    return None


def timeline(user):
    """``(date, label)`` pairs for a disc's events, oldest-first.

    Undated events and events of an unknown type/status are dropped. A stable sort keeps
    same-day events in the order they were logged.
    """
    rows = []
    for event in (user.events or []):
        date = event.get("date")
        if not date:
            continue
        label = _label(event)
        if label is None:
            continue
        rows.append((date, label))
    return sorted(rows, key=lambda row: row[0])
