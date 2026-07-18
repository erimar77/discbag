"""Command-line interface for discbag."""

import argparse
import sys
from datetime import datetime, timezone

from discbag import db, history, player, roles
from discbag.inventory import Disc, Inventory, OwnedDisc


# ---------- pure formatting helpers ----------

def _num_str(value):
    """Render a flight number without a trailing ".0"."""
    f = float(value)
    return str(int(f)) if f == int(f) else str(f)


def flight_str(disc):
    """Speed / glide / turn / fade, e.g. '6 / 5 / -2 / 1'."""
    return " / ".join(_num_str(v) for v in (disc.speed, disc.glide, disc.turn, disc.fade))


def parse_flight(text):
    """Parse 'speed/glide/turn/fade' into a dict, or None if malformed."""
    parts = [p.strip() for p in str(text).replace(",", "/").split("/") if p.strip()]
    if len(parts) != 4:
        return None
    try:
        speed, glide, turn, fade = (db._num(p) for p in parts)
    except (TypeError, ValueError):
        return None
    return {"speed": speed, "glide": glide, "turn": turn, "fade": fade}


def humanize_age(last_updated, now_iso=None):
    """Human-friendly age of a timestamp, e.g. 'today', '3 days ago'."""
    if not last_updated:
        return "unknown"
    try:
        then = datetime.fromisoformat(last_updated)
        now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(timezone.utc)
    except ValueError:
        return "unknown"
    # A --date backfill stores a naive timestamp; "now" is tz-aware. Compare at the
    # same awareness (day granularity makes the dropped offset immaterial).
    if (then.tzinfo is None) != (now.tzinfo is None):
        then, now = then.replace(tzinfo=None), now.replace(tzinfo=None)
    days = (now - then).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


# ---------- command implementations ----------

def _print_disc_row(disc):
    plastic = f" [{disc.plastic}]" if disc.plastic else ""
    u = getattr(disc, "user", None)
    star = " ★" if u and u.favorite else ""
    notes = []
    if u and not u.is_active:
        notes.append(u.status)                       # archived: show the lifecycle status
    elif u and not u.in_bag:
        notes.append("out of bag")
    if u and u.damaged:
        notes.append("damaged")                      # worn but (if active) still carried
    out = f" ({', '.join(notes)})" if notes else ""
    print(f"  {disc.brand} {disc.name}{plastic}{star}{out}".rstrip())
    role = f"  ·  {u.role}" if u and u.role else ""
    tags = f"  #{' #'.join(u.tags)}" if u and u.tags else ""
    print(f"      {flight_str(disc)}   {disc.category}  ({disc.stability}){role}{tags}".rstrip())


def format_owned(disc, profile=None):
    """Render an owned disc: manufacturer facts plus this physical disc's user data."""
    plastic = f" [{disc.plastic}]" if disc.plastic else ""
    lines = [f"{disc.brand} {disc.name}{plastic}"]

    u = disc.user
    user_rows = [
        ("Plastic", u.plastic),
        ("Weight", f"{u.weight}g" if u.weight else ""),
        ("Color", u.color),
        ("Condition", u.condition),
        ("Damaged", "yes" if u.damaged else ""),
        ("Bought at", u.purchase_location),
        ("Added", u.date_added),
        ("Use count", u.use_count or ""),
        ("Last used", u.last_used[:10] if u.last_used else ""),
        ("Tags", ", ".join(u.tags) if u.tags else ""),
        ("Favorite", "yes" if u.favorite else ""),
    ]
    for label, value in user_rows:
        if value:
            lines.append(f"  {label + ':':<11}{value}")

    lines.append("")
    lines.append(f"  Flight:    {flight_str(disc)}  (speed/glide/turn/fade, manufacturer)")
    pf = u.personal_flight
    if pf:
        nums = " / ".join(_num_str(pf[k]) for k in ("speed", "glide", "turn", "fade"))
        extra = []
        if pf.get("avg_distance"):
            extra.append(f"avg {pf['avg_distance']} ft")
        if pf.get("confidence"):
            extra.append("★" * int(pf["confidence"]))
        suffix = f"  ({', '.join(extra)})" if extra else ""
        lines.append(f"  Personal:  {nums}{suffix}")
    lines.append(f"  Category:  {disc.category}")
    lines.append(f"  Stability: {disc.stability}")
    role = u.role or _auto_role(disc)
    if role:
        lines.append(f"  Role:      {role}")

    level, est = player.power_level(disc)
    dist, _ = player.recommended_distance(disc)
    tag = " (estimated)" if est else ""
    lines.append(f"  Power:     {level}{tag}, ~{dist}+ ft")
    if profile is not None and not profile.is_empty():
        from discbag import roles
        f = roles.behaves_flight(disc, profile)
        word = roles.stability_word(f.turn + f.fade)
        nums = " / ".join(_num_str(round(v, 1)) for v in (f.speed, f.glide, f.turn, f.fade))
        lines.append(f"  For you:   plays {word}  ({nums})")

    if u.notes:
        lines.append(f"  Notes:     {u.notes}")
    return "\n".join(lines)


def _auto_role(disc):
    """The engine's best-fit role name, for display when no personal role is set."""
    from discbag import roles
    return roles.primary_role(disc).name


def cmd_updatedb(args, inv):
    print(f"Fetching discs from {db.DEFAULT_DB_URL} ...")
    try:
        result = db.update_db()
    except Exception as exc:  # noqa: BLE001 - surface any network/parse failure cleanly
        print(f"Update failed: {exc}", file=sys.stderr)
        print("Your existing database was left unchanged.", file=sys.stderr)
        return 1
    print(f"Updated database: {result['count']} discs. Last updated {result['last_updated']}.")
    return 0


def cmd_dbinfo(args, inv):
    data = db.load_db()
    stamp = data.get("last_updated")
    print(f"Disc database: {len(data.get('discs', []))} discs")
    print(f"Last updated:  {stamp or 'unknown'} ({humanize_age(stamp)})")
    print("Refresh with: discbag updatedb")
    return 0


def cmd_add(args, inv):
    query = " ".join(args.query).strip()
    data = db.load_db()
    best, alts = db.find_disc(query, data.get("discs", []))

    chosen = None
    if best is not None:
        interactive = sys.stdin.isatty() and not args.yes
        if not alts or not interactive:
            chosen = best
            print(f"Matched: {best['brand']} {best['name']} "
                  f"({best['speed']}/{best['glide']}/{best['turn']}/{best['fade']})")
        else:
            chosen = _prompt_choice(best, alts)

    if chosen is None and best is None:
        print(f"No database match for '{query}'.")
        if not sys.stdin.isatty():
            print("Run interactively to enter stats manually, or run 'discbag updatedb'.",
                  file=sys.stderr)
            return 1
        chosen = _prompt_manual(query)
        if chosen is None:
            print("Cancelled.")
            return 1
        record = chosen
    else:
        record = chosen

    today = datetime.now(timezone.utc).date().isoformat()
    disc = OwnedDisc.from_db_record(
        record, plastic=args.plastic or "", weight=args.weight,
        color=args.color or "", notes=args.notes or "",
        condition=args.condition or "", purchase_location=args.location or "",
        date_added=today,
    )
    inv.add(disc)
    plastic = f" in {disc.plastic}" if disc.plastic else ""
    print(f"Added {disc.brand} {disc.name}{plastic} to your bag.")
    return 0


def _prompt_choice(best, alts):
    options = [best] + alts
    print("Multiple matches found:")
    for i, d in enumerate(options, 1):
        print(f"  {i}. {d['brand']} {d['name']} "
              f"({d['speed']}/{d['glide']}/{d['turn']}/{d['fade']}) - {d['category']}")
    print("  m. enter stats manually")
    raw = input(f"Choose [1-{len(options)}, m] (default 1): ").strip().lower()
    if raw == "m":
        return _prompt_manual("")
    if not raw:
        return best
    try:
        idx = int(raw)
        if 1 <= idx <= len(options):
            return options[idx - 1]
    except ValueError:
        pass
    print("Invalid choice; using the first match.")
    return best


