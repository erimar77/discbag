"""The bag intelligence engine.

A single, reusable definition of disc-golf *roles* — the jobs a disc performs —
described by flight characteristics (turn/fade, with a speed band to place the
class) and intended use, NOT by speed alone. Every command reasons through this
engine: what roles a bag covers, which are missing, which discs qualify and why,
and what to acquire next.

Future-proofing: role qualification runs on each disc's *effective* flight —
personal flight numbers when the player has recorded them, otherwise the
manufacturer numbers. The role definitions never need to change as discs beat in
or a player's power changes.
"""

import math
from collections import namedtuple
from dataclasses import dataclass

from discbag import player


def _personal_complete(disc):
    p = getattr(getattr(disc, "user", None), "personal_flight", None)
    return bool(p) and all(p.get(k) is not None for k in ("speed", "glide", "turn", "fade"))


def _manufacturer_complete(disc):
    return all(getattr(disc, k, None) is not None for k in ("speed", "glide", "turn", "fade"))


def flight_known(disc):
    """Complete flight to reason with: the player's personal_flight, or the mold's published
    numbers. Works on OwnedDisc (delegates to its cached snapshot) and on a bare Disc."""
    return _personal_complete(disc) or _manufacturer_complete(disc)


def stability_number(disc):
    """turn + fade, or None if flight is incomplete."""
    if disc.turn is None or disc.fade is None:
        return None
    return float(disc.turn) + float(disc.fade)


def stability_word(stab):
    """Map a stability number to a broad category word."""
    if stab <= -2:
        return "very understable"
    if stab <= -0.5:
        return "understable"
    if stab < 1.5:
        return "neutral"
    if stab < 3:
        return "overstable"
    return "very overstable"


INF = math.inf

Flight = namedtuple("Flight", ["speed", "glide", "turn", "fade"])


@dataclass(frozen=True)
class Role:
    name: str
    use: str                    # plain-language purpose
    speed: tuple                # (min, max) inclusive band
    turn: tuple
    fade: tuple
    ideal: tuple                # (speed, turn, fade) centre, for ranking fit
    priority: int               # 1 = most essential
    covered_reason: str         # why qualifying discs satisfy the role
    missing_reason: str         # why the role is unmet when empty
    min_power: float = 0        # player power-speed at which this role becomes useful
    overstable: bool = False    # a fade-first role (low value once a bag already fades)
    optional: bool = False


# Ordered roughly slow -> fast. Bands intentionally overlap: a disc is placed by
# how it flies (turn/fade), with speed only narrowing the class.
ROLES = [
    Role("Putting", "putting and short, controlled approaches",
         speed=(1, 4), turn=(-1.5, 1), fade=(0, 2), ideal=(2.5, 0, 1), priority=1,
         covered_reason="a slow, stable flight you can trust up close",
         missing_reason="No slow, stable putter for putting and short approaches.",
         min_power=1),
    Role("Straight approach", "straight, controllable approach shots",
         speed=(3, 5), turn=(-1, 0.5), fade=(0, 1.5), ideal=(4, 0, 1), priority=6,
         covered_reason="a straight, controllable approach flight",
         missing_reason="No straight, controllable approach disc.",
         min_power=3),
    Role("Overstable approach", "reliable fade for headwind and forehand approaches",
         speed=(2.5, 5.5), turn=(-1, 1.5), fade=(2.5, INF), ideal=(3.5, 0, 3), priority=4,
         covered_reason="a dependable fade for forehands and headwind approaches",
         missing_reason="No overstable approach disc that reliably fades in wind.",
         min_power=3, overstable=True),
    Role("Straight mid", "neutral tunnel shots with minimal fade",
         speed=(4.5, 6.5), turn=(-1, 0.5), fade=(0, 1.5), ideal=(5, 0, 1), priority=2,
         covered_reason="a neutral flight with minimal fade",
         missing_reason="No neutral, straight-flying midrange.",
         min_power=4.5),
    Role("Overstable mid", "dependable fade in wind and on forced flex shots",
         speed=(4.5, 6.5), turn=(-1, 1.5), fade=(3, INF), ideal=(5, 0, 3), priority=7,
         covered_reason="a reliable, wind-fighting fade at midrange speed",
         missing_reason="No overstable midrange with the fade to hold up in wind.",
         min_power=5, overstable=True),
    Role("Understable fairway", "easy turnovers, hyzer flips and rollers",
         speed=(6, 10), turn=(-INF, -2), fade=(0, 2), ideal=(7, -3, 1), priority=8,
         covered_reason="enough turn for turnovers, hyzer flips and rollers",
         missing_reason="No understable fairway for turnovers and hyzer flips.",
         min_power=6),
    Role("Control fairway", "accurate placement with a predictable finish",
         speed=(6.5, 10), turn=(-1.5, 1), fade=(1.5, 3.5), ideal=(7.5, 0, 2.5), priority=3,
         covered_reason="a predictable finish for accurate placement",
         missing_reason="No stable control fairway for accurate placement.",
         min_power=6.5),
    Role("Utility driver", "wind resistance, skips, flex and escape shots",
         speed=(8, INF), turn=(-1, INF), fade=(4, INF), ideal=(10, 0, 4.5), priority=5,
         covered_reason="enough fade to hold a line into wind and skip predictably",
         missing_reason="No disc has enough fade to reliably serve as a utility driver.",
         min_power=9.5, overstable=True),
    Role("Distance driver", "maximum distance off the tee",
         speed=(9.5, INF), turn=(-3, 0.5), fade=(1.5, 3.5), ideal=(12, -1, 2.5), priority=9,
         covered_reason="the speed to reach maximum distance",
         missing_reason="No high-speed distance driver.",
         min_power=10, optional=True),
]


