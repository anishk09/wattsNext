"""
Tools exposed to the language model. The model may only call these — it
never computes a number itself. Every numeric field is wrapped with an
evidence tag: source_data, assumption, model_estimate, or not_available.
"""
from . import cases, engine, customer_services

SOURCE_DATA = "source_data"
ASSUMPTION = "assumption"
MODEL_ESTIMATE = "model_estimate"
NOT_AVAILABLE = "not_available"


def _tag(value, evidence, note=None):
    return {"value": value, "evidence": evidence, "note": note}


def get_fallback_status(household_id):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    return engine.check_fallback(case) if household else {"fallback": True, "reason": "Unknown household."}


def get_risk(household_id, repairs_complete=False):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback}
    risk_fallback = engine.check_risk_fallback(case)
    if risk_fallback["fallback"]:
        return {"fallback": risk_fallback}

    risk = engine.risk_band(case, repairs_complete=repairs_complete)
    conf = engine.confidence(case, repairs_complete=repairs_complete)
    return {
        "fallback": {"fallback": False, "reason": None},
        "city": household["city"],
        "risk_band": _tag(risk["band"], risk["evidence"], "demonstration rule, not a calibrated probability"),
        "risk_reason": risk["reason"],
        "confidence": _tag(conf["level"], MODEL_ESTIMATE, conf["reason"]),
        "storm_setting": _tag(case["storm_setting"], SOURCE_DATA),
        "storm_multiplier": _tag(risk.get("storm_multiplier"), ASSUMPTION, "Storm setting scales the historical rate as a stated assumption, not a derived value.") if "storm_multiplier" in risk else None,
        "historical_rate": {
            "base_rate": _tag(risk.get("base_rate"), MODEL_ESTIMATE, "Empirical-Bayes-shrunk historical damage rate for this circuit."),
            "system_rate": _tag(risk.get("system_rate"), SOURCE_DATA, "System-wide historical damage rate across all circuits."),
            "exposure": _tag(risk.get("exposure"), SOURCE_DATA, "Customer count on this circuit — the rate's denominator."),
            "damage_count": _tag(risk.get("damage_count"), SOURCE_DATA, "Damage records reliably joined to this circuit."),
        } if "base_rate" in risk else None,
        "confirmed_by_utility": _tag(None, NOT_AVAILABLE, "Nothing in this prototype is confirmed by the utility."),
    }


def get_restoration_estimate(household_id, access_blocked=False, extra_crews=0, repairs_complete=False):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback}

    estimate = engine.restoration_effort(
        case, access_blocked=access_blocked, extra_crews=extra_crews, repairs_complete=repairs_complete
    )
    conf = engine.confidence(case, access_blocked=access_blocked, repairs_complete=repairs_complete)
    phases = engine.restoration_phases(case)

    def _item_tag(d):
        return {
            "asset_type": _tag(d["asset_type"], SOURCE_DATA),
            "quantity": _tag(d["quantity"], ASSUMPTION, "quantity assigned to this household is a replay assumption"),
            "repaired": _tag(d.get("repaired", True), SOURCE_DATA),
        }

    return {
        "fallback": {"fallback": False, "reason": None},
        "low_hours": _tag(estimate["low_hours"], MODEL_ESTIMATE, "scenario range, not a confidence interval"),
        "high_hours": _tag(estimate["high_hours"], MODEL_ESTIMATE, "scenario range, not a confidence interval"),
        "reference_effort_hours": _tag(estimate["reference_effort_hours"], MODEL_ESTIMATE),
        "access_blocked": _tag(access_blocked, ASSUMPTION, "+3 h assumed delay when access is blocked"),
        "crew_count": _tag(estimate["crew_count"], ASSUMPTION, "baseline 1 crew; chip adds crews"),
        "damage_items": [_item_tag(d) for d in phases["local"]],
        "upstream_damage_items": [_item_tag(d) for d in phases["upstream"]],
        "nearest_closed_device": _tag(
            phases["nearest_closed_device"], SOURCE_DATA,
            "The nearest normally-closed protective device on this household's real upstream path "
            "(matched_upstream.txt) — only damage between the household and this device affects its "
            "restoration time. Damage beyond it is isolated by this device, step restoration.",
        ) if phases["nearest_closed_device"] else None,
        "confidence": _tag(conf["level"], MODEL_ESTIMATE, conf["reason"]),
        "confirmed_by_utility": _tag(None, NOT_AVAILABLE, "Nothing in this prototype is confirmed by the utility."),
    }