def _prompt_manual(query):
    print("Enter disc stats (leave blank to cancel):")
    name = input(f"  Name [{query}]: ").strip() or query
    if not name:
        return None
    brand = input("  Brand: ").strip()
    category = input("  Category (Putter/Midrange/Fairway/Distance): ").strip()

    def num(label):
        while True:
            raw = input(f"  {label}: ").strip()
            try:
                return db._num(raw)
            except (TypeError, ValueError):
                print("    Please enter a number.")

    return {
        "name": name, "brand": brand, "category": category, "stability": "",
        "speed": num("Speed"), "glide": num("Glide"),
        "turn": num("Turn"), "fade": num("Fade"),
    }


# ---------- resolving a typed name to a specific physical disc ----------

def _disc_descriptor(disc):
    """Short, human distinguishing details for one physical disc, for disambiguation."""
    u = disc.user
    bits = []
    if u.plastic:
        bits.append(u.plastic)
    if u.weight:
        bits.append(f"{u.weight}g")
    if u.color:
        bits.append(u.color)
    if u.condition:
        bits.append(u.condition)
    if u.purchase_location:
        bits.append(u.purchase_location)
    if u.date_added:
        bits.append(f"added {str(u.date_added)[:10]}")
    if not u.is_active:
        bits.append(u.status)
    if u.damaged:
        bits.append("damaged")
    if u.notes:
        bits.append(u.notes)
    return ", ".join(bits) if bits else "no distinguishing details"


def _print_matches(name, matches):
    print(f"Multiple discs match '{name}':\n")
    for i, d in enumerate(matches, 1):
        print(f"  {i}) {d.brand} {d.name}")
        print(f"     {_disc_descriptor(d)}")


def _prompt_for_disc(name, matches):
    _print_matches(name, matches)
    print()
    while True:
        try:
            raw = input(f"Select a disc [1-{len(matches)}] (blank to cancel): ").strip()
        except EOFError:
            return None
        if not raw:
            print("Cancelled.")
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(matches):
            return matches[int(raw) - 1]
        print(f"Please enter a number from 1 to {len(matches)}.")


def _resolve(inv, name, args=None, include_archived=False, allow_all=False):
    """Resolve a user-typed disc name to the physical disc(s) to act on.

    Returns a list of discs (one, or several only when a bulk command is given --all),
    or None when unresolved (a message is printed). A single match never prompts. An
    ambiguous name prompts in a terminal, but is a hard error when non-interactive —
    we never guess which physical disc was meant.
    """
    matches = inv.match(name, include_archived=include_archived)
    if not matches:
        print(f"No disc named '{name}' in your bag.", file=sys.stderr)
        return None
    if len(matches) == 1:
        return matches
    if allow_all and getattr(args, "all", False):
        return matches
    if not sys.stdin.isatty():
        _print_matches(name, matches)
        extra = ", or pass --all to apply to every copy" if allow_all else ""
        print(f"\n'{name}' matches {len(matches)} discs — "
              f"re-run in a terminal to choose{extra}.", file=sys.stderr)
        return None
    chosen = _prompt_for_disc(name, matches)
    return [chosen] if chosen else None


def cmd_remove(args, inv):
    """Archive a disc (default status: retired). It leaves the active bag but its
    history is preserved. Use `delete` to erase permanently."""
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name)
    if targets is None:
        return 1
    disc = targets[0]
    status = getattr(args, "status", None) or "retired"
    reason = getattr(args, "reason", None)
    inv.set_status(disc, status, reason=reason, when=_now_iso())
    print(f"Disc archived.\n  Status: {status.capitalize()}")
    if reason:
        print(f"  Reason: {reason}")
    return 0


def cmd_delete(args, inv):
    """Permanently erase a disc and all its history, after confirmation."""
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name, include_archived=True)
    if targets is None:
        return 1
    disc = targets[0]
    if not getattr(args, "yes", False):
        resp = input(f"This will permanently erase all history for {disc.brand} {disc.name} "
                     f"({_disc_descriptor(disc)}). Continue? (y/N) ").strip().lower()
        if resp not in ("y", "yes"):
            print("Cancelled.")
            return 1
    inv.delete(disc)
    print(f"Permanently deleted {disc.brand} {disc.name}.")
    return 0


def cmd_restore(args, inv):
    """Return an archived disc to the active bag."""
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name, include_archived=True)
    if targets is None:
        return 1
    disc = targets[0]
    inv.set_status(disc, "active", reason=None, when=_now_iso())
    print(f"Restored {disc.brand} {disc.name} to Active.")
    return 0


def cmd_lost(args, inv):
    """Mark a disc lost: archive it with status=lost. It leaves the active bag but
    keeps its history; `restore` brings it back if you find it."""
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name)
    if targets is None:
        return 1
    disc = targets[0]
    reason = getattr(args, "reason", None)
    inv.set_status(disc, "lost", reason=reason, when=_now_iso())
    print(f"Marked {disc.brand} {disc.name} as Lost.")
    if reason:
        print(f"  Reason: {reason}")
    return 0


def cmd_damaged(args, inv):
    """Flag a disc as damaged. By default it stays active and carried, just flagged;
    `--retire` archives it (worn beyond use) as broken; `--unset` clears the flag to
    correct a mistake. Discs are replaced, never repaired — see `replace`."""
    retire = getattr(args, "retire", False)
    unset = getattr(args, "unset", False)
    if retire and unset:
        print("Choose one of --retire or --unset, not both.", file=sys.stderr)
        return 1
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name)
    if targets is None:
        return 1
    disc = targets[0]
    reason = getattr(args, "reason", None)
    if unset:
        inv.set_damaged(disc, False)
        print(f"Cleared the damaged flag on {disc.brand} {disc.name}.")
        return 0
    if retire:
        inv.retire_damaged(disc, reason=reason, when=_now_iso())
        print(f"Retired {disc.brand} {disc.name} as damaged (Broken).")
    else:
        inv.set_damaged(disc, True, reason=reason, when=_now_iso())
        print(f"Marked {disc.brand} {disc.name} as damaged — still in your bag.")
    if reason:
        print(f"  Reason: {reason}")
    return 0


def cmd_replace(args, inv):
    """Replace a disc: archive the old copy (keeping its history) and add a fresh copy
    of the same mold with a clean history. The new copy inherits plastic/weight/color/
    role/favorite/tags; --plastic/--weight/--color override for a different run."""
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name)
    if targets is None:
        return 1
    disc = targets[0]
    status = getattr(args, "status", None) or "retired"
    reason = getattr(args, "reason", None)
    overrides = {k: getattr(args, k, None) for k in ("plastic", "weight", "color")
                 if getattr(args, k, None) is not None}
    new = inv.replace(disc, status=status, reason=reason, when=_now_iso(), **overrides)
    print(f"Replaced {disc.brand} {disc.name}.")
    print(f"  Old copy archived ({status.capitalize()}), history kept.")
    plastic = f" [{new.user.plastic}]" if new.user.plastic else ""
    print(f"  New copy added{plastic} — fresh history.")
    return 0


def cmd_edit(args, inv):
    """Correct a disc's inventory metadata in place (plastic, color, weight,
    condition, notes, or the manufacturer/mold identity). Metadata correction
    only: it changes nothing about the disc's career and logs no history event.
    Changing the manufacturer/mold refreshes the cached flight numbers from the
    database. A unique name is edited directly; an ambiguous name prompts (or is
    a hard error non-interactively); `--id` targets one copy for scripting."""
    edits = {
        "brand": args.manufacturer,
        "mold": args.mold,
        "plastic": args.plastic,
        "weight": args.weight,
        "color": args.color,
        "condition": args.condition,
        "notes": args.notes,
    }
    if all(v is None for v in edits.values()):
        print("Nothing to edit — pass at least one field, e.g. --plastic Champion.",
              file=sys.stderr)
        return 1

    disc_id = getattr(args, "id", None)
    if disc_id:
        disc = inv.find_by_id(disc_id)
        if disc is None:
            print(f"No disc with id '{disc_id}'.", file=sys.stderr)
            return 1
    else:
        name = " ".join(args.name).strip() if args.name else ""
        if not name:
            print("Name a disc to edit, or pass --id.", file=sys.stderr)
            return 1
        targets = _resolve(inv, name, include_archived=True)
        if targets is None:
            return 1
        disc = targets[0]

    db_discs = db.load_db().get("discs", [])
    identity_changed, matched = inv.update_metadata(disc, db_discs=db_discs, **edits)

    print(f"Updated {disc.brand} {disc.name}.")
    if identity_changed:
        if matched is not None:
            print(f"  Matched: {matched['brand']} {matched['name']} "
                  f"({matched['speed']}/{matched['glide']}/"
                  f"{matched['turn']}/{matched['fade']})")
        else:
            print("  Warning: no database match for the new identity; flight "
                  "numbers left unchanged. Run 'discbag updatedb' or check the "
                  "spelling.", file=sys.stderr)
    return 0


