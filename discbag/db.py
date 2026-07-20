"""Disc database: the bundled/online snapshot of disc flight numbers and lookup.

Data source: the DiscIt API (https://discit-api.fly.dev/disc), a free no-auth
JSON endpoint sourced from the Marshall Street Flight Guide.
"""

import difflib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_URL = "https://discit-api.fly.dev/disc"

DATA_DIR = Path(__file__).resolve().parent / "data"
BUNDLED_DB_PATH = DATA_DIR / "discs.json"

RUNTIME_DIR = Path(os.path.expanduser("~")) / ".discbag"
RUNTIME_DB_PATH = RUNTIME_DIR / "discs.json"

# The flight-number fields we coerce from strings to numbers.
FLIGHT_FIELDS = ("speed", "glide", "turn", "fade")

# Fields we keep from each raw disc record.
KEPT_FIELDS = ("name", "brand", "category", "stability") + FLIGHT_FIELDS

# Tokens that describe plastic blends, runs, weights or editions rather than the
# disc itself. Stripped before matching so "Gateway Wizard SS Chalky" -> "wizard".
_NOISE_TOKENS = {
    # generic / run / edition words
    "ss", "sss", "hd", "chalky", "organic", "suregrip", "evolution", "diamond",
    "platinum", "hyperflex", "soft", "firm", "max", "mini", "glow", "glo",
    "first", "run", "tour", "series", "limited", "edition", "swirl", "blend",
    # Innova
    "star", "champion", "dx", "pro", "gstar", "xt", "kc", "jk", "rpro",
    "blizzard", "halo", "luster", "nexus", "shimmer", "metal", "flake",
    # Discraft
    "esp", "z", "zflx", "flx", "jawbreaker", "titanium", "ti", "cryztal",
    "big",
    # Dynamic/Latitude/Westside/MVP/Axiom and friends
    "lucid", "fuzion", "prime", "classic", "biofuzion", "moonshine", "vip",
    "tournament", "gold", "opto", "retro", "neutron", "plasma", "electron",
    "proton", "eclipse", "cosmic", "fission", "burst", "ice", "supreme",
}


def _num(value):
    """Coerce a flight-number string to int when whole, else float."""
    f = float(value)
    return int(f) if f == int(f) else f


def normalize_name(query):
    """Lowercase a disc query and strip plastic/run/weight noise tokens."""
    tokens = []
    for raw in str(query).lower().split():
        tok = raw.strip(".,/")
        if not tok:
            continue
        if tok in _NOISE_TOKENS:
            continue
        # weight tokens like "175g" or a bare "175"
        if tok.endswith("g") and tok[:-1].isdigit():
            continue
        if tok.isdigit() and len(tok) == 3:  # gram weight, not a disc like "machete"
            continue
        tokens.append(tok)
    return " ".join(tokens)


def _slug(value):
    """Lowercase alphanumeric runs joined by single hyphens."""
    out, prev_hyphen = [], True
    for ch in str(value or "").lower():
        if ch.isalnum():
            out.append(ch)
            prev_hyphen = False
        elif not prev_hyphen:
            out.append("-")
            prev_hyphen = True
    return "".join(out).strip("-")


def catalog_id(record):
    """Stable identifier for a catalog mold, derived from brand + name.

    Accepts a raw catalog record dict or any object exposing .brand/.name
    (Disc, OwnedDisc). Stable only while the upstream brand and mold name are
    unchanged: a catalog rename changes the derived id in schema v1.
    """
    if isinstance(record, dict):
        brand, name = record.get("brand"), record.get("name")
    else:
        brand, name = getattr(record, "brand", ""), getattr(record, "name", "")
    return "-".join(p for p in (_slug(brand), _slug(name)) if p)


def _disc_keys(disc):
    """Search keys for a disc: its bare name and brand+name, both normalized."""
    name = normalize_name(disc.get("name", ""))
    brand = normalize_name(disc.get("brand", ""))
    keys = {name}
    if brand:
        keys.add(f"{brand} {name}".strip())
    return keys


def find_disc(query, discs):
    """Find the best-matching disc for a free-text query.

    Returns (best_match_or_None, alternatives_list). Matching is forgiving of
    brand prefixes and plastic/run words.
    """
    qn = normalize_name(query)
    if not qn:
        return None, []

    # Map every search key to its disc, preserving order for stable results.
    key_to_disc = []
    for disc in discs:
        for key in _disc_keys(disc):
            key_to_disc.append((key, disc))

    def discs_for(keys):
        seen, out = set(), []
        for key in keys:
            for k, disc in key_to_disc:
                if k == key and id(disc) not in seen:
                    seen.add(id(disc))
                    out.append(disc)
        return out

    # 1. Exact key matches first (these are the strongest candidates).
    matches = discs_for([qn])

    # 2. Substring relatives (e.g. "leopard" -> "leopard3") appended as alternatives.
    subset = [k for k, _ in key_to_disc if qn in k or k in qn]
    for disc in discs_for(dict.fromkeys(subset)):
        if disc not in matches:
            matches.append(disc)

    # 3. Fuzzy match only when nothing else hit.
    if not matches:
        all_keys = list(dict.fromkeys(k for k, _ in key_to_disc))
        close = difflib.get_close_matches(qn, all_keys, n=8, cutoff=0.6)
        matches = discs_for(close)

    if not matches:
        return None, []
    return matches[0], matches[1:]


def update_db(path=None, url=DEFAULT_DB_URL, fetcher=None, now=None):
    """Fetch the disc list and write a numeric, timestamped snapshot atomically.

    `fetcher(url) -> list[dict]` and `now() -> iso str` are injectable for tests.
    On fetch failure the existing snapshot is left untouched.
    """
    path = Path(path) if path else RUNTIME_DB_PATH
    fetcher = fetcher or _http_fetch
    now = now or (lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())

    raw = fetcher(url)  # may raise; existing snapshot stays intact

    discs = []
    for entry in raw:
        disc = {f: entry.get(f) for f in ("name", "brand", "category", "stability")}
        for f in FLIGHT_FIELDS:
            try:
                disc[f] = _num(entry.get(f))
            except (TypeError, ValueError):
                disc[f] = None
        discs.append(disc)

    snapshot = {"last_updated": now(), "discs": discs}
    _write_json_atomic(path, snapshot)
    return {"count": len(discs), "last_updated": snapshot["last_updated"], "path": str(path)}


def load_db(path=None, bundled_path=None):
    """Load the runtime snapshot, seeding it from the bundled snapshot on first run."""
    path = Path(path) if path else RUNTIME_DB_PATH
    bundled_path = Path(bundled_path) if bundled_path else BUNDLED_DB_PATH

    if not path.exists():
        snapshot = json.loads(Path(bundled_path).read_text())
        _write_json_atomic(path, snapshot)
        return snapshot
    return json.loads(path.read_text())


def _http_fetch(url):
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
