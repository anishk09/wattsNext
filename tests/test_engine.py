import unittest

from concierge import cases, engine, tools


class TransformerAcceptanceRanges(unittest.TestCase):
    """
    Original CLAUDE.md acceptance numbers (fixed 75%-150% band):
    baseline 6.7-13.5 h, blocked access 9.7-16.5 h.

    Step 3 replaced that flat band with a seeded Monte Carlo over labor
    hours (triangular(0.6x, 1.0x, 1.8x) per job — wider and right-skewed
    versus the old symmetric-looking 0.75x-1.5x multiply) and crew
    availability (a 0-1.5 h dispatch/travel delay per crew). Both the
    reference effort (9.0 h, unchanged — same labor-workbook math as
    before) and the shape of the new distribution explain the shift:
    P10 (8.1 h) sits ABOVE the old low end (6.7 h) because the crew-delay
    term has no symmetric downside, and the triangular's long right tail
    pulls P50/P90 up a bit versus the old flat multiply. The new window
    is narrower (8.1-14.0 vs 6.7-13.5) but shifted later — a materially
    different, better-justified range, not the same numbers relabeled.
    """

    def setUp(self):
        self.case = cases.get_case("transformer_roanoke")

    def test_baseline_range(self):
        result = engine.restoration_effort(self.case)
        self.assertEqual(result["p10_hours"], 8.1)
        self.assertEqual(result["p50_hours"], 10.8)
        self.assertEqual(result["p90_hours"], 14.0)

    def test_blocked_access_range(self):
        result = engine.restoration_effort(self.case, access_blocked=True)
        self.assertEqual(result["p10_hours"], 11.1)
        self.assertEqual(result["p50_hours"], 13.7)
        self.assertEqual(result["p90_hours"], 17.1)

    def test_seeded_monte_carlo_is_reproducible(self):
        # Same case + scenario must always give the same P10/P50/P90 —
        # "seeded," not fresh noise every call, even across process restarts.
        first = engine.restoration_effort(self.case)
        second = engine.restoration_effort(self.case)
        self.assertEqual(first, second)

    def test_different_scenarios_get_different_seeds(self):
        baseline = engine.restoration_effort(self.case)
        blocked = engine.restoration_effort(self.case, access_blocked=True)
        more_crews = engine.restoration_effort(self.case, extra_crews=2)
        self.assertNotEqual(baseline["p50_hours"], blocked["p50_hours"])
        self.assertNotEqual(baseline, more_crews)


class ConfidenceLevels(unittest.TestCase):
    def test_high_when_exposure_is_large(self):
        # STATION24/CIR114 (transformer_roanoke) has ~1900 customers of
        # exposure behind its historical rate — well past the EB beta
        # threshold, so confidence is no longer capped at Medium the way
        # the old rule-based model always capped it.
        case = cases.get_case("transformer_roanoke")
        self.assertEqual(engine.confidence(case)["level"], "High")

    def test_low_when_access_blocked(self):
        case = cases.get_case("transformer_roanoke")
        self.assertEqual(engine.confidence(case, access_blocked=True)["level"], "Low")

    def test_low_when_path_invalid(self):
        case = cases.get_case("no_path")
        self.assertEqual(engine.confidence(case)["level"], "Low")


class FallbackRule(unittest.TestCase):
    def test_no_path_triggers_fallback(self):
        case = cases.get_case("no_path")
        result = engine.check_fallback(case)
        self.assertTrue(result["fallback"])
        self.assertTrue(result["reason"])

    def test_valid_case_no_fallback(self):
        case = cases.get_case("transformer_roanoke")
        result = engine.check_fallback(case)
        self.assertFalse(result["fallback"])

    def test_tool_layer_returns_fallback_for_household(self):
        result = tools.get_risk("h12")
        self.assertTrue(result["fallback"]["fallback"])