def cmd_history(args, inv):
    """A disc's full story — active or archived — including its lifecycle status."""
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name, include_archived=True)
    if targets is None:
        return 1
    d = targets[0]
    u = d.user
    print(f"{d.brand} {d.name}\n")
    print(f"  Status: {(u.status or 'active').capitalize()}")
    print(f"  Uses: {u.use_count or 0}")
    print(f"  Rounds: {u.round_count}")
    print(f"  Practices: {u.practice_count}")
    if u.first_used:
        print(f"  First used: {u.first_used[:10]}")
    if u.last_used:
        print(f"  Last used: {u.last_used[:10]}")
    if u.status_reason:
        print(f"  Reason: {u.status_reason}")
    print()

    events = history.timeline(u)
    if events:
        print("History\n")
        width = max(len(date) for date, _ in events)
        for date, label in events:
            print(f"  {date:<{width}}  {label}")
        print()
    return 0


def cmd_list(args, inv):
    filters = {}
    if getattr(args, "tag", None):
        filters["tag"] = args.tag
    if getattr(args, "favorite", False):
        filters["favorite"] = True
    if getattr(args, "in_bag", False):
        filters["in_bag"] = True
    if getattr(args, "status", None):
        filters["status"] = args.status
    elif getattr(args, "all", False):
        filters["include_archived"] = True
    # filter() defaults to active-only, so an empty filter set still hides archived discs.
    narrowed = any(k in filters for k in ("tag", "favorite", "in_bag", "status"))
    discs = sorted(inv.filter(**filters), key=lambda d: float(d.speed))
    if not discs:
        where = " matching that filter" if narrowed else ""
        print(f"No discs{where}." if narrowed else
              "Your bag is empty. Add discs with: discbag add <name>")
        return 0
    label = "matching" if narrowed else "discs"
    print(f"Your bag ({len(discs)} {label}):\n")
    show_ids = getattr(args, "ids", False)
    for d in discs:
        _print_disc_row(d)
        if show_ids:
            print(f"      id: {d.id}")
    return 0


def cmd_show(args, inv):
    name = " ".join(args.name).strip()
    targets = _resolve(inv, name)
    if targets is None:
        return 1
    prof = player.load_profile()
    print(format_owned(targets[0], profile=prof))
    print()
    return 0


def cmd_sync(args, inv):
    catalog = db.load_db().get("discs", [])
    name = getattr(args, "disc", None)
    if name:
        # A bulk-friendly command: resolve to one disc, or every copy with --all.
        targets = _resolve(inv, name, args=args, include_archived=True, allow_all=True)
        if targets is None:
            return 1
        inv.refresh_manufacturer(catalog, discs=targets)
        scope = targets[0].name if len(targets) == 1 else f"{len(targets)} '{name}' discs"
        print(f"Refreshed manufacturer data for {scope}. Your personal data was left untouched.")
        return 0
    n = inv.refresh_manufacturer(catalog)
    print(f"Refreshed manufacturer data for {n} disc(s) from the database. "
          "Your personal data was left untouched.")
    return 0


def _not_found(name):
    print(f"No disc named '{name}' in your bag.")
    return 1


def cmd_tag(args, inv):
    targets = _resolve(inv, args.disc, args=args, allow_all=True)
    if targets is None:
        return 1
    for d in targets:
        inv.add_tag(d, args.tag)
    print(f"Tagged {len(targets)} disc(s) with '{args.tag}'.")
    return 0


def cmd_untag(args, inv):
    targets = _resolve(inv, args.disc, args=args, allow_all=True)
    if targets is None:
        return 1
    for d in targets:
        inv.remove_tag(d, args.tag)
    print(f"Removed tag '{args.tag}' from {len(targets)} disc(s).")
    return 0


def cmd_role(args, inv):
    targets = _resolve(inv, args.disc)
    if targets is None:
        return 1
    role = " ".join(args.role)
    inv.set_role(targets[0], role)
    print(f"Set role of {targets[0].name} to '{role}'.")
    return 0


def cmd_favorite(args, inv):
    targets = _resolve(inv, args.disc, args=args, allow_all=True)
    if targets is None:
        return 1
    value = not args.unset
    for d in targets:
        inv.set_favorite(d, value)
    print(f"{'Marked' if value else 'Unmarked'} {len(targets)} disc(s) "
          f"as {'a favorite' if value else 'not a favorite'}.")
    return 0


def cmd_bag(args, inv):
    if args.action == "list":
        discs = sorted(inv.filter(in_bag=True), key=lambda d: float(d.speed))
        if not discs:
            print("No discs currently in the bag. Add with: discbag bag add <name>")
            return 0
        print(f"In the bag ({len(discs)} discs):\n")
        for d in discs:
            _print_disc_row(d)
        return 0

    name = " ".join(args.name)
    value = args.action == "add"
    n = inv.set_in_bag(name, value)
    if not n:
        return _not_found(name)
    verb = "Put" if value else "Pulled"
    where = "in the bag" if value else "out of the bag"
    print(f"{verb} {n} {name} disc(s) {where}.")
    return 0


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _days_ago(when, now_iso=None):
    from datetime import date
    try:
        then = date.fromisoformat(str(when)[:10])
        now = date.fromisoformat((now_iso or _now_iso())[:10])
    except (TypeError, ValueError):
        return None
    return (now - then).days


def cmd_used(args, inv):
    when = args.date or _now_iso()
    session_type = getattr(args, "session_type", "round")
    # Resolve every named disc first (prompting/erroring as needed) so recording is
    # all-or-nothing — a use is attached to one specific physical disc.
    resolved = []
    for name in args.discs:
        targets = _resolve(inv, name)
        if targets is None:
            return 1
        resolved.append(targets[0])
    for disc in resolved:
        inv.record_use(disc, when, session_type)
    label = "practice" if session_type == "practice" else "round"
    print(f"Recorded {label} use ({when[:10]}) for: "
          f"{', '.join(d.name for d in resolved)}.")
    return 0


def _staleness(disc):
    """Days since a disc was last used; +inf if never used (sorts as most neglected)."""
    if not disc.user.use_count:
        return float("inf")
    days = _days_ago(disc.user.last_used)
    return float("inf") if days is None else days


def _neglected(discs, threshold=30):
    """Discs not used within `threshold` days, most neglected first."""
    return sorted((d for d in discs if _staleness(d) > threshold),
                  key=_staleness, reverse=True)


def cmd_usage(args, inv):
    if args.disc:
        targets = _resolve(inv, args.disc, include_archived=True)
        if targets is None:
            return 1
        d = targets[0]
        u = d.user
        print(f"{d.brand} {d.name}\n")
        print(f"  Use count: {u.use_count or 0}")
        if u.last_used:
            days = _days_ago(u.last_used)
            ago = "today" if days == 0 else f"{days} days ago"
            print(f"  Last used: {u.last_used[:10]} ({ago})")
            print(f"  Recently used: {'Yes' if days is not None and days <= 30 else 'No'}")
        else:
            print("  Last used: never")
            print("  Recently used: No")
        # Break the count down by session type when either kind is on record.
        if u.round_count or u.practice_count:
            print(f"  Rounds: {u.round_count}")
            print(f"  Practices: {u.practice_count}")
            if u.last_round:
                print(f"  Last round: {u.last_round[:10]}")
            if u.last_practice:
                print(f"  Last practice: {u.last_practice[:10]}")
        print()
        return 0

    discs = inv.all_discs()   # overall stats span every disc you've owned
    used = sorted((d for d in discs if d.user.use_count), key=lambda d: -d.user.use_count)
    print("Most used discs\n")
    if used:
        for d in used[:10]:
            print(f"  {d.name:<14} {d.user.use_count}")
    else:
        print("  (none tracked yet — record a round with: discbag used <disc>...)")

    # "Neglected" is actionable advice — only active discs you could actually throw.
    neglected = _neglected(inv.list_discs())
    if neglected:
        print("\nNeglected discs\n")
        for d in neglected:
            note = "never used" if not d.user.use_count else f"last used {_days_ago(d.user.last_used)} days ago"
            print(f"  {d.name:<14} {note}")
    return 0


