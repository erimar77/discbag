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
from dataclasses import dataclass, field
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
    filled: list             # RoleFill, in role-priority order
    gaps: list                # roles.Role with no qualifying disc
    omitted: list = field(default_factory=list)   # roles trimmed only to honor --size


def _stability(disc):
    return roles.stability_number(disc)


def _overpower(disc, profile):
    """How far a disc out-powers the player (0 if within their arm)."""
    ps = player.power_speed(profile)
    if ps is None:
        return 0.0
    return max(0.0, player.required_power(disc) - ps)


def _goal_components(goal, disc, profile, today=None):
    """The named parts of a goal's per-disc adjustment (internal, lower = better).

    Returns a list of (label, value) — negative values reward, positive penalize.
    Summing them gives the goal penalty. Zero-valued parts are dropped.
    """
    goal = (goal or "coverage").lower()
    if goal == "coverage":
        return []

    user = getattr(disc, "user", None)
    uses = getattr(user, "use_count", 0) or 0
    favorite = bool(getattr(user, "favorite", False))
    stab = _stability(disc)
    usage = min(uses, 50) / 50.0  # 0..1
    recent = _used_recently(disc, today)

    parts = []
    if goal == "development":
        parts = [
            ("Power mismatch", 0.9 * _overpower(disc, profile)),
            ("Specialization", 0.5 * max(0.0, abs(stab) - 2)),
            ("Under-used (needs reps)", -0.4 * (1 - usage)),
        ]
    elif goal == "confidence":
        parts = [
            ("Proven use", -1.5 * usage),
            ("Recently used", -0.5 if recent else 0.0),
            ("Favorite", -1.0 if favorite else 0.0),
            ("Unpredictable (flippy)", 0.6 * max(0.0, -stab - 1)),
            ("Power mismatch", 0.5 * _overpower(disc, profile)),
        ]
    elif goal == "tournament":
        parts = [
            ("Proven use", -1.5 * usage),
            ("Recently used", -0.3 if recent else 0.0),
            ("Risk (understable)", 0.8 * max(0.0, -stab)),
            ("Power mismatch", 0.6 * _overpower(disc, profile)),
        ]
    elif goal == "fun":
        parts = [
            ("Favorite", -2.0 if favorite else 0.0),
            ("Overused (less novel)", 0.6 * usage),
            ("Neglected (revisit)", 0.0 if recent else -0.5),
        ]
    return [(label, value) for label, value in parts if value]


def _goal_penalty(goal, disc, profile, today=None):
    """A per-disc adjustment (lower = more preferred) layered on role fit."""
    return sum(value for _, value in _goal_components(goal, disc, profile, today))


def _selection_score(disc, role, goal, profile, today=None):
    return roles.fit_score(disc, role) + _goal_penalty(goal, disc, profile, today)


# ---------- explainable scoring ----------

# Presentation scale: internal scores are distances (lower = better); we invert them
# into readable "points" (higher = better) for explain/score output.
_POINT_SCALE = 10.0


@dataclass
class ScoreComponent:
    label: str
    points: int      # higher = better contribution


@dataclass
class DiscScore:
    disc: object
    role: roles.Role
    components: list   # ScoreComponent, in order
    total: int         # sum of component points (higher = better)
    internal: float    # raw selection score (lower = better) used for ranking


def score_disc(disc, role, goal="coverage", profile=None, today=None):
    """Explainable score of a disc for a role under a goal: components + total."""
    fit = roles.fit_score(disc, role)
    components = [ScoreComponent("Role fit", round(100 - fit * _POINT_SCALE))]
    for label, value in _goal_components(goal, disc, profile, today):
        components.append(ScoreComponent(label, round(-value * _POINT_SCALE)))
    total = sum(c.points for c in components)
    internal = fit + _goal_penalty(goal, disc, profile, today)
    return DiscScore(disc=disc, role=role, components=components, total=total, internal=internal)


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
    bag = [d for d in bag if roles.flight_known(d)]
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

    omitted = []
    if size is not None:
        kept = sorted(fills, key=lambda f: f.score)[:size]
        kept_ids = {id(f) for f in kept}
        omitted = [f.role for f in fills if id(f) not in kept_ids]
        fills = sorted(kept, key=lambda f: f.role.priority)

    return BagResult(filled=fills, gaps=gaps, omitted=omitted)


@dataclass
class RoleDecision:
    role: roles.Role
    candidates: list    # DiscScore, ranked best-first (qualifying, available discs)
    selected: object    # the chosen disc, or None if the role is a gap
    comparable: list    # discs within the rotation threshold of the best
    rotated: bool       # True if rotation chose other than the top candidate


def build_bag_explained(bag, situation=None, goal="coverage", rotate=False,
                        profile=None, rng=None, today=None):
    """Like build_bag, but returns a RoleDecision per role: the ranked candidates,
    the comparable group, the selection, and whether rotation was involved."""
    bag = [d for d in bag if roles.flight_known(d)]
    wanted = roles.roles_for_situation(situation)
    used = set()
    decisions = []

    for role in sorted(wanted, key=lambda r: r.priority):
        qualifying = [d for d in bag if roles.qualifies(d, role)]
        available = [d for d in qualifying if id(d) not in used] or qualifying
        if not available:
            decisions.append(RoleDecision(role, [], None, [], False))
            continue
        ranked = sorted((score_disc(d, role, goal, profile, today) for d in available),
                        key=lambda s: s.internal)
        scored = [(s.internal, s.disc) for s in ranked]
        comparable = comparable_group(scored)
        pick = _choose(comparable, rotate, rng)
        used.add(id(pick))
        rotated = rotate and len(comparable) > 1 and pick is not ranked[0].disc
        decisions.append(RoleDecision(role, ranked, pick, comparable, rotated))

    return decisions
