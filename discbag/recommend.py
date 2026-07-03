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

from discbag import player, roles

# Discs whose selection score is within this margin of the best are "comparable"
# for rotation — close enough that swapping between them keeps recommendation quality.
ROTATE_THRESHOLD = 1.0

GOALS = ("coverage", "development", "confidence", "tournament", "fun")


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


def _goal_penalty(goal, disc, profile):
    """A per-disc adjustment (lower = more preferred) layered on role fit."""
    goal = (goal or "coverage").lower()
    if goal == "coverage":
        return 0.0

    user = getattr(disc, "user", None)
    throws = getattr(user, "throw_count", 0) or 0
    favorite = bool(getattr(user, "favorite", False))
    stab = _stability(disc)
    usage = min(throws, 50) / 50.0  # 0..1

    if goal == "development":
        # Reward discs the player can power and that aren't highly specialized.
        return 0.9 * _overpower(disc, profile) + 0.5 * max(0.0, abs(stab) - 2)
    if goal == "confidence":
        # Reward proven, favorite, predictable (overstable) discs the player can power.
        return (-1.5 * usage) + (-1.0 if favorite else 0.0) \
            + 0.6 * max(0.0, -stab - 1) + 0.5 * _overpower(disc, profile)
    if goal == "tournament":
        # Reward proven, reliable molds; penalize risky (understable) or over-powered.
        return (-1.5 * usage) + 0.8 * max(0.0, -stab) + 0.6 * _overpower(disc, profile)
    if goal == "fun":
        # Favorites first; heavily-thrown molds are a touch less novel.
        return (-2.0 if favorite else 0.0) + 0.6 * usage
    return 0.0


def _selection_score(disc, role, goal, profile):
    return roles.fit_score(disc, role) + _goal_penalty(goal, disc, profile)


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
              rotate=False, profile=None, rng=None):
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
        scored = sorted(((_selection_score(d, role, goal, profile), d) for d in available),
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