class RiskBand(unittest.TestCase):
    """Historical-rate model: exposure-normalized damage rate, empirical-Bayes
    shrunk toward the system-wide rate, scaled by storm setting, banded by
    fixed thresholds. Replaces the old 'any unrepaired damage => High' rule."""

    def test_high_damage_circuit_is_high(self):
        # STATION2/CIR60 (wire_montvale) really does have an elevated
        # historical rate (25/1233 joined damage records vs a 0.0092
        # system-wide rate) — this one happens to agree with the old rule,
        # but for the real reason now: a measured rate, not "any damage present".
        case = cases.get_case("wire_montvale")
        self.assertEqual(engine.risk_band(case)["band"], "High")

    def test_calm_no_damage_is_low(self):
        case = cases.get_case("calm_roanoke")
        self.assertEqual(engine.risk_band(case)["band"], "Low")

    def test_repairs_complete_is_low(self):
        case = cases.get_case("transformer_roanoke")
        self.assertEqual(engine.risk_band(case, repairs_complete=True)["band"], "Low")

    def test_severe_storm_multiplier_can_push_band_up(self):
        base = engine.risk_band(cases.get_case("transformer_roanoke"))
        self.assertGreater(base["storm_multiplier"], 1.0)  # severe scales the rate up, a stated assumption

    def test_shrinkage_pulls_toward_system_rate(self):
        # A circuit identical to the system rate (0 damage, small exposure)
        # should land very close to the system rate once shrunk — the EB
        # math, not a specific circuit's story.
        model = engine._risk_model
        system_rate = model["overall"]["system_rate"]
        small_circuit = min(
            (c for c in model["circuits"].values() if c["damage_count"] == 0),
            key=lambda c: c["customer_exposure"],
        )
        self.assertAlmostEqual(small_circuit["shrunk_rate"], system_rate, delta=system_rate * 0.5)


class RiskFallback(unittest.TestCase):
    def test_ambiguous_circuit_label_triggers_risk_fallback(self):
        # STATION29/CIR6 (wirepole_vinton) maps to two different circuit_ids
        # across the asset tables — excluded from the historical model, so
        # risk (not restoration) must honestly fall back.
        case = cases.get_case("wirepole_vinton")
        self.assertEqual(case["risk_status"], "ambiguous_circuit_label")
        result = engine.check_risk_fallback(case)
        self.assertTrue(result["fallback"])
        self.assertIn("ambiguous", result["reason"])

    def test_restoration_still_works_when_risk_is_in_fallback(self):
        # The scenario-based restoration estimate doesn't depend on the
        # population-level historical rate, so it should be unaffected.
        case = cases.get_case("wirepole_vinton")
        self.assertFalse(engine.check_fallback(case)["fallback"])
        estimate = engine.restoration_effort(case)
        self.assertGreater(estimate["p90_hours"], 0)

    def test_tool_layer_falls_back_for_ambiguous_circuit(self):
        result = tools.get_risk("h4")  # household on wirepole_vinton
        self.assertTrue(result["fallback"]["fallback"])

    def test_tool_layer_restoration_still_works_for_ambiguous_circuit(self):
        result = tools.get_restoration_estimate("h4")
        self.assertFalse(result["fallback"]["fallback"])


class RestorationCompleteFlow(unittest.TestCase):
    def test_repairs_complete_zeroes_the_estimate(self):
        case = cases.get_case("transformer_roanoke")
        result = engine.restoration_effort(case, repairs_complete=True)
        self.assertEqual(result["p10_hours"], 0.0)
        self.assertEqual(result["p90_hours"], 0.0)

    def test_tool_layer_reflects_repairs_complete(self):
        result = tools.get_restoration_estimate("h1", repairs_complete=True)
        self.assertEqual(result["reference_effort_hours"]["value"], 0.0)


