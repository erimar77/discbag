"""The bag, with manufacturer data (immutable, from the DB) kept separate from
personal user data.

- ``Disc``      — a mold: manufacturer/flight data only.
- ``UserData``  — everything personal about a physical disc you own.
- ``OwnedDisc`` — a physical disc: a brand+mold reference, a cached mold snapshot
  (so it still displays if the mold later drops out of the DB), and its UserData.

Refreshing the disc database never touches user data; only the cached mold
snapshot is updated (see ``OwnedDisc.refresh_from_db``).
"""

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List, Optional

RUNTIME_DIR = Path(os.path.expanduser("~")) / ".discbag"
RUNTIME_INVENTORY_PATH = RUNTIME_DIR / "inventory.json"

# Manufacturer fields carried on a mold snapshot.
_MOLD_FIELDS = ("name", "brand", "category", "speed", "glide", "turn", "fade", "stability")


@dataclass
class Disc:
    """Manufacturer / mold data. Immutable facts sourced from the database."""

    name: str
    brand: str = ""
    category: str = ""
    speed: float = 0
    glide: float = 0
    turn: float = 0
    fade: float = 0
    stability: str = ""

    @classmethod
    def from_db_record(cls, record):
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in record.items() if k in known})

    from_dict = from_db_record

    def to_dict(self):
        return asdict(self)


@dataclass
class UserData:
    """Everything personal about a physical disc — never overwritten by a DB refresh."""

    plastic: str = ""
    weight: Optional[int] = None
    color: str = ""
    condition: str = ""
    purchase_location: str = ""
    date_added: Optional[str] = None
    favorite: bool = False
    in_bag: bool = True
    tags: List[str] = field(default_factory=list)
    role: str = ""
    # Lightweight use tracking (not throw-by-throw): a count, the last-used timestamp,
    # and a timestamped log of uses.
    use_count: int = 0
    last_used: Optional[str] = None
    use_dates: List[str] = field(default_factory=list)
    notes: str = ""
    personal_flight: Optional[dict] = None

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        # Legacy field: throw_count is now use_count.
        if "throw_count" in data and "use_count" not in data:
            data["use_count"] = data["throw_count"]
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self):
        return asdict(self)


@dataclass
class OwnedDisc:
    """A physical disc you own: a mold reference + cached mold snapshot + user data."""

    brand: str
    mold: str
    cached: Disc
    user: UserData = field(default_factory=UserData)

    # --- manufacturer accessors delegate to the cached mold snapshot ---
    @property
    def name(self):
        return self.mold

    @property
    def category(self):
        return self.cached.category

    @property
    def speed(self):
        return self.cached.speed

    @property
    def glide(self):
        return self.cached.glide

    @property
    def turn(self):
        return self.cached.turn

    @property
    def fade(self):
        return self.cached.fade

    @property
    def stability(self):
        return self.cached.stability

    # --- convenience user accessors (read-only) for display code ---
    @property
    def plastic(self):
        return self.user.plastic

    @property
    def weight(self):
        return self.user.weight

    @property
    def color(self):
        return self.user.color

    @property
    def notes(self):
        return self.user.notes

    @classmethod
    def from_db_record(cls, record, **user_kwargs):
        mold = Disc.from_db_record(record)
        return cls(brand=mold.brand, mold=mold.name, cached=mold,
                   user=UserData(**user_kwargs))

    @classmethod
    def from_dict(cls, data):
        return cls(
            brand=data.get("brand", ""),
            mold=data.get("mold", ""),
            cached=Disc.from_dict(data.get("cached", {})),
            user=UserData.from_dict(data.get("user", {})),
        )

    def to_dict(self):
        return {"brand": self.brand, "mold": self.mold,
                "cached": self.cached.to_dict(), "user": self.user.to_dict()}

    def refresh_from_db(self, db_discs):
        """Update the cached mold snapshot from the DB. User data is left untouched."""
        target = (self.brand.strip().lower(), self.mold.strip().lower())
        for record in db_discs:
            if (str(record.get("brand", "")).strip().lower(),
                    str(record.get("name", "")).strip().lower()) == target:
                self.cached = Disc.from_db_record(record)
                return True
        return False


