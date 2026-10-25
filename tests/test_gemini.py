import unittest
from unittest import mock

from concierge import gemini


class ErrorCategorization(unittest.TestCase):
    def _http_error(self, code):
        err = mock.Mock()
        err.code = code
        err.read.return_value = b"error body"
        return err

    def test_404_is_model_unavailable(self):
        self.assertEqual(gemini._categorize_http_error(self._http_error(404)), "model_unavailable")

    def test_429_is_quota(self):
        self.assertEqual(gemini._categorize_http_error(self._http_error(429)), "quota")

    def test_403_is_permission(self):
        self.assertEqual(gemini._categorize_http_error(self._http_error(403)), "permission")

    def test_503_is_unavailable(self):
        self.assertEqual(gemini._categorize_http_error(self._http_error(503)), "unavailable")


class RequestErrorHandling(unittest.TestCase):
    """_request() crashed the server's startup lifespan the first time it
    ran against a real network: urlopen raised a raw socket TimeoutError,
    which only urllib.error.HTTPError/URLError were being caught for.
    Every low-level failure mode must degrade to ProviderError, never
    propagate — this client exists specifically so a flaky connection
    never takes the whole app down."""

    def test_socket_timeout_becomes_a_provider_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(gemini.ProviderError) as ctx:
                gemini._request("models", "fake-key")
        self.assertEqual(ctx.exception.category, "unavailable")

    def test_generic_os_error_becomes_a_provider_error(self):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("network unreachable")):
            with self.assertRaises(gemini.ProviderError) as ctx:
                gemini._request("models", "fake-key")
        self.assertEqual(ctx.exception.category, "unavailable")


class PinModel(unittest.TestCase):
    def test_allowlist_is_gemini_flash_latest_only(self):
        # Pinned from a live test: gemini-2.5-flash is listed but 404s on
        # generateContent ("no longer available to new users") — listed
        # availability and real availability aren't the same thing.
        self.assertEqual(gemini.ALLOWLIST, ["gemini-flash-latest"])
        self.assertFalse(any(m.startswith("gemini-2.5") for m in gemini.ALLOWLIST))

    def test_model_listed_but_404_on_generate_raises_model_unavailable_not_generic(self):
        with mock.patch.object(gemini, "list_models", return_value=["gemini-flash-latest"]):
            with mock.patch.object(gemini, "_request") as mock_request:
                def side_effect(path, api_key, method="GET", body=None, timeout=15):
                    if "generateContent" in path:
                        raise gemini.ProviderError("model_unavailable", "gemini-flash-latest is no longer available to new users")
                    return {"models": []}
                mock_request.side_effect = side_effect
                with self.assertRaises(gemini.ProviderError) as ctx:
                    gemini.pin_model("fake-key")
        self.assertEqual(ctx.exception.category, "model_unavailable")
        self.assertIn("no longer available", ctx.exception.message)

    def test_model_not_in_available_list_is_model_unavailable(self):
        with mock.patch.object(gemini, "list_models", return_value=["some-other-model"]):
            with self.assertRaises(gemini.ProviderError) as ctx:
                gemini.pin_model("fake-key")
        self.assertEqual(ctx.exception.category, "model_unavailable")

    def test_real_round_trip_pins_the_model(self):
        with mock.patch.object(gemini, "list_models", return_value=["gemini-flash-latest"]):
            with mock.patch.object(gemini, "_tool_round_trip_ok", return_value=True):
                self.assertEqual(gemini.pin_model("fake-key"), "gemini-flash-latest")

    def test_empty_response_parts_is_rejected_not_accepted(self):
        # "accept the model only if it actually answers" — a 200 with
        # candidates but no parts must not count as success.
        with mock.patch.object(gemini, "_request", return_value={"candidates": [{"content": {"parts": []}}]}):
            self.assertFalse(gemini._tool_round_trip_ok("gemini-flash-latest", "fake-key"))


if __name__ == "__main__":
    unittest.main()