# Ranking weights: turn and fade (how it flies) matter more than raw speed.
_W_SPEED, _W_TURN, _W_FADE = 1.0, 1.3, 1.3

# Named situations select a subset of roles to build a bag around.
_SITUATIONS = {
    "windy": ["Putting", "Overstable approach", "Overstable mid", "Control fairway", "Utility driver"],
    "rain": ["Putting", "Overstable approach", "Overstable mid", "Control fairway", "Utility driver"],
    "woods": ["Putting", "Straight approach", "Straight mid", "Understable fairway", "Control fairway"],
    "minimal": ["Putting", "Straight mid", "Control fairway", "Overstable approach"],
    "travel": ["Putting", "Straight mid", "Control fairway", "Overstable approach"],
}


def effective_flight(disc):
    """The flight numbers to reason with: personal if recorded, else manufacturer.

    Callers must only pass `flight_known` discs — Unknown flight is never coerced
    to 0; incomplete data fails loudly instead.
    """
    if _personal_complete(disc):
        p = disc.user.personal_flight
        return Flight(speed=float(p["speed"]), glide=float(p["glide"]),
                      turn=float(p["turn"]), fade=float(p["fade"]))
    if not _manufacturer_complete(disc):
        raise ValueError("effective_flight requires complete flight data")
    return Flight(speed=float(disc.speed), glide=float(disc.glide),
                  turn=float(disc.turn), fade=float(disc.fade))


def behaves_flight(disc, profile=None):
    """How the disc flies for this player: personal numbers if recorded, else the
    player-power-adjusted manufacturer numbers (or raw numbers with no profile)."""
    personal = getattr(getattr(disc, "user", None), "personal_flight", None)
    if personal:
        return effective_flight(disc)
    speed, glide, turn, fade = player.adjusted_numbers(disc, profile)
    return Flight(speed=speed, glide=glide, turn=turn, fade=fade)


def _in(value, band):
    return band[0] <= value <= band[1]


def qualifies(disc, role):
    """Does this disc fly the way the role requires (on its effective flight)?"""
    f = effective_flight(disc)
    return _in(f.speed, role.speed) and _in(f.turn, role.turn) and _in(f.fade, role.fade)


def fit_score(disc, role):
    """Lower is better: weighted distance of the disc's flight from the role's ideal."""
    f = effective_flight(disc)
    si, ti, fi = role.ideal
    return (_W_SPEED * (f.speed - si) ** 2
            + _W_TURN * (f.turn - ti) ** 2
            + _W_FADE * (f.fade - fi) ** 2) ** 0.5


def why_qualifies(disc, role):
    """A short explanation of why a specific disc satisfies a role."""
    f = effective_flight(disc)
    return f"{role.covered_reason} (turn {f.turn:g}, fade {f.fade:g})"


def primary_role(disc):
    """The single role a disc best embodies — a qualifying one if any, else nearest."""
    qualifying = [r for r in ROLES if qualifies(disc, r)]
    pool = qualifying or ROLES
    return min(pool, key=lambda r: fit_score(disc, r))


@dataclass
class RoleCoverage:
    role: Role
    covered: bool
    discs: list      # owned discs that qualify, best fit first
    reason: str
    priority: str = "Medium"      # Satisfied / High / Medium / Low
    priority_reason: str = ""


_PRIORITY_RANK = {"Satisfied": -1, "High": 0, "Medium": 1, "Low": 2}


def _bag_behaves_overstable(bag, profile):
    """True when most of the bag already fades (fights right) for this player."""
    if not bag:
        return False
    overstable = sum(1 for d in bag
                     if (lambda f: f.turn + f.fade >= 2)(behaves_flight(d, profile)))
    return overstable / len(bag) > 0.5


