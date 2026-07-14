"""Analysis & decision helpers: overlap, compare, choose-a-disc, and practice.

These work on any object exposing ``name``/``brand``/``speed``/``glide``/``turn``/
``fade`` — both catalog ``Disc`` records and owned ``OwnedDisc`` instances.
"""

from dataclasses import dataclass

from discbag import roles

# Two discs within this weighted flight-distance are considered redundant.
OVERLAP_THRESHOLD = 1.6

# Flight-distance weights: glide varies a lot but matters least for "same role".
_W = {"speed": 1.0, "glide": 0.3, "turn": 1.0, "fade": 1.0}


def _flight_distance(a, b):
    return (
        _W["speed"] * (a.speed - b.speed) ** 2
        + _W["glide"] * (a.glide - b.glide) ** 2
        + _W["turn"] * (a.turn - b.turn) ** 2
        + _W["fade"] * (a.fade - b.fade) ** 2
    ) ** 0.5


# ---------- overlap ----------

def overlap(discs, threshold=OVERLAP_THRESHOLD, profile=None):
    """Group discs that fly near-identically (for this player). Returns 2+ groups.

    With a profile, two discs overlap when they *behave* the same for the player,
    not just when their manufacturer numbers match.
    """
    n = len(discs)
    parent = list(range(n))
    flights = [roles.behaves_flight(d, profile) for d in discs]

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _flight_distance(flights[i], flights[j]) <= threshold:
                parent[find(i)] = find(j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(discs[i])
    return [g for g in groups.values() if len(g) >= 2]


# ---------- compare ----------

@dataclass
class Row:
    label: str
    values: list


@dataclass
class Table:
    headers: list
    rows: list


def _role_of(disc):
    """Personal role if set, else the engine's best-fit role name."""
    user = getattr(disc, "user", None)
    if user is not None and user.role:
        return user.role
    return roles.primary_role(disc).name


def compare(discs):
    """A side-by-side table of flight numbers and expected role for each disc."""
    headers = [d.name for d in discs]
    rows = [
        Row("Speed", [d.speed for d in discs]),
        Row("Glide", [d.glide for d in discs]),
        Row("Turn", [d.turn for d in discs]),
        Row("Fade", [d.fade for d in discs]),
        Row("Stability",
            [roles.stability_word(roles.stability_number(d)) for d in discs]),
        Row("Role", [_role_of(d) for d in discs]),
    ]
    return Table(headers=headers, rows=rows)


# ---------- choose ----------

@dataclass
class Pick:
    disc: object
    score: float


def _shot_target(distance=None, wind=None, shape=None):
    """Build a target (speed, turn, fade, weights) profile for a shot."""
    speed = None if distance is None else max(1.0, min(13.0, float(distance) / 28.0))

    shape = (shape or "straight").lower()
    if shape in ("hyzer", "overstable", "fade"):
        turn, fade = 0.0, 3.0
    elif shape in ("anhyzer", "turnover", "understable", "roller", "flip"):
        turn, fade = -3.0, 1.0
    else:  # straight
        turn, fade = 0.0, 1.0

    w_speed, w_turn, w_fade = 1.0, 1.3, 1.3
    wind = (wind or "none").lower()
    if wind in ("head", "headwind", "into", "hw"):
        # Into wind, a disc that resists turning matters most; slower/overstable is safer.
        turn = 0.0
        fade += 1.5
        w_speed, w_turn, w_fade = 0.5, 3.0, 0.5
    elif wind in ("tail", "tailwind", "downwind", "tw"):
        turn = min(turn, -2.0)
        fade = max(0.0, fade - 0.5)
        w_speed, w_turn, w_fade = 0.7, 2.0, 1.0

    return speed, turn, fade, (w_speed, w_turn, w_fade)


def _shot_score(flight, target):
    speed, turn, fade, (ws, wt, wf) = target
    total = wt * (flight.turn - turn) ** 2 + wf * (flight.fade - fade) ** 2
    if speed is not None:
        total += ws * (flight.speed - speed) ** 2
    return total ** 0.5


def choose(bag, distance=None, wind=None, shape=None, profile=None):
    """Rank discs for a shot, using how each flies *for this player*."""
    target = _shot_target(distance, wind, shape)
    picks = [Pick(disc=d, score=_shot_score(roles.behaves_flight(d, profile), target))
             for d in bag]
    picks.sort(key=lambda p: p.score)
    return picks


# ---------- practice ----------

def _practice_score(flight):
    """Lower is better: straight, neutral discs expose form; very fast discs less so."""
    return abs(flight.turn) + abs(flight.fade) + 0.1 * max(0.0, flight.speed - 7)


def practice(bag, count=3, profile=None):
    """The most form-friendly discs in the bag (straight, neutral, controllable)."""
    return sorted(bag, key=lambda d: _practice_score(roles.behaves_flight(d, profile)))[:count]