class StepRestoration(unittest.TestCase):
    """Real demo cases only ever have transformer/primary/pole damage, which
    this model conservatively treats as always-local (no finer position data
    in the source), so they don't exercise the filtering. These tests build
    a synthetic case with a real-shaped upstream_chain and device-type damage
    to prove the mechanism itself: damage beyond the nearest closed device
    must not extend the household's restoration time."""

    def _synthetic_case(self, damage_items):
        return {
            "damage_items": damage_items,
            "upstream_chain": [
                {"source": "eo_power_xfrmr_inst", "description": "Distribution", "normal_status": "unknown"},
                {"source": "eo_isolating_eqpt_inst", "description": "Fuse", "normal_status": "Closed"},
                {"source": "eo_isolating_eqpt_inst", "description": "Recloser (Hydraulic)", "normal_status": "Closed"},
                {"source": "eo_circuit", "description": "Circuit Breaker", "normal_status": "unknown"},
            ],
        }

    def test_damage_beyond_nearest_closed_device_is_excluded(self):
        case = self._synthetic_case([
            {"asset_type": "transformer", "quantity": 1, "size_kva": 25},  # always local
            {"asset_type": "recloser_bank", "quantity": 1},  # matches the 2nd device, beyond the 1st (nearest closed)
        ])
        phases = engine.restoration_phases(case)
        self.assertEqual([d["asset_type"] for d in phases["local"]], ["transformer"])
        self.assertEqual([d["asset_type"] for d in phases["upstream"]], ["recloser_bank"])
        self.assertEqual(phases["nearest_closed_device"], "Fuse")

    def test_upstream_damage_does_not_extend_restoration_time(self):
        local_only = self._synthetic_case([{"asset_type": "transformer", "quantity": 1, "size_kva": 25}])
        with_upstream = self._synthetic_case([
            {"asset_type": "transformer", "quantity": 1, "size_kva": 25},
            {"asset_type": "recloser_bank", "quantity": 1},
        ])
        self.assertEqual(
            engine.restoration_effort(local_only)["reference_effort_hours"],
            engine.restoration_effort(with_upstream)["reference_effort_hours"],
        )

    def test_damage_matching_the_nearest_device_itself_is_local(self):
        # A fault ON the nearest closed device (not beyond it) still blocks the household.
        case = self._synthetic_case([{"asset_type": "fuse_bank", "quantity": 1}])
        phases = engine.restoration_phases(case)
        self.assertEqual(len(phases["local"]), 1)
        self.assertEqual(len(phases["upstream"]), 0)

    def test_no_chain_available_treats_everything_as_local(self):
        case = {"damage_items": [{"asset_type": "recloser_bank", "quantity": 1}], "upstream_chain": None}
        phases = engine.restoration_phases(case)
        self.assertEqual(len(phases["local"]), 1)
        self.assertFalse(phases["chain_available"])

    def test_real_cases_have_a_chain_and_only_local_damage(self):
        # Document the honest outcome for the actual demo data: the mechanism
        # is live, but none of the 4 real cases have device-type damage, so
        # restoration numbers are unchanged from before this feature existed.
        for case_id in ("transformer_roanoke", "wirepole_vinton", "wire_montvale"):
            case = cases.get_case(case_id)
            self.assertIsNotNone(case["upstream_chain"])
            phases = engine.restoration_phases(case)
            self.assertEqual(phases["local"], case["damage_items"])
            self.assertEqual(phases["upstream"], [])


class ExtraCrewsShortenMultiJobCase(unittest.TestCase):
    def test_more_crews_do_not_increase_makespan(self):
        case = cases.get_case("wirepole_vinton")
        baseline = engine.restoration_effort(case, extra_crews=0)
        with_crews = engine.restoration_effort(case, extra_crews=2)
        self.assertLessEqual(with_crews["reference_effort_hours"], baseline["reference_effort_hours"])


class MonteCarloMechanism(unittest.TestCase):
    """Engine-level checks on the simulation itself, not just the one
    acceptance case's exact numbers."""

    def test_percentiles_are_ordered(self):
        for case_id in ("transformer_roanoke", "wirepole_vinton", "wire_montvale"):
            result = engine.restoration_effort(cases.get_case(case_id))
            self.assertLessEqual(result["p10_hours"], result["p50_hours"])
            self.assertLessEqual(result["p50_hours"], result["p90_hours"])

    def test_more_runs_converge_toward_fewer_runs(self):
        # Sanity check on the simulation itself: raising MC_RUNS shouldn't
        # move the percentiles by much for a single-job case.
        case = cases.get_case("transformer_roanoke")
        jobs = engine._jobs(engine.restoration_phases(case)["local"])
        rng_small = engine.random.Random(1)
        small = sorted(engine._simulate_makespan(rng_small, jobs, 1) for _ in range(200))
        rng_large = engine.random.Random(1)
        large = sorted(engine._simulate_makespan(rng_large, jobs, 1) for _ in range(5000))
        self.assertAlmostEqual(
            engine._percentile(small, 0.5), engine._percentile(large, 0.5), delta=1.5
        )

    def test_empty_damage_items_give_zero_for_every_percentile(self):
        case = cases.get_case("calm_roanoke")
        result = engine.restoration_effort(case)
        self.assertEqual((result["p10_hours"], result["p50_hours"], result["p90_hours"]), (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
