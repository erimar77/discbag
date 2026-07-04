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


def _normalize_use(entry):
    """A use-log entry as {"date", "session_type"}. A bare timestamp string is a
    legacy round; a dict may omit the type (defaults to round)."""
    if isinstance(entry, dict):
        return {"date": entry.get("date"),
                "session_type": entry.get("session_type") or "round"}
    return {"date": entry, "session_type": "round"}


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
    # and a log of uses. Each log entry is {"date": ..., "session_type": "round"|"practice"};
    # legacy entries are bare timestamp strings and count as rounds.
    use_count: int = 0
    last_used: Optional[str] = None
    use_dates: List = field(default_factory=list)
    notes: str = ""
    personal_flight: Optional[dict] = None
    # Lifecycle: "active" (in the working bag) or an archived status (lost, sold,
    # gifted, broken, retired). Archived discs keep their history but leave the
    # active inventory the engine reasons about. status_reason tells the story.
    status: str = "active"
    status_reason: Optional[str] = None
    status_date: Optional[str] = None

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

    # --- session-typed use log ---

    @property
    def uses(self):
        """Normalized use entries: {"date", "session_type"}. Bare-string (legacy)
        entries are treated as rounds — that was the only session type before."""
        return [_normalize_use(e) for e in (self.use_dates or [])]

    @property
    def round_count(self):
        return sum(1 for e in self.uses if e["session_type"] == "round")

    @property
    def practice_count(self):
        return sum(1 for e in self.uses if e["session_type"] == "practice")

    def _last_of(self, session_type):
        dates = [e["date"] for e in self.uses
                 if e["session_type"] == session_type and e["date"]]
        return max(dates) if dates else None

    @property
    def last_round(self):
        return self._last_of("round")

    @property
    def last_practice(self):
        return self._last_of("practice")

    @property
    def first_used(self):
        dates = [e["date"] for e in self.uses if e["date"]]
        return min(dates) if dates else None

    @property
    def is_active(self):
        return (self.status or "active") == "active"


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

    def delete(self, name):
        """Permanently remove all discs whose mold matches name (case-insensitive),
        history and all — active or archived. Returns count."""
        target = name.strip().lower()
        before = len(self._discs)
        self._discs = [d for d in self._discs if d.mold.strip().lower() != target]
        removed = before - len(self._discs)
        if removed:
            self._save()
        return removed

    def list_discs(self):
        """The active inventory — discs still in play. Archived discs are excluded;
        this is what every recommendation/analysis command reasons about."""
        return [d for d in self._discs if d.user.is_active]

    def all_discs(self):
        """Every disc ever owned, active and archived — for history and lifecycle."""
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

    def filter(self, tag=None, favorite=None, in_bag=None,
               status=None, include_archived=False):
        """Owned discs matching the given user-data filters (any combination).

        By default only active discs are returned. Pass ``status`` to select a
        specific lifecycle status, or ``include_archived=True`` for every disc.
        """
        out = []
        for d in self._discs:
            if status is not None:
                if (d.user.status or "active") != status:
                    continue
            elif not include_archived and not d.user.is_active:
                continue
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

    def set_status(self, name, status, reason=None, when=None):
        """Set a disc's lifecycle status (e.g. active, retired, lost, sold). Archiving
        (any non-active status) removes it from the carry bag but keeps its history.
        Returns discs updated. Reaches archived discs too (for restore)."""
        def apply(u):
            u.status = status
            u.status_reason = reason
            u.status_date = when
            if status != "active":
                u.in_bag = False
        return self._mutate(name, apply)

    def record_use(self, name, when, session_type="round"):
        """Record that a disc was used at timestamp `when` in a session of the given
        type ("round" or "practice"): bump the count, set last_used, and append a
        typed entry to the log. use_count is session-agnostic. Returns discs updated."""
        def apply(u):
            u.use_count = (u.use_count or 0) + 1
            u.use_dates = list(u.use_dates or []) + [
                {"date": when, "session_type": session_type}]
            # last_used tracks the most recent date, even if uses are backfilled.
            if not u.last_used or str(when)[:10] >= str(u.last_used)[:10]:
                u.last_used = when
        return self._mutate(name, apply)
