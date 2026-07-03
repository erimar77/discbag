"""Bag builder — assembles a bag by covering functional *roles*, not speed classes.

Role logic lives in ``discbag.roles`` (the engine). This module decides which owned
disc fills each required role, optimized for a **goal**:

- ``coverage``    — the best-fitting disc per role (default; fewest discs, most roles).
- ``development`` — discs the player can power and that reward clean form.
- ``confidence``  — the discs the player throws most and trusts.
- ``tournament``  — proven, reliable, low-risk molds.
- ``fun``         — favorites and variety.

Scenarios (``situation``) are environmental modifiers (windy, woods, …) that narrow
which roles the bag covers — orthogonal to the goal.

``rotate`` adds controlled variety: when several discs fill a role comparably well, it
picks among them instead of always the single best, without ever choosing a notably
worse disc.
"""

import random
from dataclasses import dataclass
from datetime import date

from discbag import player, roles

# Discs whose selection score is within this margin of the best are "comparable"
# for rotation — close enough that swapping between them keeps recommendation quality.
ROTATE_THRESHOLD = 1.0

# A disc used within this many days counts as "recently used".
RECENT_DAYS = 30

GOALS = ("coverage", "development", "confidence", "tournament", "fun")


def _to_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _used_recently(disc, today):
    """True if the disc's last use is within RECENT_DAYS of `today` (an ISO string)."""
    user = getattr(disc, "user", None)
    last = _to_date(getattr(user, "last_used", None))
    ref = _to_date(today)
    if last is None or ref is None:
        return False
    return 0 <= (ref - last).days <= RECENT_DAYS


@dataclass
class RoleFill:
    role: roles.Role
    disc: object
    score: float


@dataclass
class BagResult:
    filled: list   # RoleFill, in role-priority order
    gaps: list     # roles.Role left unfilled


def _stability(disc):
    return float(disc.turn) + float(disc.fade)


def _overpower(disc, profile):
    """How far a disc out-powers the player (0 if within their arm)."""
    ps = player.power_speed(profile)
    if ps is None:
        return 0.0
    return max(0.0, player.required_power(disc) - ps)


def _goal_penalty(goal, disc, profile, today=None):
    """A per-disc adjustment (lower = more preferred) layered on role fit."""
    goal = (goal or "coverage").lower()
    if goal == "coverage":
        return 0.0

    user = getattr(disc, "user", None)
    uses = getattr(user, "use_count", 0) or 0
    favorite = bool(getattr(user, "favorite", False))
    stab = _stability(disc)
    usage = min(uses, 50) / 50.0  # 0..1
    recent = _used_recently(disc, today)

    if goal == "development":
        # Reward discs the player can power, that aren't highly specialized, and that
        # are under-used (they deserve practice reps).
        return 0.9 * _overpower(disc, profile) + 0.5 * max(0.0, abs(stab) - 2) \
            - 0.4 * (1 - usage)
    if goal == "confidence":
        # Reward proven, recently used, favorite, predictable discs you can power.
        return (-1.5 * usage) + (-0.5 if recent else 0.0) + (-1.0 if favorite else 0.0) \
            + 0.6 * max(0.0, -stab - 1) + 0.5 * _overpower(disc, profile)
    if goal == "tournament":
        # Reward a proven, recently trusted, reliable mold; penalize risk / over-power.
        return (-1.5 * usage) + (-0.3 if recent else 0.0) \
            + 0.8 * max(0.0, -stab) + 0.6 * _overpower(disc, profile)
    if goal == "fun":
        # Favorites first; heavily-used molds are less novel; revisit neglected discs.
        return (-2.0 if favorite else 0.0) + 0.6 * usage + (0.0 if recent else -0.5)
    return 0.0


def _selection_score(disc, role, goal, profile, today=None):
    return roles.fit_score(disc, role) + _goal_penalty(goal, disc, profile, today)


def comparable_group(scored, threshold=ROTATE_THRESHOLD):
    """Given [(score, disc), ...] sorted best-first, the discs within `threshold`
    of the best score — those good enough to rotate among."""
    best = scored[0][0]
    return [disc for score, disc in scored if score <= best + threshold]


def _choose(group, rotate, rng):
    if rotate and len(group) > 1:
        return (rng or random.Random()).choice(group)
    return group[0]


def build_bag(bag, size=None, situation=None, goal="coverage",
              rotate=False, profile=None, rng=None, today=None):
    """Fill each required role with the disc that best serves the chosen `goal`.

    Roles come from the engine (optionally narrowed to a `situation`). A disc is
    preferred for one role but may cover a second if nothing else qualifies.
    `size` keeps only the best-fitting N fills. `rotate` varies among comparable discs.
    """
    wanted = roles.roles_for_situation(situation)
    used = set()
    fills, gaps = [], []

    for role in sorted(wanted, key=lambda r: r.priority):
        qualifying = [d for d in bag if roles.qualifies(d, role)]
        available = [d for d in qualifying if id(d) not in used] or qualifying
        if not available:
            gaps.append(role)
            continue
        scored = sorted(((_selection_score(d, role, goal, profile, today), d) for d in available),
                        key=lambda t: t[0])
        pick = _choose(comparable_group(scored), rotate, rng)
        used.add(id(pick))
        fills.append(RoleFill(role, pick, roles.fit_score(pick, role)))

    if size is not None:
        kept = sorted(fills, key=lambda f: f.score)[:size]
        kept_names = {f.role.name for f in kept}
        fills = sorted(kept, key=lambda f: f.role.priority)
        gaps = [r for r in wanted if r.name not in kept_names]

    return BagResult(filled=fills, gaps=gaps)