def cmd_build_bag(args, inv):
    import random

    from discbag import recommend  # local import keeps startup light
    discs = inv.list_discs()
    prof = player.load_profile()
    profile = None if prof.is_empty() else prof
    rng = random.Random() if args.rotate else None
    result = recommend.build_bag(discs, size=args.size, situation=args.situation,
                                 goal=args.goal, rotate=args.rotate, profile=profile,
                                 rng=rng, today=_now_iso())

    if not discs:
        print("Your bag is empty — add discs first with: discbag add <name>")
    situ = f", {args.situation}" if args.situation else ""
    rot = ", rotating" if args.rotate else ""
    print(f"Recommended bag (goal: {args.goal}{situ}{rot}):\n")
    for fit in result.filled:
        d = fit.disc
        plastic = f" [{d.plastic}]" if getattr(d, "plastic", "") else ""
        print(f"  {fit.role.name:<22} {d.brand} {d.name}{plastic}  ({flight_str(d)})")

    if result.gaps:
        print("\nRoles to fill:")
        for role in result.gaps:
            print(f"  {role.name:<22} {role.use}")
    return 0


def _score_line(disc_score):
    d = disc_score.disc
    return f"  {d.name:<16} {disc_score.total:>4}"


def _print_breakdown(disc_score):
    d = disc_score.disc
    print(f"{d.brand} {d.name}\n")
    for c in disc_score.components:
        print(f"  {c.label:<26} {c.points:+d}")
    print(f"  {'Total':<26} {disc_score.total:>4}")


def cmd_explain(args, inv):
    from discbag import recommend, roles
    prof = player.load_profile()
    profile = None if prof.is_empty() else prof
    today = _now_iso()

    if args.what == "role":
        role_name = " ".join(args.rest).strip()
        role = next((r for r in roles.ROLES if r.name.lower() == role_name.lower()), None)
        if role is None:
            print(f"Unknown role '{role_name}'. Roles: " +
                  ", ".join(r.name for r in roles.ROLES))
            return 1
        goal = args.goal
        candidates = sorted((recommend.score_disc(d, role, goal, profile, today)
                             for d in inv.list_discs() if roles.qualifies(d, role)),
                            key=lambda s: s.internal)
        print(f"{role.name}\n")
        if profile is not None:
            print("Player Profile")
            if prof.max_distance:
                print(f"  Max distance: {prof.max_distance} ft")
            ps = player.power_speed(prof)
            if ps is not None:
                print(f"  Estimated arm power: {ps:.1f}")
            print()
        print(f"Goal: {goal}\n")
        if not candidates:
            print("No owned disc qualifies for this role.")
            return 0
        print("Candidate scores\n")
        for s in candidates:
            print(_score_line(s))
        best = candidates[0]
        print(f"\nSelected\n\n  {best.disc.brand} {best.disc.name}")
        if len(candidates) > 1:
            print("\nOther strong candidates")
            for s in candidates[1:4]:
                print(_score_line(s))
        return 0

    # explain build-bag
    decisions = recommend.build_bag_explained(
        inv.list_discs(), situation=args.situation, goal=args.goal,
        rotate=args.rotate, profile=profile, today=today,
        rng=(__import__("random").Random() if args.rotate else None))
    print(f"Goal: {args.goal}")
    if args.situation:
        print(f"Scenario: {args.situation}")
    print()
    for dec in decisions:
        print(dec.role.name)
        if dec.selected is None:
            print("  (no qualifying disc — gap)\n")
            continue
        print(f"  Selected: {dec.selected.brand} {dec.selected.name}")
        top = next((c for c in dec.candidates if c.disc is dec.selected), dec.candidates[0])
        print(f"  Score: {top.total}  ({dec.role.covered_reason})")
        if dec.rotated:
            names = ", ".join(c.disc.name for c in dec.candidates
                              if c.disc in dec.comparable)
            print(f"  Rotation: chose among comparable candidates ({names})")
        others = [c for c in dec.candidates if c.disc is not dec.selected][:3]
        if others:
            print("  Other strong candidates: " +
                  ", ".join(f"{c.disc.name} {c.total}" for c in others))
        print()
    return 0


def cmd_score(args, inv):
    from discbag import recommend, roles
    prof = player.load_profile()
    profile = None if prof.is_empty() else prof
    today = _now_iso()
    db_discs = db.load_db().get("discs", [])

    pinned = None
    if args.role:
        pinned = next((r for r in roles.ROLES if r.name.lower() == args.role.lower()), None)
        if pinned is None:
            print(f"Unknown role '{args.role}'.")
            return 1

    scores = []
    for name in args.discs:
        disc = _resolve_disc(name, inv, db_discs)
        if disc is None:
            print(f"Couldn't find '{name}' in your bag or the database.")
            return 1
        role = pinned or roles.primary_role(disc)
        scores.append(recommend.score_disc(disc, role, args.goal, profile, today, args.situation))

    scores.sort(key=lambda s: s.internal)
    print(f"Goal: {args.goal}" + (f"   Role: {pinned.name}" if pinned else "") + "\n")
    if args.verbose:
        for s in scores:
            role_note = "" if pinned else f"  (role: {s.role.name})"
            _print_breakdown(s)
            if role_note:
                print(f" {role_note}")
            print()
    else:
        print(f"  {'Disc':<16} {'Score':>4}")
        for s in scores:
            print(_score_line(s))
    return 0


def _print_suggestions(picks):
    if not picks:
        return
    print("  Suggested discs:")
    for pick in picks:
        d = pick.disc
        print(f"    {d.brand} {d.name}  ({flight_str(d)})  {d.stability}")


def cmd_recommend(args, inv):
    from discbag import roles
    prof = player.load_profile()
    profile = None if prof.is_empty() else prof

    preferred_only = getattr(args, "preferred_only", False)
    if preferred_only and not prof.preferred_brands:
        print("No preferred brands set.\n")
        print("Use:")
        print("  discbag profile --brand Gateway --brand Innova")
        return 0

    owned = inv.list_discs()
    data = db.load_db()
    catalog = [Disc.from_db_record(r) for r in data.get("discs", [])]

    if args.next:
        nxt = roles.best_next(owned, catalog, n=args.per_slot, profile=profile,
                              preferred_only=preferred_only)
        if nxt is None:
            print("Your bag already covers every essential role — no purchase needed. Nice bag!")
            return 0
        print("Best Next Purchase\n")
        print(f"  {nxt.coverage.role.name}")
        print(f"  Priority: {nxt.coverage.priority}\n")
        print(f"  Reason:\n    {nxt.reason}\n")
        _print_suggestions(nxt.candidates)
        return 0

    assessment = roles.assess(owned, profile=profile)
    if args.gaps:
        assessment = [c for c in assessment if not c.covered]
        if not assessment:
            print("Your bag covers every role — no gaps. Nice bag!")
            return 0

    for cov in assessment:
        optional = " (optional)" if cov.role.optional else ""
        print(f"{cov.role.name}{optional}")
        if cov.covered:
            print("  Status:   Covered")
            print("  Priority: Satisfied\n")
            print("  Current discs:")
            for d in cov.discs:
                plastic = f" [{d.plastic}]" if getattr(d, "plastic", "") else ""
                print(f"    {d.brand} {d.name}{plastic}")
            print(f"\n  Reason:\n    Provides {cov.reason}.")
        else:
            print("  Status:   Missing")
            print(f"  Priority: {cov.priority}\n")
            reason = cov.priority_reason or cov.reason
            print(f"  Reason:\n    {reason}\n")
            _print_suggestions(roles.suggest(cov.role, owned, catalog, n=args.per_slot,
                                             profile=profile, preferred_only=preferred_only))
        print()
    return 0


