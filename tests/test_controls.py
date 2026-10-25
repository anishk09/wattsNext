import unittest

from concierge import cases, chat, privacy, validator


class AnswerValidator(unittest.TestCase):
    def test_empty_cards_is_trivially_valid(self):
        result = validator.validate_reply("I don't have that data.", {})
        self.assertTrue(result["valid"])

    def test_number_not_in_tool_output_is_rejected(self):
        result = validator.validate_reply("There is a 95% chance.", {"risk": {"a": 1}})
        self.assertFalse(result["valid"])
        self.assertIn("95", result["unverified"])

    def test_band_word_not_in_tool_output_is_rejected(self):
        result = validator.validate_reply("Risk is Moderate.", {"risk": {"band": "High"}})
        self.assertFalse(result["valid"])
        self.assertIn("Moderate", result["unverified"])

    def test_range_hyphen_is_not_mistaken_for_a_negative_number(self):
        # "8.1-14.0" is the range 8.1 to 14.0, not 8.1 and -14.0.
        result = validator.validate_reply("Estimated restoration: 8.1-14.0 hours.", {"restoration": {"p10_hours": {"value": 8.1}, "p90_hours": {"value": 14.0}}})
        self.assertTrue(result["valid"])
        self.assertEqual(result["unverified"], [])

    def test_all_real_offline_replies_validate_clean(self):
        # The offline templates are built directly from tool output, so
        # this is a regression guard: if a future edit adds a number to
        # the text that isn't also in the cards, this catches it.
        scenarios = [
            {"access_blocked": False, "extra_crews": 0, "repairs_complete": False},
            {"access_blocked": True, "extra_crews": 0, "repairs_complete": False},
            {"access_blocked": False, "extra_crews": 2, "repairs_complete": False},
            {"access_blocked": False, "extra_crews": 0, "repairs_complete": True},
        ]
        messages = [
            "Will I lose power and for how long?",
            "How long could repairs take?",
            "What should I do to prepare?",
            "Do I qualify for outage alerts?",
        ]
        for household in cases.list_households():
            for scenario in scenarios:
                for message in messages:
                    reply = chat.offline_reply(message, household["household_id"], scenario)
                    result = validator.validate_reply(reply["text"], reply["cards"])
                    self.assertTrue(
                        result["valid"],
                        f"{household['household_id']} / {scenario} / {message!r}: unverified {result['unverified']} in {reply['text']!r}",
                    )


class PrivacyFilter(unittest.TestCase):
    def test_legitimate_restoration_text_passes_through_unchanged(self):
        text = "Risk is High (High confidence). Estimated restoration: 8.1-14.0 hours (median 10.8)."
        clean, violations = privacy.scrub(text)
        self.assertEqual(clean, text)
        self.assertEqual(violations, [])

    def test_premise_number_is_redacted(self):
        clean, violations = privacy.scrub("Premise 247057282 is affected.")
        self.assertNotIn("247057282", clean)
        self.assertTrue(violations)

    def test_equipment_location_code_is_redacted(self):
        clean, violations = privacy.scrub("Device at 37800343D00129 tripped.")
        self.assertNotIn("37800343D00129", clean)
        self.assertTrue(violations)

    def test_coordinate_is_redacted(self):
        clean, violations = privacy.scrub("Located at -80.2125770318, 37.2341816484.")
        self.assertNotIn("80.2125770318", clean)
        self.assertNotIn("37.2341816484", clean)
        self.assertTrue(violations)

    def test_facility_keyword_is_redacted(self):
        clean, violations = privacy.scrub("Power is also out at the hospital.")
        self.assertNotIn("hospital", clean.lower())
        self.assertTrue(violations)

    def test_empty_text_is_a_no_op(self):
        clean, violations = privacy.scrub("")
        self.assertEqual(clean, "")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
