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
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import List, Optional


def _new_id():
    return uuid.uuid4().hex

RUNTIME_DIR = Path(os.path.expanduser("~")) / ".discbag"
RUNTIME_INVENTORY_PATH = RUNTIME_DIR / "inventory.json"

# Manufacturer fields carried on a mold snapshot.
_MOLD_FIELDS = ("name", "brand", "category", "speed", "glide", "turn", "fade", "stability")


# --- event log ---
# Each event is a plain dict with a "date" (YYYY-MM-DD) and a "type"; the timeline
# renderer maps type -> label. Persistence stays plain dicts; these builders are the
# single source of their shape. Inventory methods are the sole recorders of events.

def _date_only(when):
    """The YYYY-MM-DD date portion of a timestamp, or None."""
    return str(when)[:10] if when else None


def _added_event(when):
    return {"date": _date_only(when), "type": "added"}


def _use_event(when, session_type):
    return {"date": _date_only(when), "type": "use", "session_type": session_type}


def _status_event(when, status, reason=None):
    return {"date": _date_only(when), "type": "status", "status": status, "reason": reason}


def _damaged_event(when, reason=None):
    return {"date": _date_only(when), "type": "damaged", "reason": reason}


def _damaged_retired_event(when, reason=None):
    return {"date": _date_only(when), "type": "damaged_retired", "reason": reason}


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
    # Wear flag, orthogonal to status: a disc can be damaged (beat-in, cracked) yet
    # still "active" and carried. Discs are plastic — replaced, never repaired — so
    # this is only cleared to correct a mistake, never to model a repair.
    damaged: bool = False
    # Chronological event log — the source of truth for the history timeline. None on a
    # legacy disc that predates the log (the loader seeds it from known timestamps); a
    # list once seeded or created. Never None on a disc created through ``add``.
    events: Optional[List] = None

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

    def log_event(self, event):
        """Append an event, initializing the log if this is the disc's first. Storage
        primitive — Inventory decides *what* to record; this just stores it."""
        self.events = list(self.events or []) + [event]


