"""
Pure calculation engine. No AI calls here — every number the assistant
shows comes from this module so the model only explains, never invents.
"""
import hashlib
import json
import pathlib
import random

DATA = pathlib.Path(__file__).parent.parent / "data"
ACCESS_BLOCKED_HOURS = 3.0

# Monte Carlo parameters — all stated assumptions, not fit from data (this
# sample has no historical per-job duration variance to fit against).
MC_RUNS = 2000
# Per-job labor hours: triangular(min, mode, max) around the reference hour
# figure, replacing the old flat 75%-150% band with an actual distribution.
JOB_DURATION_TRIANGULAR = {"min_factor": 0.6, "mode_factor": 1.0, "max_factor": 1.8}
# Per-crew dispatch/travel delay before that crew's first job starts.
CREW_AVAILABILITY_DELAY_HOURS = {"low": 0.0, "high": 1.5}

_labor = json.loads((DATA / "labor_reference.json").read_text())
ILM = _labor["indirect_multiplier"]
CATEGORIES = _labor["categories"]

_risk_model = json.loads((DATA / "risk_model.json").read_text())
STORM_MULTIPLIER = _risk_model["storm_multiplier"]
BAND_THRESHOLDS = _risk_model["overall"]["band_thresholds"]

RISK_FALLBACK_REASONS = {
    # Customer-facing — never names an internal station/circuit label.
    # The technical detail (which pair, which candidate IDs) is still
    # available to a developer via GET /api/data-quality.
    "ambiguous_circuit_label": (
        "This household's circuit maps ambiguously to more than one record in the underlying grid "
        "data, so we can't trust a population-level damage rate for it."
    ),
    "unmapped_circuit_label": (
        "This household's circuit doesn't appear in the asset data used to build the historical rate "
        "model, so we can't compute a damage rate for it."
    ),
    "no_path": "This household has no validated upstream path.",
}

# Damage asset types that correspond to an actual protective device hop in
# the upstream chain (matched against that hop's free-text "description").
# Everything else (primary/secondary/pole/...) has no finer position in the
# source data than "this circuit," so it's conservatively assumed local to
# the household — a stated assumption, not a measurement.
DEVICE_DESCRIPTION_BY_ASSET_TYPE = {
    "fuse_bank": "Fuse",
    "recloser_bank": "Recloser",
    "switch": "Switch",
}


def nearest_closed_device_index(chain):
    """Index into the upstream chain of the first normally-closed protective
    device (skips the household's own transformer at index 0). None if the
    chain is unavailable or has no closed device — never guessed."""
    if not chain:
        return None
    for i, hop in enumerate(chain):
        if hop["source"] == "eo_isolating_eqpt_inst" and hop["normal_status"] == "Closed":
            return i
    return None


def restoration_phases(case):
    """
    Splits a case's damage_items into what actually blocks THIS household —
    its own transformer, plus anything between it and the nearest normally
    closed upstream protective device — versus damage further upstream that
    device isolates: crews still have to fix it, but it doesn't extend this
    household's restoration time ("step restoration").
    """
    chain = case.get("upstream_chain")
    upstream_device_descriptions = set()
    idx = nearest_closed_device_index(chain) if chain else None
    if idx is not None:
        upstream_device_descriptions = {
            hop["description"] for hop in chain[idx + 1:] if hop["source"] == "eo_isolating_eqpt_inst"
        }

    local, upstream = [], []
    for item in case["damage_items"]:
        device_label = DEVICE_DESCRIPTION_BY_ASSET_TYPE.get(item["asset_type"])
        is_upstream = device_label is not None and any(device_label in d for d in upstream_device_descriptions)
        (upstream if is_upstream else local).append(item)

    return {
        "local": local,
        "upstream": upstream,
        "chain_available": chain is not None,
        "nearest_closed_device": chain[idx]["description"] if idx is not None else None,
    }


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
        for i in range(item["quantity"]):
            label = item["asset_type"] + (f" #{i + 1}" if item["quantity"] > 1 else "")
            jobs.append({"asset_type": item["asset_type"], "label": label, "duration": per_unit_effort})
    return jobs


