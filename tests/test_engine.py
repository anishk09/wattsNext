import unittest

from concierge import cases, engine, tools


class TransformerAcceptanceRanges(unittest.TestCase):
    """CLAUDE.md acceptance tests: must match exactly."""

    def setUp(self):
        self.case = cases.get_case("transformer_roanoke")

    def test_baseline_range(self):
        result = engine.restoration_effort(self.case)
        self.assertEqual(result["low_hours"], 6.7)
        self.assertEqual(result["high_hours"], 13.5)

    def test_blocked_access_range(self):
        result = engine.restoration_effort(self.case, access_blocked=True)
        self.assertEqual(result["low_hours"], 9.7)
        self.assertEqual(result["high_hours"], 16.5)


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
        self.assertGreater(estimate["high_hours"], 0)

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
        self.assertEqual(result["low_hours"], 0.0)
        self.assertEqual(result["high_hours"], 0.0)

    def test_tool_layer_reflects_repairs_complete(self):
        result = tools.get_restoration_estimate("h1", repairs_complete=True)
        self.assertEqual(result["reference_effort_hours"]["value"], 0.0)


class ExtraCrewsShortenMultiJobCase(unittest.TestCase):
    def test_more_crews_do_not_increase_makespan(self):
        case = cases.get_case("wirepole_vinton")
        baseline = engine.restoration_effort(case, extra_crews=0)
        with_crews = engine.restoration_effort(case, extra_crews=2)
        self.assertLessEqual(with_crews["reference_effort_hours"], baseline["reference_effort_hours"])


if __name__ == "__main__":
    unittest.main()
