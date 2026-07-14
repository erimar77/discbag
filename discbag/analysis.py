"""Analysis & decision helpers: overlap, compare, choose-a-disc, and practice.

These work on any object exposing ``name``/``brand``/``speed``/``glide``/``turn``/
``fade`` — both catalog ``Disc`` records and owned ``OwnedDisc`` instances.
"""

from dataclasses import dataclass

from discbag import roles

# Two discs within this weighted flight-distance are considered redundant.
OVERLAP_THRESHOLD = 1.6

# For the compare *verdict*: discs within this weighted flight-distance read as
# "largely duplicate". Stricter than OVERLAP_THRESHOLD (which loosely groups the
# `overlap` command) so that e.g. Wave vs Wraith reads as "same slot, different",
# not "duplicate". Tunable.
NEAR_DUPLICATE_DISTANCE = 1.0

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


def _disc_traits(disc, other):
    """Relative flight traits of `disc` vs `other`, split so sentences read
    naturally: (noun phrases that follow "has", standalone verb phrases)."""
    has_nps, verbs = [], []
    if disc.turn < other.turn:
        has_nps.append("more high-speed turn")
    elif disc.turn > other.turn:
        verbs.append("resists turning more")
    if disc.fade > other.fade:
        verbs.append("fades harder")
    elif disc.fade < other.fade:
        has_nps.append("a gentler finish")
    if disc.speed > other.speed:
        has_nps.append("a higher speed ceiling")
    elif disc.speed < other.speed:
        verbs.append("is a touch slower")
    return has_nps, verbs


def _trait_sentence(disc, other):
    has_nps, verbs = _disc_traits(disc, other)
    if not has_nps and not verbs:
        return f"The {disc.name} flies almost identically."
    if has_nps and verbs:
        return (f"The {disc.name} has {roles.english_list(has_nps)}; it also "
                f"{roles.english_list(verbs)}.")
    clauses = (["has " + roles.english_list(has_nps)] if has_nps else []) + verbs
    return f"The {disc.name} {roles.english_list(clauses)}."


def _overlap_text(a, b):
    dist = _flight_distance(a, b)
    role_a = roles.primary_role(a).name
    role_b = roles.primary_role(b).name
    same_role = role_a == role_b
    if dist <= NEAR_DUPLICATE_DISTANCE:
        where = f" in the {role_a.lower()} slot" if same_role else ""
        return f"These fly very similarly and largely duplicate each other{where}."
    if same_role:
        return (f"These occupy the same broad {role_a.lower()} slot, but their "
                "flights are meaningfully different.")
    return (f"These fill different roles — {role_a} vs {role_b} — and "
            "complement each other.")


def _how_to_use_text(a, b):
    stab_a, stab_b = roles.stability_number(a), roles.stability_number(b)
    differ = a.fade != b.fade or stab_a != stab_b
    if not differ:
        return ("These fly very similarly — reach for whichever you trust; there's "
                "no meaningful finish difference between them.")
    if stab_a == stab_b:
        # Same overall stability but a different turn/fade split: an over/under
        # "reach for" pick would conflate turn (movement) with fade (finish) and
        # contradict itself, so describe the two sides in direct flight language.
        turny, tame = (a, b) if a.turn < b.turn else (b, a)
        return (f"The {turny.name} has more turn and more fade. The {tame.name} "
                "resists turning more and finishes more gently.")
    # Different stability: more overstable = higher turn+fade.
    key = lambda d: (roles.stability_number(d), d.fade, d.speed)
    over, under = (a, b) if key(a) >= key(b) else (b, a)
    return (f"Reach for the {under.name} when you want easier distance and more "
            f"movement before the fade. Reach for the {over.name} when you want a "
            f"stronger finish or more resistance to wind. Expect the {over.name} to "
            f"finish left more strongly than the {under.name}. That difference is "
            "built into the discs, although an unusually early fade can still "
            "reflect the throw.")


def _degraded_note(discs):
    idx = range(len(discs))
    pairs = [(i, j) for i in idx for j in idx if i < j]
    ci, cj = min(pairs, key=lambda p: _flight_distance(discs[p[0]], discs[p[1]]))
    dist_total = lambda i: sum(_flight_distance(discs[i], discs[j])
                               for j in idx if j != i)
    di = max(idx, key=dist_total)
    return (f"Most similar: {discs[ci].name} and {discs[cj].name}. "
            f"Most distinct: {discs[di].name}.")


def compare_verdict(discs):
    """A rule-derived bottom line. Three-part relative verdict for exactly two
    discs; a one-line degraded note for 3+; None for fewer than two."""
    if len(discs) < 2:
        return None
    if len(discs) > 2:
        return _degraded_note(discs)
    a, b = discs
    key_diff = _trait_sentence(a, b) + " " + _trait_sentence(b, a)
    return (
        "Bottom line\n\n"
        f"Overlap:\n{_overlap_text(a, b)}\n\n"
        f"Key difference:\n{key_diff}\n\n"
        f"How to use them:\n{_how_to_use_text(a, b)}"
    )


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
