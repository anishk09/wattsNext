import unittest
from unittest import mock

from starlette.testclient import TestClient

import server
from concierge import gemini


class ChatFlow(unittest.TestCase):
    def setUp(self):
        server.SETTINGS["offline_mode"] = True
        server.SETTINGS["api_key"] = None
        server.SETTINGS["model"] = None
        self.client = TestClient(server.app)
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        self.session_id = resp.json()["session_id"]

    def test_offline_mode_is_labeled(self):
        resp = self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Will I lose power?"})
        body = resp.json()
        self.assertTrue(body["offline"])
        self.assertIn("risk", body["cards"])

    def test_live_data_question_is_refused_honestly(self):
        resp = self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Is the shelter on Main St open?"})
        body = resp.json()
        self.assertIn("redcross.org", body["text"])
        self.assertEqual(body["cards"], {})

    def test_fallback_household_gets_fallback_response(self):
        resp = self.client.post("/api/session", json={"household_id": "h12"})
        session_id = resp.json()["session_id"]
        resp = self.client.post("/api/chat", json={"session_id": session_id, "message": "Will I lose power?"})
        self.assertTrue(resp.json()["fallback"])

    def test_risk_fallback_on_ambiguous_circuit_does_not_crash_the_chat(self):
        # h4 sits on a circuit the historical risk model can't trust
        # (STATION29/CIR6 maps ambiguously), but path_valid is still true,
        # so the top-level household fallback check doesn't catch it —
        # this is the per-card fallback the offline renderer must handle.
        resp = self.client.post("/api/session", json={"household_id": "h4"})
        session_id = resp.json()["session_id"]
        resp = self.client.post("/api/chat", json={"session_id": session_id, "message": "Will I lose power and for how long?"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["cards"]["risk"]["fallback"]["fallback"])
        self.assertIn("ambiguous", body["text"])
        self.assertFalse(body["cards"]["restoration"]["fallback"]["fallback"])


class WhatIfFlow(unittest.TestCase):
    def setUp(self):
        server.SETTINGS["offline_mode"] = True
        self.client = TestClient(server.app)
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        self.session_id = resp.json()["session_id"]

    def test_block_access_moves_the_range_and_shows_before_after(self):
        resp = self.client.post("/api/whatif", json={"session_id": self.session_id, "action": "block_access"})
        body = resp.json()
        self.assertEqual(body["before"]["p10_hours"]["value"], 8.1)
        self.assertEqual(body["after"]["p10_hours"]["value"], 11.1)

    def test_complete_repairs_triggers_restoration_complete_message(self):
        resp = self.client.post("/api/whatif", json={"session_id": self.session_id, "action": "complete_repairs"})
        body = resp.json()
        previews = body["alerts"]["message_previews"]
        self.assertTrue(any(p["type"] == "restoration_complete" for p in previews))


class SettingsEndpoint(unittest.TestCase):
    def test_bad_key_reports_honest_error_and_offers_offline(self):
        client = TestClient(server.app)
        resp = client.post("/api/settings", json={"api_key": "not-a-real-key"})
        self.assertEqual(resp.status_code, 502)
        self.assertTrue(resp.json()["offer_offline"])

    def test_non_bool_offline_mode_is_rejected(self):
        client = TestClient(server.app)
        resp = client.post("/api/settings", json={"offline_mode": "yes"})
        self.assertEqual(resp.status_code, 400)


class InputValidation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_session_requires_known_household(self):
        resp = self.client.post("/api/session", json={"household_id": "not-a-real-household"})
        self.assertEqual(resp.status_code, 400)

    def test_session_rejects_non_string_household_id(self):
        resp = self.client.post("/api/session", json={"household_id": 123})
        self.assertEqual(resp.status_code, 400)

    def test_session_rejects_non_object_body(self):
        resp = self.client.post("/api/session", json=["not", "an", "object"])
        self.assertEqual(resp.status_code, 400)

    def test_chat_rejects_empty_message(self):
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        session_id = resp.json()["session_id"]
        resp = self.client.post("/api/chat", json={"session_id": session_id, "message": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_chat_rejects_oversized_message(self):
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        session_id = resp.json()["session_id"]
        resp = self.client.post("/api/chat", json={"session_id": session_id, "message": "x" * 3000})
        self.assertEqual(resp.status_code, 400)

    def test_whatif_rejects_unknown_action(self):
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        session_id = resp.json()["session_id"]
        resp = self.client.post("/api/whatif", json={"session_id": session_id, "action": "delete_everything"})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_session_id_is_404_not_500(self):
        resp = self.client.post("/api/chat", json={"session_id": "nonexistent", "message": "hi"})
        self.assertEqual(resp.status_code, 404)


class NoSilentOfflineFallback(unittest.TestCase):
    """A failed connection attempt (startup .env, or a manual key) must
    never silently drop to offline mode — the customer gets the same
    honest-error-plus-offer-offline response as a failure mid-chat."""

    def setUp(self):
        self.client = TestClient(server.app)
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        self.session_id = resp.json()["session_id"]

    def tearDown(self):
        server.SETTINGS.update({"api_key": None, "model": None, "offline_mode": False, "last_error": None, "key_source": None})

    def test_failed_connection_surfaces_honest_error_not_silent_offline(self):
        server.SETTINGS["offline_mode"] = False
        server.SETTINGS["api_key"] = None
        server.SETTINGS["model"] = None
        server.SETTINGS["last_error"] = {"category": "model_unavailable", "message": "gemini-flash-latest is no longer available to new users"}

        resp = self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Will I lose power?"})
        self.assertEqual(resp.status_code, 502)
        body = resp.json()
        self.assertTrue(body["offer_offline"])
        self.assertEqual(body["category"], "model_unavailable")
        self.assertIn("no longer available", body["message"])

    def test_explicit_offline_mode_still_works_normally(self):
        server.SETTINGS["offline_mode"] = True
        server.SETTINGS["last_error"] = {"category": "model_unavailable", "message": "irrelevant, offline was chosen"}
        resp = self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Will I lose power?"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["offline"])

    def test_never_attempted_no_key_anywhere_is_a_normal_offline_answer(self):
        server.SETTINGS["offline_mode"] = False
        server.SETTINGS["api_key"] = None
        server.SETTINGS["model"] = None
        server.SETTINGS["last_error"] = None
        resp = self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Will I lose power?"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["offline"])


class EnvAutoConnect(unittest.TestCase):
    """_connect_from_env() is only ever wired to real server startup via the
    lifespan context manager (confirmed separately: a bare TestClient(app),
    as used everywhere else in this file, never drives it) — these tests
    call it directly, with the network call mocked, to check its own logic."""

    def tearDown(self):
        server.SETTINGS.update({"api_key": None, "model": None, "offline_mode": False, "last_error": None, "key_source": None})

    def test_no_key_leaves_settings_untouched(self):
        with mock.patch("concierge.env_config.get_gemini_api_key", return_value=None):
            server._connect_from_env()
        self.assertIsNone(server.SETTINGS["key_source"])
        self.assertIsNone(server.SETTINGS["model"])

    def test_valid_key_connects_and_sets_env_key_source(self):
        with mock.patch("concierge.env_config.get_gemini_api_key", return_value="fake-key"), \
             mock.patch("server.gemini.pin_model", return_value="gemini-flash-latest"):
            server._connect_from_env()
        self.assertEqual(server.SETTINGS["key_source"], "env")
        self.assertEqual(server.SETTINGS["model"], "gemini-flash-latest")
        self.assertEqual(server.SETTINGS["api_key"], "fake-key")
        self.assertFalse(server.SETTINGS["offline_mode"])

    def test_invalid_key_falls_back_without_crashing(self):
        with mock.patch("concierge.env_config.get_gemini_api_key", return_value="bad-key"), \
             mock.patch("server.gemini.pin_model", side_effect=gemini.ProviderError("permission", "bad key")):
            server._connect_from_env()
        self.assertIsNone(server.SETTINGS["key_source"])
        self.assertIsNone(server.SETTINGS["model"])
        self.assertEqual(server.SETTINGS["last_error"]["category"], "permission")

    def test_settings_endpoint_reports_env_source_without_the_key(self):
        with mock.patch("concierge.env_config.get_gemini_api_key", return_value="fake-key"), \
             mock.patch("server.gemini.pin_model", return_value="gemini-flash-latest"):
            server._connect_from_env()
        client = TestClient(server.app)
        resp = client.get("/api/settings")
        body = resp.json()
        self.assertEqual(body["key_source"], "env")
        self.assertNotIn("api_key", body)
        self.assertNotIn("fake-key", resp.text)


class AuditLog(unittest.TestCase):
    def setUp(self):
        server.SETTINGS["offline_mode"] = True
        self.client = TestClient(server.app)
        resp = self.client.post("/api/session", json={"household_id": "h1"})
        self.session_id = resp.json()["session_id"]

    def test_chat_turn_is_logged_with_required_fields(self):
        self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Will I lose power?"})
        resp = self.client.get("/api/audit", params={"session_id": self.session_id})
        entries = resp.json()["audit_log"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        for field in ("timestamp", "turn_type", "inputs", "tools_called", "outputs", "validator", "data_version", "model_name"):
            self.assertIn(field, entry)
        self.assertEqual(entry["model_name"], "offline-rules-v1")
        self.assertTrue(entry["validator"]["valid"])
        self.assertTrue(any(t["name"] == "get_risk" for t in entry["tools_called"]))

    def test_whatif_turn_is_also_logged(self):
        self.client.post("/api/whatif", json={"session_id": self.session_id, "action": "block_access"})
        resp = self.client.get("/api/audit", params={"session_id": self.session_id})
        entries = resp.json()["audit_log"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["turn_type"], "whatif")

    def test_audit_log_is_newest_first(self):
        self.client.post("/api/chat", json={"session_id": self.session_id, "message": "Will I lose power?"})
        self.client.post("/api/whatif", json={"session_id": self.session_id, "action": "block_access"})
        resp = self.client.get("/api/audit", params={"session_id": self.session_id})
        entries = resp.json()["audit_log"]
        self.assertEqual(entries[0]["turn_type"], "whatif")
        self.assertEqual(entries[1]["turn_type"], "chat")

    def test_unknown_session_is_404(self):
        resp = self.client.get("/api/audit", params={"session_id": "nonexistent"})
        self.assertEqual(resp.status_code, 404)


class VisibilityEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_data_quality_reports_join_exclusions_and_the_bogus_repair_date_finding(self):
        resp = self.client.get("/api/data-quality")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreater(body["circuit_crosswalk"]["ambiguous_pair_count"], 0)
        self.assertGreater(body["damage_join"]["unmapped"], 0)
        self.assertEqual(body["unrepaired_with_repair_date"]["count"], body["unrepaired_with_repair_date"]["of_unrepaired_total"])
        self.assertIn("spearman_rank_correlation", body["backtest_summary"])

    def test_docs_page_lists_every_real_route(self):
        resp = self.client.get("/docs")
        self.assertEqual(resp.status_code, 200)
        text = resp.text
        for path in ("/api/chat", "/api/whatif", "/api/audit", "/api/dashboard", "/api/data-quality", "/api/session", "/api/settings"):
            self.assertIn(path, text)


if __name__ == "__main__":
    unittest.main()
