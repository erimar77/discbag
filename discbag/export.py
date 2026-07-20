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
from itertools import combinations

from discbag import __version__, analysis, db, maturity, player, recommend, roles
from discbag.recommend import GOALS
from discbag.inventory import Disc

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

    `flight` here is always the mold's own cached/manufacturer numbers, raw
    from the disc record — never `roles.effective_flight()`, which for an
    OWNED disc can return the user's personal_flight. catalog_map is keyed by
    catalog_id, so the same mold must report the same numbers regardless of
    whether it happens to reach this function via an owned disc or a bare
    catalog record; personal numbers belong only in that disc's own
    `inventory[].computed.effective_flight`.
    """
    return {
        "catalog_id": db.catalog_id(disc),
        "name": disc.name,
        "brand": disc.brand,
        "category": disc.category,
        "stability": disc.stability,
        "flight": {"speed": disc.speed, "glide": disc.glide,
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
        candidates.append({"catalog_id": cid, "fit_score": pick.score})
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


def _bag_result(active, profile, analysis_date, goal=None, situation=None):
    """One build-bag report. Uses the CLI defaults: no size limit, no rotation
    (rotation is RNG-driven and would break reproducibility)."""
    if goal is None:
        goal = ANALYSIS_DEFAULTS["goal"]
    result = recommend.build_bag(
        active, size=ANALYSIS_DEFAULTS["bag_size"], situation=situation,
        goal=goal, rotate=False, profile=profile, today=analysis_date)
    return {
        # Engine order throughout — role priority, never alphabetized.
        # RoleFill.score is roles.fit_score for the chosen role: LOWER IS BETTER.
        "filled": [{"role": f.role.name, "disc_id": f.disc.id, "fit_score": f.score}
                   for f in result.filled],
        "gaps": [r.name for r in result.gaps],
        "omitted": [r.name for r in result.omitted],
    }


def _overlap_groups(active, profile):
    """The engine's thresholded clusters. overlap() returns member discs only —
    no score and no reasoning — so neither is exported."""
    out = []
    for group in analysis.overlap(active, profile=profile):
        ids = sorted(d.id for d in group)
        # Structural identifier for rendering, derived from the sorted members.
        # Not an engine conclusion.
        out.append({"group_id": "overlap-" + "-".join(ids), "inventory_ids": ids})
    return sorted(out, key=lambda g: g["inventory_ids"])


def _verdict_dict(verdict):
    return {"overlap_text": verdict.overlap_text,
            "key_difference": verdict.key_difference,
            "how_to_use": verdict.how_to_use,
            "degraded_note": verdict.degraded_note}


def _pairwise_comparisons(active):
    """Existing compare_verdict() output for each eligible unordered pair.

    The compare() table is deliberately omitted: it is presentation, and every
    fact it shows already lives in the two referenced inventory records.
    """
    out = []
    for a, b in combinations(active, 2):
        left, right = (a, b) if a.id <= b.id else (b, a)
        verdict = analysis.compare_verdict([left, right])
        if verdict is None:           # incomplete flight: engine declines to judge
            continue
        out.append({"left_inventory_id": left.id,
                    "right_inventory_id": right.id,
                    "verdict": _verdict_dict(verdict)})
    return sorted(out, key=lambda p: (p["left_inventory_id"], p["right_inventory_id"]))


# Reports each exclusion reason actually keeps a disc out of. Verified against
# real engine behavior — a disc is never claimed to be excluded from a report
# the engine in fact includes it in.
#
# `gaps` and `next_purchase` are deliberately absent from every list below:
# neither is keyed by owned-disc inventory_id. `gaps` lists uncovered roles
# (always an empty disc list); `next_purchase` names a recommended unowned
# catalog mold by catalog_id. An owned disc's inventory_id can never appear
# in either, so no exclusion claim about them is checkable.
_INCOMPLETE_FLIGHT_REPORTS = ["coverage", "goal_bags", "scenario_bags",
                              "overlap_groups", "pairwise_comparisons"]
# Currently identical to _INCOMPLETE_FLIGHT_REPORTS above — that's a coincidence
# of today's engine, not a documented equivalence. Keep the two lists separate:
# they assert different facts (inactive vs. flight-incomplete) and could
# diverge if either mechanism changes.
_INACTIVE_REPORTS = ["coverage", "goal_bags", "scenario_bags",
                     "overlap_groups", "pairwise_comparisons"]
# pairwise_comparisons alone gates on manufacturer-completeness
# (roles._manufacturer_complete via analysis.compare_verdict), not on
# flight_known. A disc with a complete personal_flight but no published
# manufacturer numbers passes flight_known and appears in every other report,
# but compare_verdict() still declines to judge it. disc.cached.has_flight is
# the public equivalent of roles._manufacturer_complete for an OwnedDisc: both
# delegate to the same four cached mold fields (speed/glide/turn/fade).
_MANUFACTURER_INCOMPLETE_REPORTS = ["pairwise_comparisons"]


def _exclusions(inventory):
    """Which owned discs the engine leaves out of which reports, and why.

    Excluded discs stay visible in `inventory`; only their analysis
    participation is limited. A disc can genuinely have more than one reason
    apply (e.g. inactive AND flight-incomplete) — every reason that actually
    holds gets its own entry, not just the first one checked.
    """
    out = []
    for disc in inventory:
        if not disc.user.is_active:
            out.append({"inventory_id": disc.id, "reason": "inactive_status",
                        "excluded_from": list(_INACTIVE_REPORTS)})
        if not roles.flight_known(disc):
            out.append({"inventory_id": disc.id, "reason": "incomplete_flight_data",
                        "excluded_from": list(_INCOMPLETE_FLIGHT_REPORTS)})
        elif not disc.cached.has_flight:
            # flight_known is True here (personal_flight covers it), but the
            # manufacturer numbers pairwise_comparisons actually gates on are not.
            out.append({"inventory_id": disc.id, "reason": "incomplete_manufacturer_data",
                        "excluded_from": list(_MANUFACTURER_INCOMPLETE_REPORTS)})
    return sorted(out, key=lambda e: (e["inventory_id"], e["reason"]))


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
    # setdefault is first-wins: if two owned discs share a catalog_id but carry
    # differing cached mold data, the winner must not depend on the caller's
    # inventory order. Walk the same inventory_id ordering used for `records`
    # above so the result is stable regardless of how `inventory` was passed in.
    catalog_map = {}
    for disc in sorted(inventory, key=lambda d: d.id):
        catalog_map.setdefault(db.catalog_id(disc), _catalog_summary(disc))

    active = [d for d in inventory if d.user.is_active]
    catalog_discs = [Disc.from_db_record(r) for r in catalog]
    analysis_section = _empty_analysis()
    if active:
        assessment = roles.assess(active, profile)
        analysis_section["coverage"] = [_coverage_entry(rc) for rc in assessment]
        analysis_section["gaps"] = [_coverage_entry(rc) for rc in assessment if not rc.covered]
        analysis_section["next_purchase"] = _next_purchase(active, catalog_discs, profile, catalog_map)
        analysis_section["goal_bags"] = {
            goal: _bag_result(active, profile, analysis_date, goal=goal)
            for goal in GOALS}
        canonical, aliases = roles.canonical_situations()
        analysis_section["scenario_bags"] = {
            name: _bag_result(active, profile, analysis_date, situation=name)
            for name in canonical}
        analysis_section["scenario_aliases"] = dict(aliases)
        analysis_section["overlap_groups"] = _overlap_groups(active, profile)
        analysis_section["pairwise_comparisons"] = _pairwise_comparisons(active)
    analysis_section["exclusions"] = _exclusions(inventory)
    analysis_section["maturity"] = _maturity(active, inventory, profile, analysis_date)

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
