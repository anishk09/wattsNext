"""
Builds data/risk_model.json and data/backtest.json from the raw AEP package.

Method: exposure-normalized historical damage rate per circuit (damage
records / asset count on that circuit), smoothed toward the system-wide
rate with empirical-Bayes (Poisson-Gamma) shrinkage so thinly-measured
circuits don't swing on a handful of records. This replaces the old
"unrepaired damage present => High" rule.

Data-quality handling (see data/data_quality.json, written by this script):
- ARCOS damage records carry a free-text (Substation, Circuit) pair, not
  the Customer/Transformer/etc. tables' numeric circuit_id. There is no
  supplied crosswalk, so we build one from the asset tables that carry
  BOTH a (station, circuit) pair AND a circuit_id (Transformer, Primary,
  Secondary, Fuse Bank, Recloser Bank, Switch all do; Pole does not).
  Any (station, circuit) pair seen with more than one circuit_id across
  those tables is ambiguous and excluded. Any pair never seen in any
  asset table is unmapped and excluded. Both counts are reported.
- NEAR_FID (a spatial nearest-feature index) is not used anywhere in this
  join — it's an analysis artifact of the extract, not a validated key.
- Records marked Repaired=No nonetheless carry a non-blank Repaired_D.
  Treated as a known data artifact (likely the extract's snapshot date,
  not a real repair date) and never read for Repaired=No records.
- Pole damage has no independent per-circuit exposure table, so it is
  folded into each circuit's OVERALL rate only, never given its own
  per-asset-type rate. Same for Capacitor Bank, Light, Step Transformer
  (also rare: 6, 5, 1 records system-wide).

Run: python3 scripts/build_risk_model.py
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from _dbf import read_dbf
from _circuit_join import build_circuit_crosswalk, RELIABLE_ASSET_TABLES

ROOT = pathlib.Path(__file__).parent.parent
AEP = ROOT / "aep-data" / "data" / "extracted"
OUT = ROOT / "data"

ARCOS_ASSET_TYPE_MAP = {
    "primary": "primary",
    "Pole": "pole",
    "Fuse Bank": "fuse_bank",
    "secondary": "secondary",
    "Transformer": "transformer",
    "Recloser Bank": "recloser_bank",
    "Switch": "switch",
    "Capacitor Bank": "capacitor_bank",
    "Light": "light",
    "Step Transformer": "step_transformer",
}

STORM_MULTIPLIER = {
    "calm": 0.6,
    "moderate": 1.0,
    "severe": 1.6,
}
STORM_MULTIPLIER_NOTE = (
    "Storm setting scales the historical rate as a stated assumption "
    "(calm x0.6, moderate x1.0, severe x1.6) — not derived from data; "
    "this sample has only one storm event to observe."
)

BACKTEST_CUTOFF = "20250201"  # 75% of all records land in Feb 2025 — treat that as "the storm"


def _load_dbf(path):
    _, records = read_dbf(path)
    return records


def build_exposure_counts():
    """circuit_id -> customer_count, and circuit_id -> {asset_type: count} for the 6 reliable types."""
    customers = _load_dbf(AEP / "Data1" / "Customer_Clip.dbf")
    customer_count = {}
    for r in customers:
        cid = r.get("circuit_id")
        if cid:
            customer_count[cid] = customer_count.get(cid, 0) + 1

    asset_count = {}  # circuit_id -> {asset_type: count}
    for asset_type, path in RELIABLE_ASSET_TABLES.items():
        for r in _load_dbf(path):
            cid = r.get("circuit_id")
            if not cid:
                continue
            asset_count.setdefault(cid, {}).setdefault(asset_type, 0)
            asset_count[cid][asset_type] += 1

    return customer_count, asset_count


def load_damage_records():
    return _load_dbf(AEP / "Data1" / "arcos_prod_damage_09_28_Clip.dbf")


def eb_fit(rates_and_exposures):
    """Method-of-moments Poisson-Gamma empirical Bayes fit.
    rates_and_exposures: list of (damage_count, exposure) pairs, one per circuit.
    Returns (alpha, beta) for the Gamma(alpha, beta) prior on the rate."""
    total_d = sum(d for d, e in rates_and_exposures)
    total_e = sum(e for d, e in rates_and_exposures)
    if total_e == 0:
        return None
    r_bar = total_d / total_e

    # Weighted variance of raw per-circuit rates around r_bar, minus the
    # expected Poisson sampling variance, isolates the true between-circuit
    # (prior) variance. Negative values (sampling noise dominates) floor to
    # a small positive number so beta stays finite instead of blowing up.
    weighted_sq_dev = 0.0
    mean_e = total_e / len(rates_and_exposures)
    for d, e in rates_and_exposures:
        if e <= 0:
            continue
        raw = d / e
        weighted_sq_dev += e * (raw - r_bar) ** 2
    observed_var = weighted_sq_dev / total_e if total_e else 0.0
    sampling_var = r_bar / mean_e if mean_e else 0.0
    prior_var = max(observed_var - sampling_var, r_bar * r_bar * 0.01)

    beta = r_bar / prior_var
    alpha = r_bar * beta
    return {"alpha": alpha, "beta": beta, "system_rate": r_bar}


def shrink(damage_count, exposure, fit):
    if fit is None or exposure <= 0:
        return None
    return (fit["alpha"] + damage_count) / (fit["beta"] + exposure)


def confidence_tier(exposure, beta):
    if exposure <= 0:
        return None
    if exposure < beta:
        return "Low"
    if exposure < 5 * beta:
        return "Medium"
    return "High"


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def band_thresholds(shrunk_rates):
    vals = sorted(v for v in shrunk_rates if v is not None)
    return {"low_max": percentile(vals, 1 / 3), "moderate_max": percentile(vals, 2 / 3)}


def band_for_rate(rate, thresholds):
    if rate <= thresholds["low_max"]:
        return "Low"
    if rate <= thresholds["moderate_max"]:
        return "Moderate"
    return "High"


def spearman(x, y):
    """Spearman rank correlation, stdlib only."""
    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg_rank = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg_rank
            i = j + 1
        return r

    if len(x) < 2:
        return None
    rx, ry = ranks(x), ranks(y)
    n = len(x)
    mean_rx, mean_ry = sum(rx) / n, sum(ry) / n
    cov = sum((a - mean_rx) * (b - mean_ry) for a, b in zip(rx, ry))
    var_x = sum((a - mean_rx) ** 2 for a in rx)
    var_y = sum((b - mean_ry) ** 2 for b in ry)
    if var_x == 0 or var_y == 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def run_backtest(damage_records, crosswalk, customer_count):
    train = [r for r in damage_records if r.get("Report_Tim") and r["Report_Tim"] < BACKTEST_CUTOFF]
    test = [r for r in damage_records if r.get("Report_Tim") and r["Report_Tim"] >= BACKTEST_CUTOFF]

    def damage_by_circuit(records):
        counts = {}
        for r in records:
            key = (r.get("Substation"), r.get("Circuit"))
            cid = crosswalk.get(key)
            if cid:
                counts[cid] = counts.get(cid, 0) + 1
        return counts

    train_damage = damage_by_circuit(train)
    test_damage = damage_by_circuit(test)

    circuits = sorted(customer_count.keys())
    fit = eb_fit([(train_damage.get(c, 0), customer_count[c]) for c in circuits])

    trained_rate = [shrink(train_damage.get(c, 0), customer_count[c], fit) for c in circuits]
    actual_future_damage = [test_damage.get(c, 0) for c in circuits]

    rho = spearman(trained_rate, actual_future_damage)

    # Top-decile hit rate: of circuits ranked in the top 10% by trained
    # rate, what share of all post-cutoff damage landed in them?
    ranked = sorted(zip(circuits, trained_rate), key=lambda cr: -(cr[1] or 0))
    top_n = max(1, len(ranked) // 10)
    top_circuits = {c for c, _ in ranked[:top_n]}
    damage_in_top = sum(test_damage.get(c, 0) for c in top_circuits)
    total_test_damage = sum(test_damage.values())
    top_decile_hit_rate = (damage_in_top / total_test_damage) if total_test_damage else None

    return {
        "cutoff_date": BACKTEST_CUTOFF,
        "train_record_count": len(train),
        "test_record_count": len(test),
        "circuits_evaluated": len(circuits),
        "spearman_rank_correlation": round(rho, 3) if rho is not None else None,
        "top_decile_circuit_count": top_n,
        "top_decile_hit_rate": round(top_decile_hit_rate, 3) if top_decile_hit_rate is not None else None,
        "top_decile_expected_by_chance": round(top_n / len(circuits), 3),
        "interpretation": None,  # filled in main()
    }


def main():
    crosswalk, ambiguous_pairs = build_circuit_crosswalk()
    customer_count, asset_count = build_exposure_counts()
    damage_records = load_damage_records()

    joined, unmapped = [], []
    unmapped_pairs_seen = {}
    for r in damage_records:
        key = (r.get("Substation"), r.get("Circuit"))
        asset_type = ARCOS_ASSET_TYPE_MAP.get(r.get("Asset_Type"))
        if key in crosswalk:
            joined.append({"circuit_id": crosswalk[key], "asset_type": asset_type, "record": r})
        else:
            unmapped.append(r)
            unmapped_pairs_seen[key] = unmapped_pairs_seen.get(key, 0) + 1

    unrepaired_with_date = sum(
        1 for r in damage_records if r.get("Repaired") == "No" and (r.get("Repaired_D") or "").strip()
    )
    unrepaired_total = sum(1 for r in damage_records if r.get("Repaired") == "No")

    # --- overall per-circuit rate (all joined damage / customer exposure) ---
    all_circuits = sorted(customer_count.keys())
    overall_damage = {}
    for j in joined:
        overall_damage[j["circuit_id"]] = overall_damage.get(j["circuit_id"], 0) + 1

    overall_fit = eb_fit([(overall_damage.get(c, 0), customer_count[c]) for c in all_circuits])
    overall_shrunk = {c: shrink(overall_damage.get(c, 0), customer_count[c], overall_fit) for c in all_circuits}
    overall_thresholds = band_thresholds(overall_shrunk.values())

    circuits_out = {}
    for c in all_circuits:
        circuits_out[c] = {
            "customer_exposure": customer_count[c],
            "damage_count": overall_damage.get(c, 0),
            "raw_rate": round(overall_damage.get(c, 0) / customer_count[c], 6),
            "shrunk_rate": round(overall_shrunk[c], 6),
            "band": band_for_rate(overall_shrunk[c], overall_thresholds),
            "confidence": confidence_tier(customer_count[c], overall_fit["beta"]),
            "by_asset_type": {},
        }

    # --- per-asset-type rate, for the 6 reliably-joined asset types ---
    per_type_fits = {}
    for asset_type in RELIABLE_ASSET_TABLES:
        type_damage = {}
        for j in joined:
            if j["asset_type"] == asset_type:
                type_damage[j["circuit_id"]] = type_damage.get(j["circuit_id"], 0) + 1
        type_circuits = sorted(cid for cid, counts in asset_count.items() if asset_type in counts)
        if not type_circuits:
            continue
        fit = eb_fit([(type_damage.get(c, 0), asset_count[c][asset_type]) for c in type_circuits])
        per_type_fits[asset_type] = fit
        shrunk_map = {c: shrink(type_damage.get(c, 0), asset_count[c][asset_type], fit) for c in type_circuits}
        thresholds = band_thresholds(shrunk_map.values())
        for c in type_circuits:
            if c not in circuits_out:
                continue
            circuits_out[c]["by_asset_type"][asset_type] = {
                "exposure": asset_count[c][asset_type],
                "damage_count": type_damage.get(c, 0),
                "raw_rate": round(type_damage.get(c, 0) / asset_count[c][asset_type], 6),
                "shrunk_rate": round(shrunk_map[c], 6),
                "band": band_for_rate(shrunk_map[c], thresholds),
                "confidence": confidence_tier(asset_count[c][asset_type], fit["beta"]),
            }

    model = {
        "method": (
            "Exposure-normalized historical damage rate per circuit (damage records / asset count on "
            "that circuit), smoothed with Poisson-Gamma empirical-Bayes shrinkage toward the system-wide "
            "rate (method-of-moments fit). Never a calibrated outage probability — a relative historical "
            "rate used only to rank circuits Low/Moderate/High."
        ),
        "storm_multiplier": STORM_MULTIPLIER,
        "storm_multiplier_note": STORM_MULTIPLIER_NOTE,
        "overall": {
            "system_rate": round(overall_fit["system_rate"], 6),
            "eb_alpha": round(overall_fit["alpha"], 4),
            "eb_beta": round(overall_fit["beta"], 2),
            "band_thresholds": {k: round(v, 6) for k, v in overall_thresholds.items()},
            "confidence_thresholds": {
                "low_max_exposure": round(overall_fit["beta"], 1),
                "medium_max_exposure": round(5 * overall_fit["beta"], 1),
            },
        },
        "by_asset_type_system": {
            t: {"system_rate": round(f["system_rate"], 6), "eb_beta": round(f["beta"], 2)}
            for t, f in per_type_fits.items()
        },
        "circuits": circuits_out,
    }

    backtest = run_backtest(damage_records, crosswalk, customer_count)
    rho = backtest["spearman_rank_correlation"]
    if rho is None:
        interpretation = "Not enough post-cutoff data to evaluate."
    elif rho >= 0.4:
        interpretation = f"Moderate-to-strong signal (rho={rho}): pre-storm rate ranking carried into the storm."
    elif rho >= 0.15:
        interpretation = f"Weak but positive signal (rho={rho}) — better than chance, not strong enough to lean on alone."
    else:
        interpretation = (
            f"Weak signal (rho={rho}). Honestly: with one dominant storm event and ~29 damaged circuits "
            "in this sample, pre-storm damage history barely predicts which circuits the storm hits. "
            "Treat the risk band as a starting point for conversation, not a forecast."
        )
    backtest["interpretation"] = interpretation

    data_quality = {
        "circuit_crosswalk": {
            "method": "Union of (station, circuit, circuit_id) triples from Transformer/Primary/Secondary/Fuse Bank/Recloser Bank/Switch tables.",
            "unique_pairs_mapped": len(crosswalk),
            "ambiguous_pairs_excluded": ambiguous_pairs,
            "ambiguous_pair_count": len(ambiguous_pairs),
        },
        "damage_join": {
            "total_damage_records": len(damage_records),
            "joined": len(joined),
            "unmapped": len(unmapped),
            "unmapped_station_circuit_pairs": [
                {"station": k[0], "circuit": k[1], "record_count": v}
                for k, v in sorted(unmapped_pairs_seen.items(), key=lambda kv: -kv[1])
            ],
        },
        "unrepaired_with_repair_date": {
            "count": unrepaired_with_date,
            "of_unrepaired_total": unrepaired_total,
            "note": "Repaired=No records all carry a non-blank Repaired_D — almost certainly the extract's snapshot date, not a real completion date. Never read for unrepaired records.",
        },
        "near_fid_not_used": "NEAR_FID is a spatial-join artifact in the damage extract and is not used anywhere in this join.",
        "pole_and_rare_types_no_exposure_table": (
            "Pole, Capacitor Bank, Light, and Step Transformer damage counts toward each circuit's "
            "OVERALL rate but have no independent per-circuit exposure table, so they get no "
            "per-asset-type rate of their own."
        ),
    }

    OUT.mkdir(exist_ok=True)
    (OUT / "risk_model.json").write_text(json.dumps(model, indent=2))
    (OUT / "backtest.json").write_text(json.dumps(backtest, indent=2))
    (OUT / "data_quality.json").write_text(json.dumps(data_quality, indent=2))

    print(f"Wrote {OUT/'risk_model.json'} ({len(circuits_out)} circuits)")
    print(f"Wrote {OUT/'backtest.json'}")
    print(f"Wrote {OUT/'data_quality.json'}")
    print(f"Backtest: {backtest['interpretation']}")
    print(f"Join: {len(joined)}/{len(damage_records)} damage records joined, {len(unmapped)} unmapped, {len(ambiguous_pairs)} ambiguous pairs excluded")


if __name__ == "__main__":
    main()