def cmd_chart(args, inv):
    from discbag import chart
    print(chart.render(inv.list_discs(), kind=args.type))
    return 0


def _resolve_disc(name, inv, db_discs):
    """Find a disc by name in the bag first, then the database."""
    hits = inv.find_by_name(name)
    if hits:
        return hits[0]
    best, _ = db.find_disc(name, db_discs)
    return Disc.from_db_record(best) if best else None


def _fmt_cell(value):
    if isinstance(value, (int, float)):
        return _num_str(value)
    return str(value)


def _render_table(table):
    label_w = max(len(r.label) for r in table.rows)
    widths = [max(len(h), *(len(_fmt_cell(r.values[i]) or "") for r in table.rows))
              for i, h in enumerate(table.headers)]
    lines = [" " * label_w + "   " +
             "   ".join(h.rjust(widths[i]) for i, h in enumerate(table.headers))]
    for r in table.rows:
        cells = "   ".join(_fmt_cell(r.values[i]).rjust(widths[i])
                           for i in range(len(table.headers)))
        lines.append(r.label.ljust(label_w) + "   " + cells)
    return "\n".join(lines)


def cmd_overlap(args, inv):
    from discbag import analysis, roles
    prof = player.load_profile()
    groups = analysis.overlap(inv.list_discs(), profile=None if prof.is_empty() else prof)
    if not groups:
        print("No significant overlap — your discs each fill a distinct niche.")
        return 0
    print("High overlap (near-duplicate flights):\n")
    for g in groups:
        print(f"  {roles.primary_role(g[0]).name}:")
        for d in g:
            plastic = f" [{d.plastic}]" if getattr(d, "plastic", "") else ""
            print(f"    {d.brand} {d.name}{plastic}  ({flight_str(d)})")
        print()
    return 0


def cmd_maturity(args, inv):
    """Where your collection sits today — Discovery, Developing, or Developed — and
    why, with grounded usage insights and observed preferences. Coaching, not a
    recommendation: it answers 'do I actually need anything?'"""
    from discbag import maturity
    prof = player.load_profile()
    profile = None if prof.is_empty() else prof
    today = datetime.now(timezone.utc).date()
    active = inv.list_discs()
    all_discs = inv.all_discs()

    phase, signals = maturity.assess_phase(active, all_discs, profile, today)
    insights = maturity.usage_insights(active, today)
    prefs = maturity.observed_preferences(active)

    color = _use_color()
    st = _styler(color)
    hue = {"Discovery": "yellow", "Developing": "cyan", "Developed": "green"}.get(phase, "cyan")

    print(st("Collection Maturity", "bold"))
    print(f"  {st(phase, 'bold', hue)}\n")
    print(st("Why:", "bold"))
    for s in signals:
        mark = st("✓", "green") if s.met else st("•", "dim")
        print(f"  {mark} {s.text}")

    tail = {
        "Discovery": "Keep exploring — every new disc still teaches you something.",
        "Developing": "You're close — more reps will tell you which discs you truly trust.",
        "Developed": ("Another disc is unlikely to improve your game right now.\n"
                      "Your biggest gains will come from throwing the discs you already own."),
    }[phase]
    print("\n" + tail)

    if insights:
        print("\n" + st("Usage insights", "bold"))
        for line in insights:
            print(f"  {line}")
    if prefs:
        print("\n" + st("Observed preferences", "bold"))
        for line in prefs:
            print(f"  {line}")
    return 0


def _ownership_footer(discs):
    """A light line of real usage/favorite data — only for a genuine multi-disc
    comparison where every disc is owned and at least one has rounds thrown. A
    database-only disc has no usage; a disc with zero rounds has nothing to report."""
    if len(discs) < 2:
        return None
    if any(getattr(d, "user", None) is None for d in discs):
        return None
    if not any(d.user.round_count > 0 for d in discs):
        return None

    def rounds(n):
        return f"{n} round" if n == 1 else f"{n} rounds"

    parts = [f"the {d.name} {rounds(d.user.round_count)}" for d in discs]
    line = "You've thrown " + roles.english_list(parts) + "."
    favs = [d.name for d in discs if d.user.favorite]
    if favs:
        names = roles.english_list([f"the {n}" for n in favs])
        verb = "is a favorite" if len(favs) == 1 else "are favorites"
        line += f" {names[0].upper() + names[1:]} {verb}."
    return line


def cmd_compare(args, inv):
    from discbag import analysis
    db_discs = db.load_db().get("discs", [])
    discs = []
    for name in args.discs:
        d = _resolve_disc(name, inv, db_discs)
        if d is None:
            print(f"Couldn't find '{name}' in your bag or the database.")
            return 1
        discs.append(d)
    print(_render_table(analysis.compare(discs)))
    verdict = analysis.compare_verdict(discs)
    if verdict:
        print()
        print(verdict)
    footer = _ownership_footer(discs)
    if footer:
        print()
        print(footer)
    return 0


def cmd_choose(args, inv):
    from discbag import analysis
    prof = player.load_profile()
    picks = analysis.choose(inv.list_discs(), distance=args.distance,
                            wind=args.wind, shape=args.shape,
                            profile=None if prof.is_empty() else prof)
    if not picks:
        print("Your bag is empty — add discs first with: discbag add <name>")
        return 0
    parts = []
    if args.distance:
        parts.append(f"{args.distance} ft")
    if args.shape:
        parts.append(args.shape)
    if args.wind:
        parts.append(f"{args.wind} wind")
    print(f"For {', '.join(parts) or 'this shot'}:\n")
    print("Recommended")
    for p in picks[:2]:
        d = p.disc
        print(f"  ✓ {d.brand} {d.name}  ({flight_str(d)})")
    if len(picks) > 2:
        print("\nAlternative")
        for p in picks[2:4]:
            d = p.disc
            print(f"    {d.brand} {d.name}  ({flight_str(d)})")
    return 0


def cmd_practice(args, inv):
    from discbag import analysis
    prof = player.load_profile()
    picks = analysis.practice(inv.list_discs(), count=args.count,
                              profile=None if prof.is_empty() else prof)
    if not picks:
        print("Your bag is empty — add discs first with: discbag add <name>")
        return 0
    print("Today's Practice Recommendation\n")
    for d in picks:
        print(f"  {d.brand} {d.name}  ({flight_str(d)})")
    print("\nReason:\n  Straight, neutral discs expose form issues and reward clean releases.")
    return 0


def cmd_profile(args, inv):
    prof = player.load_profile()
    fieldmap = [
        ("name", args.name),
        ("experience", args.experience), ("hand", args.hand),
        ("putt_hand", args.putt_hand), ("style", args.style),
        ("typical_distance", args.typical), ("max_distance", args.max),
        ("fairway_speed", args.fairway_speed), ("driver_speed", args.driver_speed),
        ("release_speed", args.release_speed), ("spin_rate", args.spin),
    ]
    changed = False
    for name, value in fieldmap:
        if value is not None:
            setattr(prof, name, value)
            changed = True
    if args.clear_brands:
        prof.preferred_brands = []
        changed = True
    elif args.brand:
        prof.preferred_brands = args.brand
        changed = True
    if changed:
        player.save_profile(prof)
        print("Player profile updated.\n")

    if prof.is_empty():
        print("No player profile set yet. Set one with, e.g.:")
        print("  discbag profile --typical 250 --max 275 --experience intermediate --hand right")
        return 0

    print(format_profile(prof))
    return 0


def _cap(value):
    return value.capitalize() if value else ""


