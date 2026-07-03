"""The single Player Profile and the power model that makes the engine player-aware.

Two ideas live here:

1. **How much power a disc needs** (`required_power`) — derived from speed, turn AND
   fade (an understable driver needs less power than an overstable one of the same
   speed). Derived values are *estimates*; an explicit per-mold override always wins.

2. **How a disc behaves for this player** (`adjusted_numbers`) — a weaker arm makes
   discs fly more overstable (less turn, more fade), amplified for discs that need
   more power than the player has. As the player's distance grows, the adjustment
   shrinks and discs fly closer to their rated numbers.

Nothing here forbids owning or carrying a disc; it only informs recommendations.
"""

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List
from typing import Optional

RUNTIME_DIR = Path(os.path.expanduser("~")) / ".discbag"
RUNTIME_PROFILE_PATH = RUNTIME_DIR / "profile.json"

# A player whose arm matches this "power speed" throws discs roughly as rated.
NEUTRAL_POWER = 10.0
_K_BASE = 0.22   # baseline overstability a weaker arm adds across all discs
_K_GAP = 0.30    # extra overstability when a disc out-powers the player

# Power-requirement model: overstable discs need more power, understable ones less.
_KT = 0.6        # weight of turn (negative turn lowers the requirement)
_KF = 0.7        # weight of fade above neutral

# Optional explicit per-mold power overrides: {(brand_lower, mold_lower): {...}}.
POWER_OVERRIDES = {}


@dataclass
class PlayerProfile:
    # General
    experience: str = ""      # beginner / intermediate / advanced / elite
    hand: str = ""            # dominant throwing hand: right / left
    putt_hand: str = ""       # putting hand, if different from the throwing hand
    style: str = ""           # backhand / forehand / both
    # Distance
    typical_distance: Optional[int] = None
    max_distance: Optional[int] = None
    # Throwing ability
    fairway_speed: Optional[float] = None
    driver_speed: Optional[float] = None
    release_speed: Optional[float] = None
    spin_rate: Optional[float] = None
    # Preferences
    preferred_brands: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})

    def to_dict(self):
        return asdict(self)

    def is_empty(self):
        return all(v in (None, "", [], {}) for v in asdict(self).values())


# ---------- disc power requirement ----------

def required_power(disc):
    """Estimated usable-power (as a disc-speed) needed to make a disc fly as intended."""
    speed, turn, fade = float(disc.speed), float(disc.turn), float(disc.fade)
    return speed + _KT * turn + _KF * (fade - 2)


_LEVELS = [(5, "Beginner"), (8, "Intermediate"), (11, "Advanced")]


def _level_for(req):
    for threshold, name in _LEVELS:
        if req <= threshold:
            return name
    return "Elite"


def _override_for(disc, overrides):
    overrides = overrides if overrides is not None else POWER_OVERRIDES
    key = (str(getattr(disc, "brand", "")).strip().lower(), str(disc.name).strip().lower())
    return overrides.get(key)


def power_level(disc, overrides=None):
    """Return (level, estimated). Explicit override wins and is not estimated."""
    override = _override_for(disc, overrides)
    if override and override.get("level"):
        return override["level"], False
    return _level_for(required_power(disc)), True


def recommended_distance(disc, overrides=None):
    """Return (feet, estimated) — the golf distance at which a disc shines."""
    override = _override_for(disc, overrides)
    if override and override.get("distance"):
        return override["distance"], False
    return int(round(required_power(disc) * 28 + 90)), True


# ---------- player power ----------

def power_speed(profile):
    """The disc-speed the player can fully power, or None if unknown."""
    if profile is None:
        return None
    if profile.driver_speed:
        return float(profile.driver_speed)
    dist = profile.max_distance or profile.typical_distance
    if dist:
        return max(3.0, min(14.0, (float(dist) - 90) / 28.0))
    if profile.fairway_speed:
        return float(profile.fairway_speed) + 2.0
    return None


def comfort_zones(profile):
    """Speed ranges the player can throw comfortably now, is developing, and is future.

    Derived from estimated arm power (not hardcoded), to explain why recommendations
    shift as the player improves. Returns None when arm power is unknown.
    """
    ps = power_speed(profile)
    if ps is None:
        return None
    hi = int(round(ps))
    return {
        "comfortable": (2, max(2, hi)),
        "developing": (hi + 1, hi + 2),
        "future": hi + 3,
    }


def _overstability_shift(disc, ps):
    req = required_power(disc)
    return max(0.0, NEUTRAL_POWER - ps) * _K_BASE + max(0.0, req - ps) * _K_GAP


def adjusted_numbers(disc, profile):
    """How the disc flies for this player: (speed, glide, turn, fade)."""
    speed = float(disc.speed)
    glide = float(getattr(disc, "glide", 0))
    turn = float(disc.turn)
    fade = float(disc.fade)
    ps = power_speed(profile)
    if ps is None:
        return (speed, glide, turn, fade)
    shift = _overstability_shift(disc, ps)
    turn2 = min(2.0, turn + shift * 0.8)
    fade2 = min(6.0, fade + shift * 0.7)
    return (speed, glide, turn2, fade2)


# ---------- persistence ----------

def load_profile(path=None):
    path = Path(path) if path else RUNTIME_PROFILE_PATH
    if not path.exists():
        return PlayerProfile()
    return PlayerProfile.from_dict(json.loads(path.read_text()))


def save_profile(profile, path=None):
    path = Path(path) if path else RUNTIME_PROFILE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(profile.to_dict(), indent=2))
    os.replace(tmp, path)