def _is_old_flat_record(data):
    """Old format was a flat dict with a top-level 'name'; new has 'mold'."""
    return "mold" not in data and "name" in data


def _migrate_flat(data):
    """Convert an old flat record into an OwnedDisc."""
    mold = Disc.from_db_record(data)
    user = UserData.from_dict(data)  # plastic/weight/color/notes carried over
    return OwnedDisc(brand=mold.brand, mold=mold.name, cached=mold, user=user)


class Inventory:
    """A bag backed by a JSON file. Loads lazily, saves on every mutation.

    On first load of an old flat-format file it migrates in place, writing a
    ``.json.bak`` backup of the original.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else RUNTIME_INVENTORY_PATH
        self._discs = self._load()

    def _load(self):
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text())
        if any(_is_old_flat_record(d) for d in raw):
            backup = self.path.with_suffix(".json.bak")
            backup.write_text(json.dumps(raw, indent=2))
            discs = [_migrate_flat(d) if _is_old_flat_record(d) else OwnedDisc.from_dict(d)
                     for d in raw]
            self._discs = discs
            self._save()
            return discs
        return [OwnedDisc.from_dict(d) for d in raw]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps([d.to_dict() for d in self._discs], indent=2))
        os.replace(tmp, self.path)

    def add(self, disc):
        self._discs.append(disc)
        self._save()
        return disc

    def remove(self, name):
        """Remove all discs whose mold matches name (case-insensitive). Returns count."""
        target = name.strip().lower()
        before = len(self._discs)
        self._discs = [d for d in self._discs if d.mold.strip().lower() != target]
        removed = before - len(self._discs)
        if removed:
            self._save()
        return removed

    def list_discs(self):
        return list(self._discs)

    def refresh_manufacturer(self, db_discs):
        """Refresh every disc's cached mold snapshot from the DB. Returns count updated."""
        updated = sum(1 for d in self._discs if d.refresh_from_db(db_discs))
        if updated:
            self._save()
        return updated

    # --- lookup & filtering ---

    def find_by_name(self, name):
        """All owned discs whose mold matches `name` (case-insensitive)."""
        target = name.strip().lower()
        return [d for d in self._discs if d.mold.strip().lower() == target]

    def filter(self, tag=None, favorite=None, in_bag=None):
        """Owned discs matching the given user-data filters (any combination)."""
        out = []
        for d in self._discs:
            if tag is not None and tag not in d.user.tags:
                continue
            if favorite is not None and d.user.favorite != favorite:
                continue
            if in_bag is not None and d.user.in_bag != in_bag:
                continue
            out.append(d)
        return out

    # --- user-data mutations (operate on every disc of a mold) ---

    def _mutate(self, name, fn):
        """Apply fn to each matching disc, save if any matched, return count."""
        matches = self.find_by_name(name)
        for d in matches:
            fn(d.user)
        if matches:
            self._save()
        return len(matches)

    def add_tag(self, name, tag):
        def apply(u):
            if tag not in u.tags:
                u.tags.append(tag)
        return self._mutate(name, apply)

    def remove_tag(self, name, tag):
        def apply(u):
            if tag in u.tags:
                u.tags.remove(tag)
        return self._mutate(name, apply)

    def set_role(self, name, role):
        return self._mutate(name, lambda u: setattr(u, "role", role))

    def set_favorite(self, name, value):
        return self._mutate(name, lambda u: setattr(u, "favorite", bool(value)))

    def set_in_bag(self, name, value):
        return self._mutate(name, lambda u: setattr(u, "in_bag", bool(value)))

    def set_personal_flight(self, name, personal):
        return self._mutate(name, lambda u: setattr(u, "personal_flight", personal))

    def record_use(self, name, when):
        """Record that a disc was used at timestamp `when`: bump the count, set
        last_used, and append to the timestamped log. Returns discs updated."""
        def apply(u):
            u.use_count = (u.use_count or 0) + 1
            u.use_dates = list(u.use_dates or []) + [when]
            # last_used tracks the most recent date, even if uses are backfilled.
            if not u.last_used or str(when)[:10] >= str(u.last_used)[:10]:
                u.last_used = when
        return self._mutate(name, apply)