def format_profile(prof):
    """Render the player profile as a sectioned dashboard with units."""
    def ft(v):
        return f"{v} ft" if v else ""

    def rpm(v):
        return f"{_num_str(v)} rpm" if v else ""

    def mph(v):
        return f"{_num_str(v)} mph" if v else ""

    def spd(v):
        return _num_str(v) if v else ""

    sections = [
        ("Experience", [("Experience", _cap(prof.experience))]),
        ("Throwing", [
            ("Throwing hand", _cap(prof.hand)),
            ("Putting hand", _cap(prof.putt_hand)
             or (f"{_cap(prof.hand)} (same as throwing)" if prof.hand else "")),
            ("Style", _cap(prof.style)),
        ]),
        ("Performance", [
            ("Typical distance", ft(prof.typical_distance)),
            ("Max distance", ft(prof.max_distance)),
            ("Comfortable fairway speed", spd(prof.fairway_speed)),
            ("Comfortable driver speed", spd(prof.driver_speed)),
            ("Release speed", mph(prof.release_speed)),
            ("Spin rate", rpm(prof.spin_rate)),
        ]),
        ("Preferences", [
            ("Preferred brands", ", ".join(prof.preferred_brands)),
        ]),
    ]

    zones = player.comfort_zones(prof)
    if zones:
        sections.append(("Comfort Zone", [
            ("Comfortable speeds", f"{zones['comfortable'][0]}-{zones['comfortable'][1]}"),
            ("Developing", f"{zones['developing'][0]}-{zones['developing'][1]}"),
            ("Future", f"{zones['future']}+"),
        ]))

    # Drop empty rows and empty sections, then align labels across everything shown.
    shown = [(title, [(l, v) for l, v in rows if v]) for title, rows in sections]
    shown = [(title, rows) for title, rows in shown if rows]
    width = max((len(l) for _, rows in shown for l, _ in rows), default=0) + 1

    lines = ["Player Profile", ""]
    for title, rows in shown:
        lines.append(title)
        lines.append("-" * len(title))
        for label, value in rows:
            lines.append(f"{(label + ':'):<{width}} {value}")
        lines.append("")

    ps = player.power_speed(prof)
    if ps is not None:
        lines.append("Estimated Arm Power")
        lines.append("-" * len("Estimated Arm Power"))
        lines.append(f"Speed ~{ps:.1f}")
        lines.append("")
        lines.append("Recommendations automatically adapt as your distance and "
                     "throwing ability improve.")

    return "\n".join(lines).rstrip()


# ---------- home screen ----------

_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "cyan": "\033[36m", "bcyan": "\033[96m", "green": "\033[32m",
    "yellow": "\033[33m", "magenta": "\033[95m", "white": "\033[97m",
    "purple": "\033[38;5;183m",
}


def _styler(enabled):
    """Return a `style(text, *codes)` function; a no-op when styling is disabled,
    so piped/redirected output and tests stay plain and parseable."""
    def style(text, *codes):
        if not enabled or not codes:
            return text
        return "".join(_ANSI[c] for c in codes) + text + _ANSI["reset"]
    return style


def _use_color():
    """Colorize only for an interactive terminal that hasn't opted out via NO_COLOR."""
    import os
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _relative_day(when, today=None):
    """A timestamp as 'Today' / 'Yesterday' / 'N days ago', or 'never' if unset."""
    if not when:
        return "never"
    return humanize_age(when, now_iso=today).capitalize()


# (emoji, ANSI colour) per section — used only when colour is on.
_SECTION_STYLE = {
    "Inventory": ("🥏", "cyan"),
    "Player": ("🎯", "purple"),
    "Recent Activity": ("📅", "yellow"),
    "Suggestions": ("💡", "green"),
    "Get started": ("👋", "green"),
    "Quick Commands": ("⚡", "cyan"),
}


def render_dashboard(inv, prof, today=None, color=False):
    """The application home screen: a concise, glanceable summary of the bag,
    the player, recent activity, and lightweight suggestions from the engine.

    `color` adds ANSI styling and decorations; when off, the output is plain text.
    """
    from discbag import analysis, roles  # local import keeps startup light

    st = _styler(color)
    active = inv.list_discs()
    lines = []

    def header(name):
        if color:
            icon, hue = _SECTION_STYLE.get(name, ("•", "cyan"))
            lines.append(f"{icon} {st(name, 'bold', hue)}")
        else:
            lines.append(name)

    def row(label, value, pad=14, value_codes=("white",)):
        lines.append(f"  {label:<{pad}} {st(str(value), *value_codes)}")

    title = f"{prof.name}'s Disc Bag" if getattr(prof, "name", "") else "Your Disc Bag"
    width = max(len(title) + 4, 40)
    if color:
        rule = st("━" * width, "cyan", "dim")
        lines += [rule, st(f"🥏 {title}", "bold", "bcyan"), rule, ""]
    else:
        lines += [title, "─" * max(len(title), 36), ""]

    header("Inventory")
    row("Active discs", len(active), value_codes=("bold", "bcyan"))
    row("In bag", len(inv.filter(in_bag=True)))
    row("Favorites", len(inv.filter(favorite=True)))
    lines.append("")

    header("Player")
    if prof.is_empty():
        lines.append("  " + st("No profile yet", "dim")
                     + " — set one with: discbag profile --max 300 --hand right")
    else:
        if prof.max_distance:
            row("Max distance", f"{prof.max_distance} ft")
        ps = player.power_speed(prof)
        if ps is not None:
            row("Arm power", f"Speed ~{ps:.1f}", value_codes=("bold", "bcyan"))
        if prof.hand:
            row("Throw hand", _cap(prof.hand))
        putt = _cap(prof.putt_hand) or (f"{_cap(prof.hand)} (same as throwing)" if prof.hand else "")
        if putt:
            row("Putt hand", putt)
    lines.append("")

    # Recent activity — the latest round/practice across every disc ever owned.
    everything = inv.all_discs()
    last_round = max((d.user.last_round for d in everything if d.user.last_round), default=None)
    last_practice = max((d.user.last_practice for d in everything if d.user.last_practice),
                        default=None)
    if last_round or last_practice:
        header("Recent Activity")
        row("Last round", _relative_day(last_round, today))
        row("Last practice", _relative_day(last_practice, today))
        lines.append("")

    profile = None if prof.is_empty() else prof
    if active:
        prac = analysis.practice(active, count=3, profile=profile)
        gaps = [c.role.name for c in roles.assess(active, profile=profile) if not c.covered]
        neglected = _neglected(active)
        rows = []
        if prac:
            rows.append(("Practice", ", ".join(d.name for d in prac), "green"))
        if gaps:
            rows.append(("Missing roles", ", ".join(gaps[:3]), "yellow"))
        if neglected:
            rows.append(("Neglected", ", ".join(d.name for d in neglected[:3]), "dim"))
        if rows:
            header("Suggestions")
            for label, value, hue in rows:
                row(label, value, value_codes=(hue,))
            lines.append("")
    else:
        header("Get started")
        lines.append("  Your bag is empty — add a disc with: discbag add <name>")
        lines.append("")

    header("Quick Commands")
    for cmd in ("discbag build-bag", "discbag choose --distance 300",
                "discbag practice", "discbag usage", "discbag list"):
        lines.append("  " + st(cmd, "dim"))
    lines += ["", st("Run 'discbag --help' for the full command reference.", "dim")]
    return "\n".join(lines)


def cmd_dashboard(args, inv):
    print(render_dashboard(inv, player.load_profile(), color=_use_color()))
    return 0


def cmd_flight(args, inv):
    targets = _resolve(inv, args.disc)
    if targets is None:
        return 1
    disc = targets[0]
    if args.clear:
        inv.set_personal_flight(disc, None)
        print(f"Cleared personal flight for {disc.name}.")
        return 0

    numbers = parse_flight(args.numbers)
    if numbers is None:
        print("Flight numbers must look like 6/5/-1/2 (speed/glide/turn/fade).", file=sys.stderr)
        return 1
    if args.distance is not None:
        numbers["avg_distance"] = args.distance
    if args.confidence is not None:
        numbers["confidence"] = args.confidence
    inv.set_personal_flight(disc, numbers)
    print(f"Recorded personal flight for {disc.name}. "
          "Recommendations will now use your numbers for this disc.")
    return 0


# ---------- argument parsing ----------

