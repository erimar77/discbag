"""Bag builder — assembles a bag by covering functional *roles*, not speed classes.

All role logic lives in ``discbag.roles`` (the engine); this module only decides
which owned disc best fills each required role and which roles go unfilled.
"""

from dataclasses import dataclass

from discbag import roles


@dataclass
class RoleFill:
    role: roles.Role
    disc: object
    score: float


@dataclass
class BagResult:
    filled: list   # RoleFill, in role-priority order
    gaps: list     # roles.Role left unfilled


def build_bag(bag, size=None, situation=None):
    """Fill each required role with the owned disc that best fits it.

    Roles are drawn from the engine (optionally narrowed to a `situation`).
    A disc is preferred for one role, but may cover a second if nothing else can.
    `size` keeps only the best-fitting N fills.
    """
    wanted = roles.roles_for_situation(situation)
    used = set()
    fills, gaps = [], []

    for role in sorted(wanted, key=lambda r: r.priority):
        candidates = sorted((d for d in bag if roles.qualifies(d, role)),
                             key=lambda d: roles.fit_score(d, role))
        pick = next((d for d in candidates if id(d) not in used), None)
        if pick is None:
            pick = candidates[0] if candidates else None
        if pick is None:
            gaps.append(role)
        else:
            used.add(id(pick))
            fills.append(RoleFill(role, pick, roles.fit_score(pick, role)))

    if size is not None:
        kept = sorted(fills, key=lambda f: f.score)[:size]
        kept_names = {f.role.name for f in kept}
        fills = sorted(kept, key=lambda f: f.role.priority)
        gaps = [r for r in wanted if r.name not in kept_names]

    return BagResult(filled=fills, gaps=gaps)
