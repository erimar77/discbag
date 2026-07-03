"""ASCII visualizations of the bag: flight chart plus distribution/histogram views."""

from collections import Counter

from discbag import braille

# Speed bands, top (fastest) to bottom (slowest).
_BANDS = [
    ("Distance", 11, 15),
    ("Fairway", 7, 10),
    ("Midrange", 4, 6),
    ("Putt/App", 1, 3),
]

_WIDTH = 41          # columns spanning stability -5 .. +5
_STAB_MIN, _STAB_MAX = -5, 5


def stability(disc):
    """A single overall-stability number: turn + fade (negative = understable)."""
    return float(disc.turn) + float(disc.fade)


def _col(stab):
    """Map a stability value to a grid column (understable left, overstable right)."""
    s = max(_STAB_MIN, min(_STAB_MAX, stab))
    frac = (s - _STAB_MIN) / (_STAB_MAX - _STAB_MIN)
    return round(frac * (_WIDTH - 1))


def _band_for(disc):
    spd = float(disc.speed)
    for name, lo, hi in _BANDS:
        if lo <= spd <= hi:
            return name
    return _BANDS[0][0] if spd > _BANDS[0][2] else _BANDS[-1][0]


_EMPTY = "Your bag is empty — add discs with: discbag add <name>"


def render(discs, kind="flight"):
    """Dispatch to a chart renderer. Unknown kinds fall back to the flight chart."""
    if not discs:
        return _EMPTY
    return {
        "stability": _render_stability,
        "speed": _render_speed,
        "composition": _render_composition,
        "brands": _render_brands,
        "grid": _render_flight,
    }.get(kind, braille.flight_scatter)(discs)


def _bar(count, total, width=30):
    filled = 0 if total == 0 else round(width * count / total)
    return "#" * filled


def _histogram(title, pairs, note=""):
    """pairs: list of (label, count). Renders aligned bars with counts."""
    total = sum(c for _, c in pairs) or 1
    label_w = max((len(str(lbl)) for lbl, _ in pairs), default=1)
    lines = [title, ""]
    for label, count in pairs:
        lines.append(f"  {str(label):<{label_w}}  {_bar(count, total):<30} {count}")
    if note:
        lines += ["", note]
    return "\n".join(lines)


def _render_speed(discs):
    counts = Counter(int(round(float(d.speed))) for d in discs)
    pairs = [(s, counts.get(s, 0)) for s in range(min(counts), max(counts) + 1)]
    return _histogram("Speed distribution", pairs)


def _render_composition(discs):
    counts = Counter(d.category or "Uncategorized" for d in discs)
    pairs = sorted(counts.items(), key=lambda kv: -kv[1])
    return _histogram("Bag composition (by category)", pairs)


def _render_brands(discs):
    counts = Counter(d.brand or "Unknown" for d in discs)
    pairs = sorted(counts.items(), key=lambda kv: -kv[1])
    return _histogram("Manufacturer breakdown", pairs)


def _render_stability(discs):
    buckets = [
        ("Very understable", lambda s: s <= -3),
        ("Understable", lambda s: -3 < s <= -1),
        ("Neutral", lambda s: -1 < s < 1),
        ("Stable-overstable", lambda s: 1 <= s < 3),
        ("Very overstable", lambda s: s >= 3),
    ]
    stabs = [stability(d) for d in discs]
    pairs = [(name, sum(1 for s in stabs if test(s))) for name, test in buckets]
    return _histogram("Stability distribution  (turn + fade)", pairs)


def _render_flight(discs):
    label_w = max(len(name) for name, _, _ in _BANDS)
    rows_by_band = {name: [" "] * _WIDTH for name, _, _ in _BANDS}
    for d in discs:
        rows_by_band[_band_for(d)][_col(stability(d))] = d.name[0].upper()

    lines = ["Bag flight chart  (Speed ↓  vs  stability →)", ""]
    for name, lo, hi in _BANDS:
        row = "".join(rows_by_band[name])
        lines.append(f"{name:>{label_w}} {lo:>2}-{hi:<2} |{row}|")

    axis = " " * (label_w + 7) + "+" + "-" * _WIDTH + "+"
    neutral_pad = (_WIDTH - len("neutral")) // 2
    scale = (" " * (label_w + 8) + "UNDERSTABLE"
             + " " * (neutral_pad - len("UNDERSTABLE")) + "neutral"
             + " " * (_WIDTH - neutral_pad - len("neutral") - len("OVERSTABLE")) + "OVERSTABLE")
    lines.append(axis)
    lines.append(scale)

    lines.append("")
    lines.append("Discs:")
    for d in sorted(discs, key=lambda x: (-float(x.speed), stability(x))):
        stab = stability(d)
        sign = f"+{stab:g}" if stab > 0 else f"{stab:g}"
        brand = f"{d.brand} " if d.brand else ""
        nums = f"{_g(d.speed)}/{_g(d.glide)}/{_g(d.turn)}/{_g(d.fade)}"
        lines.append(f"  {d.name[0].upper()}  {brand}{d.name}  ({nums}, stability {sign})")
    return "\n".join(lines)


def _g(v):
    f = float(v)
    return str(int(f)) if f == int(f) else str(f)