_HELP_GROUPS = [
    ("Common Commands", [
        ("add", "add a disc to your bag"),
        ("list", "list the discs in your bag"),
        ("show", "full details for a disc"),
        ("build-bag", "recommend a bag by role"),
        ("recommend", "role coverage + what to buy next"),
        ("profile", "show or set your player profile"),
    ]),
    ("Organization", [
        ("bag", "manage which discs you currently carry"),
        ("remove", "archive a disc (keeps its history)"),
        ("lost", "mark a disc lost"),
        ("damaged", "flag a disc damaged (--retire to archive)"),
        ("replace", "archive a disc, add a fresh copy"),
        ("restore", "return an archived disc to the bag"),
        ("delete", "permanently erase a disc"),
        ("history", "a disc's full story, even once gone"),
        ("favorite", "mark a disc as a favorite"),
        ("tag / untag", "add or remove a tag"),
        ("role", "set a personal role label"),
        ("edit", "correct a disc's metadata (no history event)"),
    ]),
    ("Analysis", [
        ("round-used / used", "record a round"),
        ("practice-used", "record a practice session"),
        ("usage", "use stats (per disc or overall)"),
        ("practice", "form-focused practice discs"),
        ("choose", "which disc to throw for a shot"),
        ("overlap", "find near-duplicate discs"),
        ("compare", "side-by-side flight/role table"),
        ("chart", "terminal flight visualizations"),
        ("flight", "record how a disc flies for you"),
        ("maturity", "is your collection still growing, or settled?"),
    ]),
    ("Advanced", [
        ("explain", "why the engine chose what it did"),
        ("score", "component breakdown of a disc's score"),
        ("sync", "refresh cached manufacturer data"),
        ("updatedb", "refresh the disc database"),
        ("db-info", "database size and age"),
    ]),
]