def _schedule(jobs, crew_count):
    """Greedy list scheduling: longest job first onto the least-loaded free crew.
    Returns one list per crew, each job annotated with its (unrounded) start/end
    hour — callers round only for display, never before using these for math."""
    crews = [[] for _ in range(max(crew_count, 1))]
    loads = [0.0] * max(crew_count, 1)
    for job in sorted(jobs, key=lambda j: -j["duration"]):
        i = loads.index(min(loads))
        start = loads[i]
        end = start + job["duration"]
        crews[i].append({**job, "start_hour": start, "end_hour": end})
        loads[i] = end
    return crews


def _makespan(jobs, crew_count):
    if not jobs:
        return 0.0
    crews = _schedule(jobs, crew_count)
    return max((c[-1]["end_hour"] for c in crews if c), default=0.0)


def job_timeline(case, crew_count=1, repairs_complete=False):
    """Restoration step timeline: one row per job, with its crew and status.
    The first job scheduled on each crew is 'in_progress' (it's the one the
    crew would be on right now in this replay); later jobs on that crew are
    'pending'. This comes straight from the scheduler, not a fabricated clock."""
    jobs = _jobs(restoration_phases(case)["local"])
    crews = _schedule(jobs, crew_count)
    timeline = []
    for crew_index, crew_jobs in enumerate(crews, start=1):
        for position, job in enumerate(crew_jobs):
            if repairs_complete:
                status = "complete"
            elif position == 0:
                status = "in_progress"
            else:
                status = "pending"
            timeline.append({
                "crew": crew_index,
                "asset_type": job["asset_type"],
                "label": job["label"],
                "duration_hours": round(job["duration"], 1),
                "start_hour": round(job["start_hour"], 1),
                "end_hour": round(job["end_hour"], 1),
                "status": status,
            })
    timeline.sort(key=lambda t: (t["crew"], t["start_hour"]))
    return timeline


def _mc_seed(case, access_blocked, extra_crews):
    """Stable across processes (unlike Python's randomized str hash()), so
    the same case+scenario always reproduces the same P10/P50/P90 —
    'seeded Monte Carlo', not fresh noise on every call."""
    key = f"{case.get('case_id')}|{access_blocked}|{extra_crews}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _simulate_makespan(rng, jobs, crew_count):
    if not jobs:
        return 0.0  # no damage => no crew dispatched => no delay sampled
    sampled = []
    for job in jobs:
        ref = job["duration"]
        sampled.append(rng.triangular(
            ref * JOB_DURATION_TRIANGULAR["min_factor"],
            ref * JOB_DURATION_TRIANGULAR["max_factor"],
            ref * JOB_DURATION_TRIANGULAR["mode_factor"],
        ))
    loads = [rng.uniform(CREW_AVAILABILITY_DELAY_HOURS["low"], CREW_AVAILABILITY_DELAY_HOURS["high"]) for _ in range(crew_count)]
    for duration in sorted(sampled, reverse=True):
        i = loads.index(min(loads))
        loads[i] += duration
    return max(loads) if loads else 0.0


def _percentile(sorted_samples, p):
    if not sorted_samples:
        return 0.0
    idx = min(len(sorted_samples) - 1, int(round(p * (len(sorted_samples) - 1))))
    return sorted_samples[idx]


def restoration_effort(case, access_blocked=False, extra_crews=0, repairs_complete=False):
    """
    Seeded Monte Carlo over labor hours (triangular distribution per job,
    replacing the old flat 75%-150% band) and crew availability (a
    dispatch/travel delay per crew before its first job). Returns
    P10/P50/P90 hours, never a single number presented as certain.
    Evidence: every hour value traces to labor_reference.json (source_data
    or assumption, per category); the distribution shapes themselves are
    stated assumptions (see MODEL_CARD.md), not fit from data.
    """
    crew_count = 1 + extra_crews
    if repairs_complete:
        return {
            "reference_effort_hours": 0.0,
            "p10_hours": 0.0,
            "p50_hours": 0.0,
            "p90_hours": 0.0,
            "access_blocked": access_blocked,
            "crew_count": crew_count,
            "mc_runs": MC_RUNS,
        }

    jobs = _jobs(restoration_phases(case)["local"])
    reference_effort = _makespan(jobs, crew_count)

    rng = random.Random(_mc_seed(case, access_blocked, extra_crews))
    samples = sorted(_simulate_makespan(rng, jobs, crew_count) for _ in range(MC_RUNS))
    p10, p50, p90 = _percentile(samples, 0.10), _percentile(samples, 0.50), _percentile(samples, 0.90)

    if access_blocked:
        p10 += ACCESS_BLOCKED_HOURS
        p50 += ACCESS_BLOCKED_HOURS
        p90 += ACCESS_BLOCKED_HOURS

    return {
        "reference_effort_hours": round(reference_effort, 1),
        "p10_hours": round(p10, 1),
        "p50_hours": round(p50, 1),
        "p90_hours": round(p90, 1),
        "access_blocked": access_blocked,
        "crew_count": crew_count,
        "mc_runs": MC_RUNS,
    }


