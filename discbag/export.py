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

from discbag import __version__

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


def build_export(inventory, profile, catalog, *, analysis_date, generated_at):
    """A complete, deterministic snapshot of the collection and its analysis.

    inventory     -- list of OwnedDisc, active and archived alike
    profile       -- PlayerProfile, or None if the user has not set one
    catalog       -- list of raw catalog record dicts
    analysis_date -- datetime.date driving date-sensitive analysis
    generated_at  -- datetime.datetime recorded as provenance only
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_z(generated_at),
        "discbag_version": __version__,
        "analysis_defaults": dict(ANALYSIS_DEFAULTS),
        "reports_included": list(REPORTS_INCLUDED),
        "profile": _profile_dict(profile),
        "catalog": {},
        "inventory": [],
        "analysis": _empty_analysis(),
    }