def _priority(role, covered, bag, profile):
    """Practical value of filling a role: does it improve THIS player's game today?"""
    if covered:
        return "Satisfied", ""
    if profile is None:
        return ("High" if role.priority <= 4 else "Medium"), ""

    ps = player.power_speed(profile)
    needs_more_power = ps is not None and (role.min_power - ps) > 1.5

    if role.overstable and (needs_more_power or _bag_behaves_overstable(bag, profile)):
        return "Low", (f"at your power most of your discs already behave overstable, so a "
                       f"{role.name.lower()} adds few new shot shapes today — re-evaluate as "
                       "your distance grows")
    if needs_more_power:
        return "Low", ("this role needs more arm speed than you have today — re-evaluate "
                       "after increasing your distance")
    return ("High" if role.priority <= 4 else "Medium"), ""


@dataclass
class Pick:
    disc: object
    score: float


@dataclass
class NextPurchase:
    coverage: RoleCoverage
    candidates: list  # Pick suggestions from the catalog
    reason: str


def assess(bag, profile=None):
    """For every role: which owned discs fill it, whether it's covered, and how
    valuable filling it would be for this player (priority)."""
    assessment = []
    for role in ROLES:
        fits = sorted((d for d in bag if qualifies(d, role)),
                      key=lambda d: fit_score(d, role))
        covered = bool(fits)
        reason = role.covered_reason if covered else role.missing_reason
        priority, priority_reason = _priority(role, covered, bag, profile)
        assessment.append(RoleCoverage(role, covered, fits, reason, priority, priority_reason))
    return assessment


# A preferred-brand disc is promoted ahead of a non-preferred one when their fits are
# within this many fit-score units — "close enough" that brand preference breaks the tie.
SUGGEST_BRAND_BOOST = 1.0


def _preferred_brands(profile):
    brands = getattr(profile, "preferred_brands", None) or []
    return {b.strip().lower() for b in brands}


def suggest(role, owned, catalog, n=3, profile=None, preferred_only=False):
    """Qualifying discs from the catalog you don't already own, best fit first.

    Still surfaces the best fits, but when a preferred-brand disc fits nearly as well as
    a non-preferred one it's promoted above it. `preferred_only` restricts suggestions to
    preferred brands entirely (ignored if you have no preferred brands set).
    """
    owned_names = {getattr(d, "mold", d.name).strip().lower() for d in owned}
    preferred = _preferred_brands(profile)

    candidates = [d for d in catalog
                  if qualifies(d, role) and d.name.strip().lower() not in owned_names]
    if preferred_only and preferred:
        candidates = [d for d in candidates
                      if str(getattr(d, "brand", "")).strip().lower() in preferred]

    def is_preferred(disc):
        return str(getattr(disc, "brand", "")).strip().lower() in preferred

    picks = [Pick(d, fit_score(d, role)) for d in candidates]
    # Preferred brands get a fit "discount", so they lead only among close fits;
    # a clearly better non-preferred disc (gap > boost) still ranks first.
    picks.sort(key=lambda p: (p.score - (SUGGEST_BRAND_BOOST if is_preferred(p.disc) else 0),
                              p.score))
    return picks[:n]


def best_next(bag, catalog, n=3, profile=None, preferred_only=False):
    """The missing role whose filling would most improve THIS player's game.

    Ranks by practical priority first (High before Low), then by how essential the
    role is — so a weak player is steered to useful discs, not a theoretically
    missing utility driver that adds nothing today.
    """
    assessment = assess(bag, profile)
    missing = [rc for rc in assessment if not rc.covered and not rc.role.optional]
    if not missing:
        return None
    target = min(missing, key=lambda rc: (_PRIORITY_RANK[rc.priority], rc.role.priority))
    covered = [rc.role.name.lower() for rc in assessment if rc.covered]
    candidates = suggest(target.role, bag, catalog, n, profile=profile,
                         preferred_only=preferred_only)

    base = target.priority_reason or target.role.missing_reason
    if covered:
        reason = f"Your bag already covers {english_list(covered)}. {base}"
    else:
        reason = base
    return NextPurchase(coverage=target, candidates=candidates, reason=reason)


def roles_for_situation(situation):
    """The roles to build a bag around for a named situation (default: all)."""
    if not situation:
        return list(ROLES)
    names = _SITUATIONS.get(situation.lower())
    if not names:
        return list(ROLES)
    order = {r.name: r for r in ROLES}
    return [order[name] for name in names if name in order]


def english_list(items):
    items = list(items)
    if len(items) <= 1:
        return items[0] if items else ""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
