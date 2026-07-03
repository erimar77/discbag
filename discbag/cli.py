"""Command-line interface for discbag."""

import argparse
import sys
from datetime import datetime, timezone

from discbag import db, player
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
    out = " (out of bag)" if u and not u.in_bag else ""
    print(f"  {disc.brand} {disc.name}{plastic}{star}{out}".rstrip())
    role = f"  ·  {u.role}" if u and u.role else ""
    tags = f"  #{' #'.join(u.tags)}" if u and u.tags else ""
    print(f"      {flight_str(disc)}   {disc.category}  ({disc.stability}){role}{tags}".rstrip())


def _stability_word(stab):
    if stab <= -2:
        return "very understable"
    if stab <= -0.5:
        return "understable"
    if stab < 1.5:
        return "neutral"
    if stab < 3:
        return "overstable"
    return "very overstable"


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
        ("Bought at", u.purchase_location),
        ("Added", u.date_added),
        ("Throws", u.throw_count or ""),
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
        word = _stability_word(f.turn + f.fade)
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


def cmd_remove(args, inv):
    name = " ".join(args.name).strip()
    n = inv.remove(name)
    print(f"Removed {n} disc(s) matching '{name}'." if n else f"No disc named '{name}' in your bag.")
    return 0 if n else 1


def cmd_list(args, inv):
    filters = {}
    if getattr(args, "tag", None):
        filters["tag"] = args.tag
    if getattr(args, "favorite", False):
        filters["favorite"] = True
    if getattr(args, "in_bag", False):
        filters["in_bag"] = True
    discs = inv.filter(**filters) if filters else inv.list_discs()
    discs = sorted(discs, key=lambda d: float(d.speed))
    if not discs:
        where = " matching that filter" if filters else ""
        print(f"No discs{where}." if filters else
              "Your bag is empty. Add discs with: discbag add <name>")
        return 0
    label = "matching" if filters else "discs"
    print(f"Your bag ({len(discs)} {label}):\n")
    for d in discs:
        _print_disc_row(d)
    return 0


def cmd_show(args, inv):
    name = " ".join(args.name).strip().lower()
    matches = [d for d in inv.list_discs() if name in d.name.lower()]
    if not matches:
        print(f"No disc matching '{name}' in your bag.")
        return 1
    prof = player.load_profile()
    for d in matches:
        print(format_owned(d, profile=prof))
        print()
    return 0


def cmd_sync(args, inv):
    data = db.load_db()
    n = inv.refresh_manufacturer(data.get("discs", []))
    print(f"Refreshed manufacturer data for {n} disc(s) from the database. "
          "Your personal data was left untouched.")
    return 0


def _not_found(name):
    print(f"No disc named '{name}' in your bag.")
    return 1


def cmd_tag(args, inv):
    name, tag = args.disc, args.tag
    n = inv.add_tag(name, tag)
    if not n:
        return _not_found(name)
    print(f"Tagged {n} {name} disc(s) with '{tag}'.")
    return 0


def cmd_untag(args, inv):
    name, tag = args.disc, args.tag
    n = inv.remove_tag(name, tag)
    if not n:
        return _not_found(name)
    print(f"Removed tag '{tag}' from {n} {name} disc(s).")
    return 0


def cmd_role(args, inv):
    name, role = args.disc, " ".join(args.role)
    n = inv.set_role(name, role)
    if not n:
        return _not_found(name)
    print(f"Set role of {n} {name} disc(s) to '{role}'.")
    return 0


