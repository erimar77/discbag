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
