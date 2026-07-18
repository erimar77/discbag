"""Collection maturity — a qualitative read of where a bag sits today, and why.

Pure functions over owned discs: no I/O, no wall-clock (a `today: date` is injected).
The CLI composes and renders these; keep rendering out of here.
"""

import math
from dataclasses import dataclass
from datetime import date

from discbag import roles

# --- tunable constants (see the design spec) ---
MIN_USES = 10                # recorded uses before "settled" can be judged
ACTIVE_WINDOW = 90           # days: "thrown recently"
CONCENTRATION = 0.80         # share of throws a "core" must cover
CORE_FRACTION = 1 / 3        # max core size as a fraction of the active bag
RECENT_WINDOW = 180          # days: a "recently introduced" new mold
MAX_RECENT_NEW_MOLDS = 1     # new molds recently before the note reads "experimenting"
MIN_FAVORITES = 3            # supporting "established favorites" threshold
NEGLECT_DAYS = 180           # unused this long → "neglected"
DOMINANT_SHARE = 0.50        # category-usage share that makes a disc the clear primary
MAX_INSIGHTS = 4             # cap on rendered usage insights
MIN_CATEGORY_DISCS = 5       # a category needs this many discs before "concentration" is worth noting
PREF_SHARE = 0.60            # share needed before a tendency is called out


@dataclass
class Signal:
    met: bool
    text: str


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _uses(disc):
    return disc.user.use_count or 0


def _meaningful_gaps(assessment):
    """Missing, non-optional roles that matter to this player now (High/Medium)."""
    return [rc for rc in assessment
            if not rc.covered and not rc.role.optional
            and rc.priority in ("High", "Medium")]


def sufficient_usage(active, today):
    """Required: enough recorded throws, thrown recently, to judge settledness."""
    total = sum(_uses(d) for d in active)
    last = max((dt for dt in (_parse_date(d.user.last_used) for d in active) if dt),
               default=None)
    recent = last is not None and (today - last).days <= ACTIVE_WINDOW
    met = total >= MIN_USES and recent
    if total < MIN_USES:
        text = f"Only {total} recorded uses — log a few rounds to judge (need {MIN_USES})"
    elif not recent:
        text = "No rounds logged recently — throw your bag to confirm it's settled"
    else:
        text = f"{total} recorded uses, thrown recently"
    return Signal(met, text)


def settled_core(active):
    """Required: a small core carries most throws."""
    counts = sorted((_uses(d) for d in active), reverse=True)
    total = sum(counts)
    if total == 0:
        return Signal(False, "No usage recorded yet")
    target = CONCENTRATION * total
    acc = core = 0
    for c in counts:
        if acc >= target:
            break
        acc += c
        core += 1
    max_core = max(1, math.ceil(len(active) * CORE_FRACTION))
    met = core <= max_core
    pct = round(100 * acc / total)
    if met:
        text = f"{pct}% of your throws use just {core} discs — you've settled on a core"
    else:
        text = f"your throws are still spread across {core} discs — no settled core yet"
    return Signal(met, text)


def not_chasing_new_molds(all_discs, today):
    """Supporting: distinct molds whose first acquisition is recent. A backup/
    replacement/variant/rebuy of an owned mold introduces no new mold."""
    earliest = {}
    for d in all_discs:
        da = _parse_date(d.user.date_added)
        if da is None:
            continue
        key = (str(d.brand).strip().lower(), str(d.mold).strip().lower())
        if key not in earliest or da < earliest[key]:
            earliest[key] = da
    recent = sum(1 for da in earliest.values() if (today - da).days <= RECENT_WINDOW)
    met = recent <= MAX_RECENT_NEW_MOLDS
    if recent == 0:
        text = "No new molds lately — you're refining what you own"
    elif met:
        text = f"Recent additions mostly refine molds you own ({recent} new)"
    else:
        text = f"You've added {recent} new molds recently — a little experimenting"
    return Signal(met, text)


def established_favorites(active):
    """Supporting: you've marked the discs you trust."""
    n = sum(1 for d in active if d.user.favorite)
    met = n >= MIN_FAVORITES
    if not n:
        text = "No favorites marked yet"
    elif met:
        text = f"{n} established favorites"
    else:
        text = f"{n} favorites so far — mark the discs you trust"
    return Signal(met, text)


def assess_phase(active, all_discs, profile, today):
    """(phase, signals). Coverage gates; among the covered, the two required usage
    signals decide Developed vs Developing. New-mold and favorite signals are
    supporting context only."""
    if not active:
        return "Discovery", [Signal(False, "Your bag is empty — add discs to get started")]
    gaps = _meaningful_gaps(roles.assess(active, profile))
    if gaps:
        signals = [Signal(False, f"Missing {rc.role.name.lower()} ({rc.priority.lower()} priority)")
                   for rc in gaps]
        return "Discovery", signals
    usage = sufficient_usage(active, today)        # required
    core = settled_core(active)                    # required
    supporting = [not_chasing_new_molds(all_discs, today), established_favorites(active)]
    signals = [Signal(True, "No meaningful coverage gaps"), usage, core, *supporting]
    phase = "Developed" if (usage.met and core.met) else "Developing"
    return phase, signals


