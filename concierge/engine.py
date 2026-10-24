"""
Pure calculation engine. No AI calls here — every number the assistant
shows comes from this module so the model only explains, never invents.
"""
import json
import pathlib

DATA = pathlib.Path(__file__).parent.parent / "data"
ACCESS_BLOCKED_HOURS = 3.0
RANGE_LOW_FACTOR = 0.75
RANGE_HIGH_FACTOR = 1.5

_labor = json.loads((DATA / "labor_reference.json").read_text())
ILM = _labor["indirect_multiplier"]
CATEGORIES = _labor["categories"]


def _unit_hours(item):
    cat = CATEGORIES[item["asset_type"]]
    if "sizes" in cat:
        key = str(item.get("size_kva") or item.get("size_group"))
        size = cat["sizes"][key]
    else:
        size = cat
    return size["install_hours"] + size["removal_hours"]


def _jobs(damage_items):
    """Each unit of quantity is its own one-crew job."""
    jobs = []
    for item in damage_items:
        per_unit_effort = _unit_hours(item) * ILM
        for _ in range(item["quantity"]):
            jobs.append(per_unit_effort)
    return jobs


def _makespan(jobs, crew_count):
    """Greedy list scheduling: longest job first onto the least-loaded free crew."""
    if not jobs:
        return 0.0
    loads = [0.0] * max(crew_count, 1)
    for duration in sorted(jobs, reverse=True):
        i = loads.index(min(loads))
        loads[i] += duration
    return max(loads)


def restoration_effort(case, access_blocked=False, extra_crews=0, repairs_complete=False):
    """
    Returns the restoration-time range for a case's damage items.
    Evidence: every hour value traces to labor_reference.json (source_data or
    assumption, per category); quantity and crew count are modeling assumptions.
    """
    if repairs_complete:
        return {
            "reference_effort_hours": 0.0,
            "low_hours": 0.0,
            "high_hours": 0.0,
            "access_blocked": access_blocked,
            "crew_count": 1 + extra_crews,
        }

    jobs = _jobs(case["damage_items"])
    crew_count = 1 + extra_crews
    reference_effort = _makespan(jobs, crew_count)

    low = reference_effort * RANGE_LOW_FACTOR
    high = reference_effort * RANGE_HIGH_FACTOR
    if access_blocked:
        low += ACCESS_BLOCKED_HOURS
        high += ACCESS_BLOCKED_HOURS

    return {
        "reference_effort_hours": round(reference_effort, 1),
        "low_hours": round(low, 1),
        "high_hours": round(high, 1),
        "access_blocked": access_blocked,
        "crew_count": crew_count,
    }


def risk_band(case, repairs_complete=False):
    """Demonstration rule, not a calibrated probability."""
    if repairs_complete:
        return {"band": "Low", "reason": "Repairs on this path are marked complete in this simulation."}

    unrepaired = [d for d in case["damage_items"] if not d.get("repaired", True)]
    if unrepaired:
        return {
            "band": "High",
            "reason": "Unrepaired damage is assigned to this household's upstream path.",
        }

    storm_band = {"calm": "Low", "moderate": "Moderate", "severe": "High"}[case["storm_setting"]]
    return {
        "band": storm_band,
        "reason": f"No unrepaired damage is assigned to this path; band follows the {case['storm_setting']} storm setting.",
    }


def confidence(case, access_blocked=False):
    """Derived from evidence quality, never from vibes."""
    if not case.get("path_valid", True):
        return {
            "level": "Low",
            "reason": "This household's upstream path failed consistency checks in the replay data.",
        }
    if access_blocked:
        return {
            "level": "Low",
            "reason": "This scenario uses an assumed access-delay duration (+3 h), not a measured one.",
        }
    return {
        "level": "Medium",
        "reason": "Damage type and access flags come from source records, but assigning them to this household is a replay assumption.",
    }


def check_fallback(case):
    if case is None:
        return {"fallback": True, "reason": "No case data is available for this household."}
    if not case.get("path_valid", True):
        return {
            "fallback": True,
            "reason": "This household has no validated upstream path, so we can't give a reliable estimate for this location.",
        }
    return {"fallback": False, "reason": None}
