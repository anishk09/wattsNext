import unittest
from unittest import mock

from concierge import chat


class ThoughtSignaturePreservation(unittest.TestCase):
    """Gemini attaches a thoughtSignature alongside a functionCall part;
    it must be sent back byte-for-byte on the follow-up turn or the model
    loses its reasoning context. online_reply() must reuse gemini.generate's
    raw `parts` list for the model-role turn, never rebuild one from just
    the parsed function_calls."""

    def test_thought_signature_is_preserved_in_the_follow_up_turn(self):
        first_response = {
            "text": "",
            "function_calls": [{"name": "get_risk", "args": {"household_id": "h1"}}],
            "parts": [
                {"functionCall": {"name": "get_risk", "args": {"household_id": "h1"}}, "thoughtSignature": "opaque-signature-xyz"},
            ],
        }
        second_response = {"text": "Risk is High.", "function_calls": [], "parts": [{"text": "Risk is High."}]}

        captured_contents = []

        def fake_generate(api_key, model, contents, function_declarations):
            if len(captured_contents) == 0:
                captured_contents.append([dict(c) for c in contents])
                return first_response
            captured_contents.append([dict(c) for c in contents])
            return second_response

        with mock.patch("concierge.chat.gemini.generate", side_effect=fake_generate):
            result = chat.online_reply(
                "fake-key", "gemini-flash-latest", "Will I lose power?", "h1",
                {"access_blocked": False, "extra_crews": 0, "repairs_complete": False}, [],
            )

        self.assertEqual(result["text"], "Risk is High.")
        # The second call's `contents` must include the exact model-role
        # turn from the first response, thoughtSignature included.
        second_call_contents = captured_contents[1]
        model_turns = [c for c in second_call_contents if c["role"] == "model"]
        self.assertEqual(len(model_turns), 1)
        self.assertEqual(model_turns[0]["parts"], first_response["parts"])
        self.assertIn("thoughtSignature", model_turns[0]["parts"][0])
        self.assertEqual(model_turns[0]["parts"][0]["thoughtSignature"], "opaque-signature-xyz")

    def test_retry_path_also_preserves_parts(self):
        # The validator-rejection retry branch rebuilds the model turn
        # from response["text"] alone in the old code — same bug, same fix.
        first_response = {"text": "", "function_calls": [{"name": "get_risk", "args": {"household_id": "h1"}}],
                           "parts": [{"functionCall": {"name": "get_risk", "args": {}}, "thoughtSignature": "sig-1"}]}
        tool_response = {"text": "There is a 95% chance.", "function_calls": [],
                          "parts": [{"text": "There is a 95% chance.", "thoughtSignature": "sig-2"}]}
        corrected_response = {"text": "Risk is High.", "function_calls": [], "parts": [{"text": "Risk is High."}]}

        calls = [first_response, tool_response, corrected_response]
        captured = []

        def fake_generate(api_key, model, contents, function_declarations):
            captured.append([dict(c) for c in contents])
            return calls.pop(0)

        with mock.patch("concierge.chat.gemini.generate", side_effect=fake_generate):
            result = chat.online_reply(
                "fake-key", "gemini-flash-latest", "Will I lose power?", "h1",
                {"access_blocked": False, "extra_crews": 0, "repairs_complete": False}, [],
            )

        self.assertEqual(result["text"], "Risk is High.")
        third_call_contents = captured[2]
        model_turns = [c for c in third_call_contents if c["role"] == "model"]
        self.assertTrue(any(p.get("thoughtSignature") == "sig-2" for turn in model_turns for p in turn["parts"]))


if __name__ == "__main__":
    unittest.main()