@dataclass
class OwnedDisc:
    """A physical disc you own: a mold reference + cached mold snapshot + user data."""

    brand: str
    mold: str
    cached: Disc
    user: UserData = field(default_factory=UserData)
    # A permanent per-copy identifier so two discs of the same mold keep separate
    # histories. Assigned on add; normally hidden, but `list --ids` reveals it
    # and `edit --id` lets users target a copy by it directly.
    id: str = ""

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
            id=data.get("id", ""),
        )

    def to_dict(self):
        return {"id": self.id, "brand": self.brand, "mold": self.mold,
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
            self._backfill_ids()
            self._seed_events()
            self._save()
            return discs
        discs = [OwnedDisc.from_dict(d) for d in raw]
        self._discs = discs
        # Backfill ids and seed event logs onto pre-feature discs; persist if anything changed.
        changed = self._backfill_ids()
        if self._seed_events():
            changed = True
        if changed:
            self._save()
        return discs

    def _backfill_ids(self):
        """Give every disc a permanent id. Returns True if any were assigned."""
        assigned = False
        for d in self._discs:
            if not d.id:
                d.id = _new_id()
                assigned = True
        return assigned

    def _seed_events(self):
        """One-time backfill of the event log for legacy discs (events is None), from
        known timestamps only — never inventing an event that was not stored. Returns
        True if any disc was seeded. Idempotent: a disc with a list is left alone."""
        seeded = False
        for d in self._discs:
            u = d.user
            if u.events is not None:
                continue
            evts = []
            if u.date_added:
                evts.append(_added_event(u.date_added))
            for e in u.uses:                 # normalized {date, session_type}
                if e["date"]:
                    evts.append(_use_event(e["date"], e["session_type"]))
            # The last known transition into the current status (not full history).
            if not u.is_active and u.status_date:
                evts.append(_status_event(u.status_date, u.status, u.status_reason))
            # Damage is deliberately NOT seeded: status_date may not mark when the
            # damage happened, and inventing that timestamp is forbidden.
            u.events = evts
            seeded = True
        return seeded

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps([d.to_dict() for d in self._discs], indent=2))
        os.replace(tmp, self.path)

    def add(self, disc):
        if not disc.id:
            disc.id = _new_id()
        if disc.user.events is None:
            disc.user.events = []            # a created disc is never left unseeded
        disc.user.log_event(_added_event(disc.user.date_added))
        self._discs.append(disc)
        self._save()
        return disc

    def delete(self, target):
        """Permanently remove a disc and its history — active or archived. `target`
        may be a single OwnedDisc (that copy only) or a mold-name string (every
        matching copy, for back-compat/bulk). Returns count removed."""
        victims = self._targets(target)
        ids = {id(d) for d in victims}
        before = len(self._discs)
        self._discs = [d for d in self._discs if id(d) not in ids]
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

    def refresh_manufacturer(self, db_discs, discs=None):
        """Refresh cached mold snapshots from the DB. Refreshes every owned disc by
        default, or only the given subset. Returns count updated."""
        targets = self._discs if discs is None else discs
        updated = sum(1 for d in targets if d.refresh_from_db(db_discs))
        if updated:
            self._save()
        return updated

    # --- lookup & filtering ---

    def find_by_name(self, name):
        """All owned discs whose mold matches `name` exactly (case-insensitive)."""
        target = name.strip().lower()
        return [d for d in self._discs if d.mold.strip().lower() == target]

    def find_by_id(self, disc_id):
        for d in self._discs:
            if d.id == disc_id:
                return d
        return None

    def match(self, name, include_archived=True):
        """Resolve a user-typed name to candidate discs: an exact mold match if any,
        otherwise a substring match. Used to disambiguate multiple physical copies."""
        pool = self._discs if include_archived else [d for d in self._discs if d.user.is_active]
        target = name.strip().lower()
        exact = [d for d in pool if d.mold.strip().lower() == target]
        if exact:
            return exact
        return [d for d in pool if target in d.mold.strip().lower()]

    def _targets(self, target):
        """Normalize a mutation target to a list of discs. An OwnedDisc targets that
        one copy; a string targets every copy of the mold (back-compat / bulk)."""
        if isinstance(target, OwnedDisc):
            return [target]
        return self.find_by_name(target)

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

    def _mutate(self, target, fn):
        """Apply fn to each targeted disc's user data, save if any matched, return count.
        `target` is an OwnedDisc (one copy) or a mold-name string (all copies)."""
        matches = self._targets(target)
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
            u.log_event(_status_event(when, status, reason))
        return self._mutate(name, apply)

    def set_damaged(self, name, value, reason=None, when=None):
        """Set the damaged wear flag. Orthogonal to status — does NOT archive; a
        damaged disc stays in whatever lifecycle state it was in. A reason (and
        timestamp), if given, is recorded in the event log so the disc's history
        can tell the story. Damage never touches the lifecycle status fields
        (status_reason/status_date) — those belong to lost/sold/retired, and
        overwriting them would corrupt an archived disc's real reason.
        Returns discs updated."""
        def apply(u):
            u.damaged = bool(value)
            if value:
                u.log_event(_damaged_event(when, reason))
            # Clearing the flag (mistake fix) is not itself a story event.
        return self._mutate(name, apply)

    def retire_damaged(self, disc, reason=None, when=None):
        """Atomically retire a disc as damaged (the `damaged --retire` command): set
        damaged, archive as broken, pull it from the bag, and log ONE combined
        `damaged_retired` event. Does not route through set_status/set_damaged, so the
        single atomic command yields a single event, not two. Returns discs updated."""
        def apply(u):
            u.damaged = True
            u.status = "broken"
            u.status_reason = reason
            u.status_date = when
            u.in_bag = False
            u.log_event(_damaged_retired_event(when, reason))
        return self._mutate(disc, apply)

    def replace(self, disc, status="retired", reason=None, when=None, **overrides):
        """Replace one physical disc: archive `disc` (an OwnedDisc) with `status`,
        preserving its history, and add a fresh copy of the same mold. The new copy
        inherits the bag identity — plastic, weight, color, role, favorite, in_bag,
        tags — but starts a clean life story (no use history, condition, notes, or
        damage). ``plastic``/``weight``/``color`` overrides win over the inherited
        values, for a rebuy in a different run. Returns the new OwnedDisc."""
        u = disc.user
        # Capture the inherited identity BEFORE archiving mutates the old copy.
        new_user = UserData(
            plastic=overrides.get("plastic") or u.plastic,
            weight=overrides["weight"] if overrides.get("weight") is not None else u.weight,
            color=overrides.get("color") or u.color,
            role=u.role,
            favorite=u.favorite,
            in_bag=u.in_bag,
            tags=list(u.tags),
            date_added=_date_only(when),     # a fresh copy is added now — dates its Added event
        )
        new = OwnedDisc(brand=disc.brand, mold=disc.mold,
                        cached=Disc.from_dict(disc.cached.to_dict()), user=new_user)
        self.set_status(disc, status, reason=reason, when=when)
        return self.add(new)

    def update_metadata(self, disc, *, brand=None, mold=None, plastic=None,
                        weight=None, color=None, condition=None, notes=None,
                        db_discs=None):
        """Correct one physical disc's inventory metadata in place (the `edit`
        command). Overwrites only the fields passed — ``None`` means leave
        unchanged. Never logs a history event: metadata correction is not part
        of a disc's career, so history, usage, favorite, tags, lifecycle status,
        and the event log are all left intact.

        ``brand`` (manufacturer) and ``mold`` are the disc's identity; the cached
        flight snapshot is derived from them. If either changes, the cached
        snapshot is refreshed here via the same resolver ``add`` uses
        (``db.find_disc``) so callers never have to remember to. Returns
        ``(identity_changed, matched_record_or_None)`` so the CLI can report the
        lookup outcome. On no DB match the identity strings are still applied and
        the cached snapshot is left untouched.
        """
        from discbag import db

        identity_changed = False
        if brand is not None and brand != disc.brand:
            disc.brand = brand
            identity_changed = True
        if mold is not None and mold != disc.mold:
            disc.mold = mold
            identity_changed = True

        u = disc.user
        if plastic is not None:
            u.plastic = plastic
        if weight is not None:
            u.weight = weight
        if color is not None:
            u.color = color
        if condition is not None:
            u.condition = condition
        if notes is not None:
            u.notes = notes

        matched = None
        if identity_changed and db_discs is not None:
            best, _ = db.find_disc(f"{disc.brand} {disc.mold}", db_discs)
            if best is not None:
                disc.cached = Disc.from_db_record(best)
                matched = best

        self._save()
        return identity_changed, matched

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
            u.log_event(_use_event(when, session_type))
        return self._mutate(name, apply)