def _broad_category(disc):
    speed = float(disc.speed)
    if speed <= 3:
        return "putter"
    if speed <= 5:
        return "midrange"
    if speed <= 8:
        return "fairway"
    return "driver"


def _by_category(active):
    groups = {}
    for d in active:
        groups.setdefault(_broad_category(d), []).append(d)
    return groups


def _plural(cat):
    return cat + "s"


def _concentration_insight(cat, discs):
    counts = sorted((_uses(d) for d in discs), reverse=True)
    total = sum(counts)
    if len(discs) < MIN_CATEGORY_DISCS or total == 0:
        return None
    target = CONCENTRATION * total
    acc = core = 0
    for c in counts:
        if acc >= target:
            break
        acc += c
        core += 1
    if core >= len(discs):            # not actually concentrated
        return None
    pct = round(100 * acc / total)
    return f"You own {len(discs)} {_plural(cat)}; {pct}% of those throws use {core} of them."


def _neglected_insight(active, today):
    stale = []
    for d in active:
        if not getattr(d.user, "in_bag", True):
            continue
        last = _parse_date(d.user.last_used)
        added = _parse_date(d.user.date_added)
        if last is not None:
            age = (today - last).days
        elif added is not None:
            age = (today - added).days       # never thrown; age since acquired
        else:
            continue
        if age > NEGLECT_DAYS:
            stale.append((age, d))
    if not stale:
        return None
    stale.sort(key=lambda t: t[0], reverse=True)
    name = f"{stale[0][1].brand} {stale[0][1].mold}"
    months = stale[0][0] // 30
    return f"You haven't thrown your {name} in {months}+ months — it may not need a bag spot."


def _primary_backup_insight(active):
    from discbag import analysis
    for cat, discs in _by_category(active).items():
        total = sum(_uses(d) for d in discs)
        if total == 0 or len(discs) < 2:
            continue
        top = max(discs, key=_uses)
        if _uses(top) / total < DOMINANT_SHARE:
            continue
        # A backup exists if any other disc overlaps the primary's flight.
        others = [d for d in discs if d is not top]
        has_backup = any(top in g and any(o in g for o in others)
                         for g in analysis.overlap([top] + others))
        if not has_backup:
            return (f"Your {top.brand} {top.mold} is your most-thrown {cat} — "
                    "consider a backup before a new mold.")
    return None


def _category_leader_insight(active):
    best = None
    for cat, discs in _by_category(active).items():
        if len(discs) < 2:
            continue
        top = max(discs, key=lambda d: d.user.round_count)
        if top.user.round_count <= 0:
            continue
        if best is None or top.user.round_count > best[0]:
            best = (top.user.round_count, f"Your {top.brand} {top.mold} leads your "
                    f"{_plural(cat)} in rounds.")
    return best[1] if best else None


def usage_insights(active, today):
    """Grounded observations from usage history, most-salient first, capped."""
    groups = _by_category(active)
    candidates = []
    candidates.append(_neglected_insight(active, today))
    candidates.append(_primary_backup_insight(active))
    for cat, discs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        candidates.append(_concentration_insight(cat, discs))
    candidates.append(_category_leader_insight(active))
    out = [c for c in candidates if c]
    return out[:MAX_INSIGHTS]


def _stability_group(disc):
    stab = roles.stability_number(disc)
    if stab <= -0.5:
        return "understable"
    if stab < 1.5:
        return "neutral"
    return "overstable"


def _dominant(labels, share):
    """The single label holding >= share of the list, or None."""
    if not labels:
        return None
    counts = {}
    for x in labels:
        counts[x] = counts.get(x, 0) + 1
    label, n = max(counts.items(), key=lambda kv: kv[1])
    return label if n / len(labels) >= share else None


def observed_preferences(active):
    """Grounded tendencies, phrased as observations. Empty when nothing is clear."""
    out = []

    groups = [_stability_group(d) for d in active]
    lean = _dominant(groups, PREF_SHARE)
    if lean == "overstable":
        out.append("You gravitate to stable-to-overstable flights.")
    elif lean == "understable":
        out.append("You gravitate to understable flights.")
    elif lean == "neutral":
        out.append("You gravitate to neutral, straight-flying discs.")

    speeds = sorted(float(d.speed) for d in active)
    if len(speeds) >= 4:
        lo = speeds[len(speeds) // 10]
        hi = speeds[-(len(speeds) // 10) - 1]
        out.append(f"Your discs cluster around speed {int(lo)}–{int(hi)}.")

    brands = [str(d.brand) for d in active if str(d.brand)]
    counts = {}
    for b in brands:
        counts[b] = counts.get(b, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])
    if top and brands:
        lead = [b for b, n in top if n / len(brands) >= 0.25][:2]
        if lead and sum(counts[b] for b in lead) / len(brands) >= PREF_SHARE:
            out.append(f"Most of your bag is {' and '.join(lead)}.")

    return out