def cmd_favorite(args, inv):
    name = args.disc
    value = not args.unset
    n = inv.set_favorite(name, value)
    if not n:
        return _not_found(name)
    print(f"{'Marked' if value else 'Unmarked'} {n} {name} disc(s) "
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


def cmd_build_bag(args, inv):
    from discbag import recommend  # local import keeps startup light
    discs = inv.list_discs()
    result = recommend.build_bag(discs, size=args.size, situation=args.situation)

    if not discs:
        print("Your bag is empty — add discs first with: discbag add <name>")
    situ = f" for {args.situation}" if args.situation else ""
    print(f"Recommended bag{situ} (by role):\n")
    for fit in result.filled:
        d = fit.disc
        plastic = f" [{d.plastic}]" if getattr(d, "plastic", "") else ""
        print(f"  {fit.role.name:<22} {d.brand} {d.name}{plastic}  ({flight_str(d)})")

    if result.gaps:
        print("\nRoles to fill:")
        for role in result.gaps:
            print(f"  {role.name:<22} {role.use}")
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
    owned = inv.list_discs()
    prof = player.load_profile()
    profile = None if prof.is_empty() else prof
    data = db.load_db()
    catalog = [Disc.from_db_record(r) for r in data.get("discs", [])]

    if args.next:
        nxt = roles.best_next(owned, catalog, n=args.per_slot, profile=profile)
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
            _print_suggestions(roles.suggest(cov.role, owned, catalog, n=args.per_slot))
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
        lines.append(f"~Speed {ps:.1f}")
        lines.append("")
        lines.append("Recommendations automatically adapt as your distance and "
                     "throwing ability improve.")

    return "\n".join(lines).rstrip()


def cmd_flight(args, inv):
    name = args.disc
    if args.clear:
        n = inv.set_personal_flight(name, None)
        return _not_found(name) if not n else (print(f"Cleared personal flight for {n} {name} disc(s).") or 0)

    numbers = parse_flight(args.numbers)
    if numbers is None:
        print("Flight numbers must look like 6/5/-1/2 (speed/glide/turn/fade).", file=sys.stderr)
        return 1
    if args.distance is not None:
        numbers["avg_distance"] = args.distance
    if args.confidence is not None:
        numbers["confidence"] = args.confidence
    n = inv.set_personal_flight(name, numbers)
    if not n:
        return _not_found(name)
    print(f"Recorded personal flight for {n} {name} disc(s). "
          "Recommendations will now use your numbers for this disc.")
    return 0


# ---------- argument parsing ----------

def build_parser():
    parser = argparse.ArgumentParser(prog="discbag", description="Manage your disc golf bag.")
    parser.add_argument("--updatedb", action="store_true",
                        help="refresh the disc database from the online source, then exit")
    sub = parser.add_subparsers(dest="command")

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

    p_rm = sub.add_parser("remove", help="remove a disc from your bag")
    p_rm.add_argument("name", nargs="+")
    p_rm.set_defaults(func=cmd_remove)

    p_list = sub.add_parser("list", help="list discs in your bag")
    p_list.add_argument("--tag", help="only discs with this tag")
    p_list.add_argument("--favorite", action="store_true", help="only favorites")
    p_list.add_argument("--in-bag", dest="in_bag", action="store_true",
                        help="only discs currently in the bag")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show details for a disc in your bag")
    p_show.add_argument("name", nargs="+")
    p_show.set_defaults(func=cmd_show)

    p_tag = sub.add_parser("tag", help="add a tag to a disc")
    p_tag.add_argument("disc")
    p_tag.add_argument("tag")
    p_tag.set_defaults(func=cmd_tag)

    p_untag = sub.add_parser("untag", help="remove a tag from a disc")
    p_untag.add_argument("disc")
    p_untag.add_argument("tag")
    p_untag.set_defaults(func=cmd_untag)

    p_role = sub.add_parser("role", help="set a personal role for a disc")
    p_role.add_argument("disc")
    p_role.add_argument("role", nargs="+", help="e.g. \"hyzer flip\"")
    p_role.set_defaults(func=cmd_role)

    p_fav = sub.add_parser("favorite", help="mark a disc as a favorite")
    p_fav.add_argument("disc")
    p_fav.add_argument("--unset", action="store_true", help="remove favorite status")
    p_fav.set_defaults(func=cmd_favorite)

    p_bagcmd = sub.add_parser("bag", help="manage which owned discs are currently carried")
    p_bagcmd.add_argument("action", choices=["add", "remove", "list"])
    p_bagcmd.add_argument("name", nargs="*")
    p_bagcmd.set_defaults(func=cmd_bag)

    sub.add_parser("updatedb", help="refresh the disc database").set_defaults(func=cmd_updatedb)
    sub.add_parser("db-info", help="show database size and age").set_defaults(func=cmd_dbinfo)
    sub.add_parser("sync", help="refresh your discs' cached manufacturer data from the database"
                   ).set_defaults(func=cmd_sync)

    p_bag = sub.add_parser("build-bag", help="recommend a bag by role from your inventory")
    p_bag.add_argument("--size", "-n", type=int, help="limit to this many discs")
    p_bag.add_argument("--situation", choices=["windy", "rain", "woods", "minimal", "travel"],
                       help="build a bag focused on a situation")
    for situ in ("windy", "rain", "woods", "minimal", "travel"):
        p_bag.add_argument(f"--{situ}", dest="situation", action="store_const", const=situ,
                           help=f"shortcut for --situation {situ}")
    p_bag.set_defaults(func=cmd_build_bag, situation=None)

    p_rec = sub.add_parser("recommend",
                           help="assess bag coverage; suggest discs for missing roles")
    p_rec.add_argument("--per-slot", type=int, default=3,
                       help="how many suggestions per missing slot (default 3)")
    p_rec.add_argument("--gaps", action="store_true",
                       help="only show missing roles")
    p_rec.add_argument("--next", action="store_true",
                       help="recommend a single highest-priority purchase")
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

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    inv = Inventory()

    if args.updatedb:
        return cmd_updatedb(args, inv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args, inv)


if __name__ == "__main__":
    sys.exit(main())
