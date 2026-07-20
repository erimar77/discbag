"""Serialize discbag's existing knowledge as a portable JSON snapshot (schema v1.0).

This module is a leaf: it imports from the engine, and nothing in the engine
imports it. It creates no knowledge. Every value here is either raw user data
or the return value of an existing engine function, reshaped into JSON-safe
structures. A threshold, comparison, classification, or scoring rule appearing
in this module is a defect.

Both clocks are injected. This module must never call datetime.now(): that is
what makes build_export() deterministic and byte-reproducible in tests.
"""

from dataclasses import asdict

from discbag import __version__, db, maturity, player, recommend, roles

SCHEMA_VERSION = "1.0"

# Mirrors the CLI exactly: `build-bag` defaults to goal=coverage and applies no
# --size limit. A null bag_size means "no explicit size override", not a number.
ANALYSIS_DEFAULTS = {"goal": "coverage", "bag_size": None, "rotate": False}

# The analysis sections this schema version advertises, in a stable order.
REPORTS_INCLUDED = [
    "coverage",
    "gaps",
    "overlap_groups",
    "pairwise_comparisons",
    "goal_bags",
    "scenario_bags",
    "maturity",
    "next_purchase",
    "exclusions",
]


def _iso_z(moment):
    """UTC timestamp in the schema's fixed format."""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _profile_dict(profile):
    return None if profile is None else asdict(profile)


def _empty_analysis():
    """Every analysis key, always present. Empty containers mean the report ran
    and had no results; None means a value could not be calculated."""
    return {
        "coverage": [],
        "gaps": [],
        "overlap_groups": [],
        "pairwise_comparisons": [],
        "goal_bags": {},
        "scenario_bags": {},
        "scenario_aliases": {},
        "maturity": None,
        "next_purchase": None,
        "exclusions": [],
    }


def _flight_dict(flight):
    """A Flight (or None) as JSON-safe numbers."""
    if flight is None:
        return None
    return {"speed": flight.speed, "glide": flight.glide,
            "turn": flight.turn, "fade": flight.fade}


def _catalog_summary(disc):
    """The deliberate portable summary of a mold, defined by the public schema.

    Deliberately not a dump of the internal catalog object: an export must
    render on a machine with no discs.json.
    """
    return {
        "catalog_id": db.catalog_id(disc),
        "name": disc.name,
        "brand": disc.brand,
        "category": disc.category,
        "stability": disc.stability,
        "flight": _flight_dict(roles.effective_flight(disc)) if roles.flight_known(disc)
                  else {"speed": disc.speed, "glide": disc.glide,
                        "turn": disc.turn, "fade": disc.fade},
    }


def _computed(disc, profile):
    """Engine conclusions about one disc. Every value is an existing engine
    result; unavailable ones are None rather than a substitute."""
    known = roles.flight_known(disc)
    if not known:
        return {"flight_known": False, "effective_flight": None, "behaves_flight": None,
                "stability": None, "primary_role": None, "fit_score": None,
                "required_power": None}
    effective = roles.effective_flight(disc)
    role = roles.primary_role(disc)
    return {
        "flight_known": True,
        "effective_flight": _flight_dict(effective),
        "behaves_flight": _flight_dict(roles.behaves_flight(disc, profile)),
        "stability": roles.stability_number(disc),
        "primary_role": role.name,
        # A weighted distance from the role's ideal: LOWER IS BETTER, unbounded.
        "fit_score": roles.fit_score(disc, role),
        "required_power": player.required_power(effective),
    }


def _history_summary(disc):
    u = disc.user
    return {
        "rounds": u.round_count,
        "practices": u.practice_count,
        "use_count": u.use_count,
        "first_used": u.first_used,
        "last_used": u.last_used,
        "last_round": u.last_round,
        "last_practice": u.last_practice,
        "acquired": u.date_added,
    }


def _inventory_record(disc, profile):
    return {
        "inventory_id": disc.id,
        "catalog_id": db.catalog_id(disc),
        "mold": disc.mold,
        "manufacturer": {
            "brand": disc.brand,
            "category": disc.category,
            "stability": disc.stability,
            "flight": {"speed": disc.speed, "glide": disc.glide,
                       "turn": disc.turn, "fade": disc.fade},
        },
        "user": asdict(disc.user),
        "computed": _computed(disc, profile),
        "history_summary": _history_summary(disc),
    }


def _coverage_entry(rc):
    return {
        "role": rc.role.name,
        "description": rc.role.use,
        "covered": rc.covered,
        "priority": rc.priority,
        "priority_reason": rc.priority_reason,
        "reason": rc.reason,
        "disc_ids": [d.id for d in rc.discs],      # engine order: best fit first
    }


def _next_purchase(active, catalog_discs, profile, catalog_map):
    """The engine's single most valuable purchase, with its reasoning. Candidate
    molds are not owned, so their portable summaries join the catalog map."""
    result = roles.best_next(active, catalog_discs, profile=profile)
    if result is None:
        return None
    candidates = []
    for pick in result.candidates:
        cid = db.catalog_id(pick.disc)
        catalog_map.setdefault(cid, _catalog_summary(pick.disc))
        candidates.append({"catalog_id": cid, "score": pick.score})
    return {
        "role": result.coverage.role.name,
        "priority": result.coverage.priority,
        "reason": result.reason,
        "candidates": candidates,        # engine rank order, best first
    }


def _maturity(active, all_discs, profile, analysis_date):
    if not all_discs:
        return None
    phase, signals = maturity.assess_phase(active, all_discs, profile, analysis_date)
    return {
        "phase": phase,
        "signals": [{"met": s.met, "text": s.text} for s in signals],
        "usage_insights": list(maturity.usage_insights(active, analysis_date)),
        "observed_preferences": list(maturity.observed_preferences(active)),
    }


def build_export(inventory, profile, catalog, *, analysis_date, generated_at):
    """A complete, deterministic snapshot of the collection and its analysis.

    inventory     -- list of OwnedDisc, active and archived alike
    profile       -- PlayerProfile, or None if the user has not set one
    catalog       -- list of raw catalog record dicts
    analysis_date -- datetime.date driving date-sensitive analysis
    generated_at  -- datetime.datetime recorded as provenance only
    """
    records = sorted((_inventory_record(d, profile) for d in inventory),
                     key=lambda r: r["inventory_id"])
    catalog_map = {}
    for disc in inventory:
        catalog_map.setdefault(db.catalog_id(disc), _catalog_summary(disc))

    active = [d for d in inventory if d.user.is_active]
    analysis_section = _empty_analysis()
    if active:
        assessment = roles.assess(active, profile)
        analysis_section["coverage"] = [_coverage_entry(rc) for rc in assessment]
        analysis_section["gaps"] = [_coverage_entry(rc) for rc in assessment if not rc.covered]
        analysis_section["next_purchase"] = _next_purchase(active, catalog, profile, catalog_map)
        analysis_section["maturity"] = _maturity(active, inventory, profile, analysis_date)
    else:
        analysis_section["next_purchase"] = None
        analysis_section["maturity"] = None

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_z(generated_at),
        "discbag_version": __version__,
        "analysis_defaults": dict(ANALYSIS_DEFAULTS),
        "reports_included": list(REPORTS_INCLUDED),
        "profile": _profile_dict(profile),
        "catalog": catalog_map,
        "inventory": records,
        "analysis": analysis_section,
    }
