"""A tiny Braille-dot canvas for dense terminal plots.

Each character cell packs a 2-wide by 4-tall grid of dots using the Unicode
Braille Patterns block (U+2800-U+28FF), giving 8x the resolution of one glyph.
"""

# Braille dot bit for each (x in 0..1, y in 0..3) position within a cell.
_DOT_BITS = {
    (0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
    (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80,
}


class Canvas:
    """A dot grid `width` x `height` pixels, rendered as Braille characters."""

    def __init__(self, width, height):
        # Round up to whole cells (2 wide, 4 tall).
        self.width = width
        self.height = height
        self.cols = (width + 1) // 2
        self.rows = (height + 3) // 4
        self._cells = [[0] * self.cols for _ in range(self.rows)]

    def set(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        cell_x, cell_y = x // 2, y // 4
        self._cells[cell_y][cell_x] |= _DOT_BITS[(x % 2, y % 4)]

    def render(self):
        return "\n".join(
            "".join(chr(0x2800 + cell) for cell in row) for row in self._cells
        )


# ---------- flight scatter ----------

_STAB_MIN, _STAB_MAX = -6.0, 6.0
_SPEED_MIN, _SPEED_MAX = 1.0, 14.0


def _stability(disc):
    return float(disc.turn) + float(disc.fade)


def flight_scatter(discs, width=60, height=32):
    """A Braille scatter of the bag: stability (x) vs speed (y, fast at top)."""
    if not discs:
        return "Your bag is empty — add discs with: discbag add <name>"

    canvas = Canvas(width, height)
    for d in discs:
        stab = max(_STAB_MIN, min(_STAB_MAX, _stability(d)))
        spd = max(_SPEED_MIN, min(_SPEED_MAX, float(d.speed)))
        x = round((stab - _STAB_MIN) / (_STAB_MAX - _STAB_MIN) * (width - 1))
        y = round((_SPEED_MAX - spd) / (_SPEED_MAX - _SPEED_MIN) * (height - 1))
        canvas.set(x, y)

    plot = canvas.render().split("\n")
    axis_w = 6
    lines = ["Bag flight chart   speed ↑   ·   stability →", ""]
    rows = len(plot)
    for i, row in enumerate(plot):
        # Label a few speed gridlines down the left edge.
        speed_here = _SPEED_MAX - (i / max(1, rows - 1)) * (_SPEED_MAX - _SPEED_MIN)
        label = f"{round(speed_here):>2}" if i % 2 == 0 else "  "
        lines.append(f"{label} spd │{row}")
    lines.append(" " * axis_w + "└" + "─" * len(plot[0]))
    scale = " " * (axis_w + 1) + "understable".ljust(len(plot[0]) - len("overstable")) + "overstable"
    lines.append(scale)

    lines.append("")
    lines.append("Discs:")
    for d in sorted(discs, key=lambda x: (-float(x.speed), _stability(x))):
        brand = f"{d.brand} " if getattr(d, "brand", "") else ""
        nums = "/".join(_g(v) for v in (d.speed, d.glide, d.turn, d.fade))
        lines.append(f"  {brand}{d.name}  ({nums})")
    return "\n".join(lines)


def _g(v):
    f = float(v)
    return str(int(f)) if f == int(f) else str(f)
