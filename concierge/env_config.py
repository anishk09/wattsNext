"""
Loads GEMINI_API_KEY from the shell environment or a .env file in the
project root — stdlib only, no python-dotenv dependency for a handful of
KEY=VALUE lines. Never logs, prints, or returns the key alongside any
other data; callers must not log the return value either.
"""
import os
import pathlib

ENV_PATH = pathlib.Path(__file__).parent.parent / ".env"


def _parse_env_file(path):
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def get_gemini_api_key():
    """Shell environment takes priority over the .env file. Returns the
    key string, or None if neither source has it."""
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    return _parse_env_file(ENV_PATH).get("GEMINI_API_KEY") or None
