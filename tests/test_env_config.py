import os
import pathlib
import tempfile
import unittest
from unittest import mock

from concierge import env_config


class EnvFileParsing(unittest.TestCase):
    def test_parses_simple_key_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / ".env"
            path.write_text("GEMINI_API_KEY=abc123\n")
            self.assertEqual(env_config._parse_env_file(path)["GEMINI_API_KEY"], "abc123")

    def test_skips_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / ".env"
            path.write_text("# a comment\n\nGEMINI_API_KEY=abc123\n")
            self.assertEqual(env_config._parse_env_file(path), {"GEMINI_API_KEY": "abc123"})

    def test_strips_quotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / ".env"
            path.write_text('GEMINI_API_KEY="abc123"\n')
            self.assertEqual(env_config._parse_env_file(path)["GEMINI_API_KEY"], "abc123")

    def test_missing_file_returns_empty(self):
        self.assertEqual(env_config._parse_env_file(pathlib.Path("/nonexistent/.env")), {})


class GetGeminiApiKey(unittest.TestCase):
    def test_shell_environment_takes_priority_over_env_file(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "from-shell"}):
            self.assertEqual(env_config.get_gemini_api_key(), "from-shell")

    def test_falls_back_to_env_file_when_shell_var_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / ".env"
            path.write_text("GEMINI_API_KEY=from-file\n")
            with mock.patch.object(env_config, "ENV_PATH", path), mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                self.assertEqual(env_config.get_gemini_api_key(), "from-file")

    def test_returns_none_when_neither_source_has_it(self):
        with mock.patch.object(env_config, "ENV_PATH", pathlib.Path("/nonexistent/.env")):
            os.environ.pop("GEMINI_API_KEY", None)
            self.assertIsNone(env_config.get_gemini_api_key())


if __name__ == "__main__":
    unittest.main()