class _GroupedHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Keeps the epilog's literal formatting and suppresses argparse's default flat
    list of subcommands — the epilog documents them, grouped by purpose, instead."""

    def _format_action(self, action):
        if isinstance(action, argparse._SubParsersAction):
            return ""
        return super()._format_action(action)


def _help_epilog():
    width = max(len(name) for _, cmds in _HELP_GROUPS for name, _ in cmds) + 2
    lines = ["commands:"]
    for title, cmds in _HELP_GROUPS:
        lines.append("")
        lines.append(f"  {title}")
        for name, desc in cmds:
            lines.append(f"    {name:<{width}} {desc}")
    lines.append("")
    lines.append("Run 'discbag <command> --help' for details on any command.")
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="discbag", description="A disc golf bag intelligence engine.",
        epilog=_help_epilog(), formatter_class=_GroupedHelpFormatter)
    parser.add_argument("--updatedb", action="store_true",
                        help="refresh the disc database from the online source, then exit")
    # metavar hides argparse's alphabetical brace-dump; the grouped epilog documents commands.
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_add = sub.add_parser("add", help="add a disc to your bag (looks up stats)")
    p_add.add_argument("query", nargs="+", help="disc name, e.g. 'Gateway Wizard SS Chalky'")
    p_add.add_argument("--plastic", help="plastic/run, stored as metadata")
    p_add.add_argument("--weight", type=int, help="weight in grams")
    p_add.add_argument("--color")
    p_add.add_argument("--condition", help="e.g. New, Used, Beat-in")
    p_add.add_argument("--location", help="where you bought it")
    p_add.add_argument("--notes")
    p_add.add_argument("--yes", action="store_true", help="accept the best match without prompting")
    p_add.set_defaults(func=cmd_add)

    _ARCHIVE_STATUSES = ["retired", "lost", "sold", "gifted", "broken"]

    p_rm = sub.add_parser("remove", help="archive a disc (keeps its history; use `delete` to erase)")
    p_rm.add_argument("name", nargs="+")
    p_rm.add_argument("--status", choices=_ARCHIVE_STATUSES,
                      help="why it left the bag (default: retired)")
    p_rm.add_argument("--reason", help="a note, e.g. \"Lost at Woodland Park hole 18\"")
    p_rm.set_defaults(func=cmd_remove)

    p_del = sub.add_parser("delete", help="permanently erase a disc and all its history")
    p_del.add_argument("name", nargs="+")
    p_del.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p_del.set_defaults(func=cmd_delete)

    p_restore = sub.add_parser("restore", help="return an archived disc to the active bag")
    p_restore.add_argument("name", nargs="+")
    p_restore.set_defaults(func=cmd_restore)

    p_lost = sub.add_parser("lost", help="mark a disc lost (archives it, keeps its history)")
    p_lost.add_argument("name", nargs="+")
    p_lost.add_argument("--reason", help="a note, e.g. \"hole 7 water\"")
    p_lost.set_defaults(func=cmd_lost)

    p_dmg = sub.add_parser("damaged",
                           help="flag a disc as damaged (still carried; --retire to archive)")
    p_dmg.add_argument("name", nargs="+")
    p_dmg.add_argument("--reason", help="a note, e.g. \"cracked rim\"")
    grp = p_dmg.add_mutually_exclusive_group()
    grp.add_argument("--retire", action="store_true",
                     help="worn beyond use: archive it as broken")
    grp.add_argument("--unset", action="store_true",
                     help="clear the damaged flag (mistake fix; discs aren't repaired)")
    p_dmg.set_defaults(func=cmd_damaged)

    p_repl = sub.add_parser("replace",
                            help="archive a disc and add a fresh copy with a clean history")
    p_repl.add_argument("name", nargs="+")
    p_repl.add_argument("--status", choices=_ARCHIVE_STATUSES,
                        help="how the old copy left the bag (default: retired)")
    p_repl.add_argument("--reason", help="a note about the old copy")
    p_repl.add_argument("--plastic", help="override the new copy's plastic")
    p_repl.add_argument("--weight", type=int, help="override the new copy's weight (grams)")
    p_repl.add_argument("--color", help="override the new copy's color")
    p_repl.set_defaults(func=cmd_replace)

    p_edit = sub.add_parser("edit",
                            help="correct a disc's inventory metadata (no history event)")
    p_edit.add_argument("name", nargs="*", help="disc name (omit if using --id)")
    p_edit.add_argument("--id", dest="id",
                        help="target one copy by id (discover ids with 'list --ids')")
    p_edit.add_argument("--manufacturer", help="correct the manufacturer/brand")
    p_edit.add_argument("--mold", help="correct the mold name")
    p_edit.add_argument("--plastic")
    p_edit.add_argument("--weight", type=int)
    p_edit.add_argument("--color")
    p_edit.add_argument("--condition", help="e.g. New, Used, Beat-in")
    p_edit.add_argument("--notes")
    p_edit.set_defaults(func=cmd_edit)

    p_hist = sub.add_parser("history", help="a disc's full story, even after it leaves the bag")
    p_hist.add_argument("name", nargs="+")
    p_hist.set_defaults(func=cmd_history)

    p_list = sub.add_parser("list", help="list discs in your bag")
    p_list.add_argument("--tag", help="only discs with this tag")
    p_list.add_argument("--favorite", action="store_true", help="only favorites")
    p_list.add_argument("--in-bag", dest="in_bag", action="store_true",
                        help="only discs currently in the bag")
    p_list.add_argument("--status", choices=["active"] + _ARCHIVE_STATUSES,
                        help="only discs with this lifecycle status")
    p_list.add_argument("--all", action="store_true",
                        help="include archived discs (lost, sold, retired, …)")
    p_list.add_argument("--ids", action="store_true",
                        help="show each disc's internal id (for 'edit --id')")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show details for a disc in your bag")
    p_show.add_argument("name", nargs="+")
    p_show.set_defaults(func=cmd_show)

    p_tag = sub.add_parser("tag", help="add a tag to a disc")
    p_tag.add_argument("disc")
    p_tag.add_argument("tag")
    p_tag.add_argument("--all", action="store_true", help="apply to every copy of the mold")
    p_tag.set_defaults(func=cmd_tag)

    p_untag = sub.add_parser("untag", help="remove a tag from a disc")
    p_untag.add_argument("disc")
    p_untag.add_argument("tag")
    p_untag.add_argument("--all", action="store_true", help="apply to every copy of the mold")
    p_untag.set_defaults(func=cmd_untag)

    p_role = sub.add_parser("role", help="set a personal role for a disc")
    p_role.add_argument("disc")
    p_role.add_argument("role", nargs="+", help="e.g. \"hyzer flip\"")
    p_role.set_defaults(func=cmd_role)

    p_fav = sub.add_parser("favorite", help="mark a disc as a favorite")
    p_fav.add_argument("disc")
    p_fav.add_argument("--unset", action="store_true", help="remove favorite status")
    p_fav.add_argument("--all", action="store_true", help="apply to every copy of the mold")
    p_fav.set_defaults(func=cmd_favorite)

    p_bagcmd = sub.add_parser("bag", help="manage which owned discs are currently carried")
    p_bagcmd.add_argument("action", choices=["add", "remove", "list"])
    p_bagcmd.add_argument("name", nargs="*")
    p_bagcmd.set_defaults(func=cmd_bag)

    # round-used / used record a round; practice-used records a practice session.
    # use_count increments the same either way — only the session context differs.
    for cmd_name, session_type, cmd_help in [
            ("round-used", "round", "record the discs you played in a round (today, or --date)"),
            ("practice-used", "practice",
             "record the discs you used in a practice session (backyard, field, putting, net)"),
            ("used", "round", "alias of round-used")]:
        p_used = sub.add_parser(cmd_name, help=cmd_help)
        p_used.add_argument("discs", nargs="+")
        p_used.add_argument("--date", help="record for a specific date (YYYY-MM-DD)")
        p_used.set_defaults(func=cmd_used, session_type=session_type)

    p_usage = sub.add_parser("usage", help="show disc use stats (per disc or overall)")
    p_usage.add_argument("disc", nargs="?", help="a disc to show; omit for overall stats")
    p_usage.set_defaults(func=cmd_usage)

    sub.add_parser("updatedb", help="refresh the disc database").set_defaults(func=cmd_updatedb)
    sub.add_parser("db-info", help="show database size and age").set_defaults(func=cmd_dbinfo)
    p_sync = sub.add_parser("sync",
                            help="refresh your discs' cached manufacturer data from the database")
    p_sync.add_argument("disc", nargs="?", help="a disc to refresh; omit to refresh the whole bag")
    p_sync.add_argument("--all", action="store_true", help="refresh every copy of the mold")
    p_sync.set_defaults(func=cmd_sync)

    p_bag = sub.add_parser("build-bag", help="recommend a bag by role from your inventory")
    p_bag.add_argument("--size", "-n", type=int, help="limit to this many discs")
    p_bag.add_argument("--goal",
                       choices=["coverage", "development", "confidence", "tournament", "fun"],
                       default="coverage",
                       help="what to optimize the bag for (default: coverage)")
    p_bag.add_argument("--rotate", action="store_true",
                       help="vary among comparable discs instead of always the top pick")
    p_bag.add_argument("--situation", choices=["windy", "rain", "woods", "minimal", "travel"],
                       help="environmental modifier: which conditions to build for")
    for situ in ("windy", "rain", "woods", "minimal", "travel"):
        p_bag.add_argument(f"--{situ}", dest="situation", action="store_const", const=situ,
                           help=f"shortcut for --situation {situ}")
    p_bag.set_defaults(func=cmd_build_bag, situation=None)

    _GOALS = ["coverage", "development", "confidence", "tournament", "fun"]
    _SITUATIONS = ["windy", "rain", "woods", "minimal", "travel"]

    p_explain = sub.add_parser("explain",
                               help="explain the engine's reasoning (developer/tuning tool)")
    p_explain.add_argument("what", choices=["build-bag", "role"])
    p_explain.add_argument("rest", nargs="*", help="for 'role': the role name")
    p_explain.add_argument("--goal", choices=_GOALS, default="coverage")
    p_explain.add_argument("--rotate", action="store_true")
    p_explain.add_argument("--situation", choices=_SITUATIONS)
    for situ in _SITUATIONS:
        p_explain.add_argument(f"--{situ}", dest="situation", action="store_const", const=situ)
    p_explain.set_defaults(func=cmd_explain, situation=None)

    p_score = sub.add_parser("score", help="score and compare discs for a goal (developer tool)")
    p_score.add_argument("discs", nargs="+")
    p_score.add_argument("--goal", choices=_GOALS, default="coverage")
    p_score.add_argument("--role", help="score all discs against this role (default: each disc's own)")
    p_score.add_argument("--situation", choices=_SITUATIONS)
    p_score.add_argument("--verbose", "-v", action="store_true", help="show the score breakdown")
    p_score.set_defaults(func=cmd_score, situation=None)

    p_rec = sub.add_parser("recommend",
                           help="assess bag coverage; suggest discs for missing roles")
    p_rec.add_argument("--per-slot", type=int, default=3,
                       help="how many suggestions per missing slot (default 3)")
    p_rec.add_argument("--gaps", action="store_true",
                       help="only show missing roles")
    p_rec.add_argument("--next", action="store_true",
                       help="recommend a single highest-priority purchase")
    p_rec.add_argument("--preferred-only", dest="preferred_only", action="store_true",
                       help="only suggest discs from your preferred brands")
    p_rec.set_defaults(func=cmd_recommend)

    p_chart = sub.add_parser("chart", help="ASCII visualizations of your bag")
    p_chart.add_argument("--type",
                         choices=["flight", "grid", "stability", "speed", "composition", "brands"],
                         default="flight",
                         help="which chart to draw (default: flight, a Braille scatter; "
                              "'grid' is the letter chart)")
    p_chart.set_defaults(func=cmd_chart)

    sub.add_parser("overlap", help="find near-duplicate discs in your bag"
                   ).set_defaults(func=cmd_overlap)

    p_cmp = sub.add_parser("compare", help="compare discs side by side (bag or database)")
    p_cmp.add_argument("discs", nargs="+")
    p_cmp.set_defaults(func=cmd_compare)

    p_choose = sub.add_parser("choose", help="pick the best disc from your bag for a shot")
    p_choose.add_argument("--distance", type=int, help="shot distance in feet")
    p_choose.add_argument("--wind", choices=["head", "tail", "none"], help="wind direction")
    p_choose.add_argument("--shape", choices=["straight", "hyzer", "anhyzer", "turnover"],
                          help="desired shot shape")
    p_choose.set_defaults(func=cmd_choose)

    p_prac = sub.add_parser("practice", help="discs to throw for a form-focused practice session")
    p_prac.add_argument("--count", type=int, default=3, help="how many discs (default 3)")
    p_prac.set_defaults(func=cmd_practice)

    p_prof = sub.add_parser("profile", help="show or set your player profile")
    p_prof.add_argument("--name", help="your name, shown on the dashboard home screen")
    p_prof.add_argument("--experience", choices=["beginner", "intermediate", "advanced", "elite"])
    p_prof.add_argument("--hand", choices=["right", "left"], help="dominant throwing hand")
    p_prof.add_argument("--putt-hand", "--putt", dest="putt_hand", choices=["right", "left"],
                        help="putting hand, if you putt with the other hand")
    p_prof.add_argument("--style", choices=["backhand", "forehand", "both"])
    p_prof.add_argument("--typical", type=int, help="typical golf distance (ft)")
    p_prof.add_argument("--max", type=int, help="max controlled distance (ft)")
    p_prof.add_argument("--fairway-speed", dest="fairway_speed", type=float)
    p_prof.add_argument("--driver-speed", dest="driver_speed", type=float)
    p_prof.add_argument("--release-speed", dest="release_speed", type=float)
    p_prof.add_argument("--spin", type=float, help="typical spin rate (rpm)")
    p_prof.add_argument("--brand", action="append", help="a preferred brand (repeatable)")
    p_prof.add_argument("--clear-brands", action="store_true", help="clear preferred brands")
    p_prof.set_defaults(func=cmd_profile)

    p_flight = sub.add_parser("flight", help="record how a disc actually flies for you")
    p_flight.add_argument("disc")
    p_flight.add_argument("numbers", nargs="?", help="speed/glide/turn/fade, e.g. 6/5/-1/2")
    p_flight.add_argument("--distance", type=int, help="your average distance in feet")
    p_flight.add_argument("--confidence", type=int, choices=range(1, 6),
                          help="how sure you are, 1-5")
    p_flight.add_argument("--clear", action="store_true", help="remove personal flight numbers")
    p_flight.set_defaults(func=cmd_flight)

    sub.add_parser("maturity",
                   help="where your collection sits today, and why").set_defaults(func=cmd_maturity)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    inv = Inventory()

    if args.updatedb:
        return cmd_updatedb(args, inv)
    if not getattr(args, "command", None):
        # The bare command is the application home screen, not the reference manual.
        return cmd_dashboard(args, inv)
    return args.func(args, inv)


if __name__ == "__main__":
    sys.exit(main())