def check_risk_fallback(case):
    """Risk has its OWN fallback condition, separate from check_fallback():
    a circuit can be perfectly fine for the restoration-scenario narrative
    (damage_items replay) while its label can't be trusted for the
    population-level historical rate (see data/data_quality.json)."""
    if case is None:
        return {"fallback": True, "reason": "No case data is available for this household."}
    status = case.get("risk_status")
    if status and status != "ok":
        template = RISK_FALLBACK_REASONS.get(status, "Historical risk data is not available for this circuit.")
        return {"fallback": True, "reason": template}
    if case.get("circuit_id") not in _risk_model["circuits"]:
        return {"fallback": True, "reason": "No exposure data is available for this circuit."}
    return {"fallback": False, "reason": None}


def risk_band(case, repairs_complete=False):
    """
    Exposure-normalized historical damage rate per circuit, empirical-Bayes
    shrunk toward the system-wide rate, scaled by storm setting (a stated
    assumption), then mapped to Low/Moderate/High via fixed thresholds
    computed from the shrunk-rate distribution across all circuits. This is
    a relative historical rate, never a calibrated outage probability —
    see data/backtest.json for how well it actually ranks damage out of
    sample (the signal is weak; say so to the customer, don't oversell it).
    """
    if repairs_complete:
        return {
            "band": "Low",
            "reason": "Repairs on this path are marked complete in this simulation.",
            "evidence": "assumption",
        }

    circuit = _risk_model["circuits"][case["circuit_id"]]
    multiplier = STORM_MULTIPLIER[case["storm_setting"]]
    effective_rate = circuit["shrunk_rate"] * multiplier

    if effective_rate <= BAND_THRESHOLDS["low_max"]:
        band = "Low"
    elif effective_rate <= BAND_THRESHOLDS["moderate_max"]:
        band = "Moderate"
    else:
        band = "High"

    return {
        "band": band,
        "reason": (
            f"Historical damage rate on this circuit ({circuit['damage_count']} of {circuit['customer_exposure']} "
            f"customers' worth of exposure, shrunk toward the system rate) is {band.lower()}, scaled x{multiplier} "
            f"for the {case['storm_setting']} storm setting — a demonstration rule, not a calibrated probability."
        ),
        "evidence": "model_estimate",
        "base_rate": circuit["shrunk_rate"],
        "effective_rate": round(effective_rate, 6),
        "system_rate": _risk_model["overall"]["system_rate"],
        "storm_multiplier": multiplier,
        "exposure": circuit["customer_exposure"],
        "damage_count": circuit["damage_count"],
    }


def confidence(case, access_blocked=False, repairs_complete=False):
    """Derived from evidence quality: effective sample size behind the
    historical rate first, then the existing replay-specific caveats."""
    if not case.get("path_valid", True):
        return {"level": "Low", "reason": "This household's upstream path failed consistency checks in the replay data."}
    if access_blocked:
        return {"level": "Low", "reason": "This scenario uses an assumed access-delay duration (+3 h), not a measured one."}

    risk_fallback = check_risk_fallback(case)
    if not risk_fallback["fallback"] and not repairs_complete:
        circuit = _risk_model["circuits"][case["circuit_id"]]
        tier = circuit["confidence"]
        if tier == "High":
            return {
                "level": "High",
                "reason": f"This circuit has {circuit['customer_exposure']} customers' worth of exposure behind its historical rate — well past the point where the empirical-Bayes estimate stops leaning on the system average.",
            }
        if tier == "Medium":
            return {
                "level": "Medium",
                "reason": f"This circuit has moderate exposure ({circuit['customer_exposure']} customers) behind its historical rate — assigning it to this household is still a replay assumption.",
            }
        return {
            "level": "Low",
            "reason": f"This circuit has limited exposure ({circuit['customer_exposure']} customers) behind its historical rate, so the estimate leans heavily on the system-wide average.",
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