def get_prep_guidance(household_id, repairs_complete=False):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {
            "fallback": fallback,
            "actions": [
                "We can't give a reliable estimate for this location.",
                "Follow general storm safety guidance: charge devices, avoid downed lines, have water and food on hand.",
                "Check the official Appalachian Power outage map for live information.",
            ],
        }

    risk_fallback = engine.check_risk_fallback(case)
    if risk_fallback["fallback"]:
        # Historical risk is unavailable for this circuit label (see
        # data/data_quality.json), but prep guidance can still lean on
        # whether a damage scenario is assigned to this path at all.
        band = "Moderate" if case["damage_items"] else "Low"
        risk = {"band": band}
    else:
        risk = engine.risk_band(case, repairs_complete=repairs_complete)
    return {"fallback": {"fallback": False, "reason": None}, "actions": customer_services.prep_guidance(household, risk)}


def get_job_timeline(household_id, extra_crews=0, repairs_complete=False):
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback, "jobs": []}

    timeline = engine.job_timeline(case, crew_count=1 + extra_crews, repairs_complete=repairs_complete)
    return {
        "fallback": {"fallback": False, "reason": None},
        "jobs": [
            {
                "crew": j["crew"],
                "label": _tag(j["label"], SOURCE_DATA),
                "duration_hours": _tag(j["duration_hours"], MODEL_ESTIMATE),
                "status": j["status"],
            }
            for j in timeline
        ],
    }


def get_alert_info(household_id, access_blocked=False, extra_crews=0, repairs_complete=False, previous_estimate=None):
    household = cases.get_household(household_id)
    case = cases.case_for_household(household_id)
    fallback = engine.check_fallback(case)
    if fallback["fallback"]:
        return {"fallback": fallback}

    estimate = engine.restoration_effort(
        case, access_blocked=access_blocked, extra_crews=extra_crews, repairs_complete=repairs_complete
    )
    eligibility = customer_services.alert_eligibility(household)
    triggers = customer_services.escalation_triggers(household)
    previews = customer_services.build_alert_previews(household, case, estimate, previous_estimate)

    return {
        "fallback": {"fallback": False, "reason": None},
        "eligible": eligibility["eligible"],
        "channel": eligibility["channel"],
        "reason": eligibility["reason"],
        "escalation_triggers": triggers,
        "message_previews": previews,
    }


FUNCTION_DECLARATIONS = [
    {
        "name": "get_risk",
        "description": "Get the outage risk band and confidence for a household.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "repairs_complete": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
    {
        "name": "get_restoration_estimate",
        "description": "Get the restoration time range (hours) for a household, as a scenario range.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "access_blocked": {"type": "boolean"},
                "extra_crews": {"type": "integer"},
                "repairs_complete": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
    {
        "name": "get_prep_guidance",
        "description": "Get preparation and safety actions tailored to a household's declared needs.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "repairs_complete": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
    {
        "name": "get_alert_info",
        "description": "Get alert eligibility, channel, escalation triggers, and message previews for a household.",
        "parameters": {
            "type": "object",
            "properties": {
                "household_id": {"type": "string"},
                "access_blocked": {"type": "boolean"},
                "extra_crews": {"type": "integer"},
                "repairs_complete": {"type": "boolean"},
            },
            "required": ["household_id"],
        },
    },
]

DISPATCH = {
    "get_risk": get_risk,
    "get_restoration_estimate": get_restoration_estimate,
    "get_prep_guidance": get_prep_guidance,
    "get_alert_info": get_alert_info,
}
