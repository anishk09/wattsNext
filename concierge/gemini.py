"""
Minimal Gemini REST client (stdlib urllib only — no SDK dependency).
Lists models with the user's key, pins the first allowlisted model that
completes a real tool-call round trip, and exposes honest error categories
so the UI can offer offline mode instead of failing silently.
"""
import json
import urllib.request
import urllib.error

API_BASE = "https://generativelanguage.googleapis.com/v1beta"

# Pinned from a live test against a real key: gemini-2.5-flash is listed by
# list-models but 404s on generateContent ("no longer available to new
# users") — listed availability and actual availability aren't the same
# thing, so the round-trip check below has to be a real generateContent
# call, not just a models-list membership check.
ALLOWLIST = [
    "gemini-flash-latest",
]


class ProviderError(Exception):
    def __init__(self, category, message):
        # "quota" | "permission" | "model_unavailable" | "unavailable" | "unknown"
        self.category = category
        self.message = message
        super().__init__(message)


def _categorize_http_error(err):
    status = err.code
    if status == 429:
        return "quota"
    if status in (401, 403):
        return "permission"
    if status == 404:
        return "model_unavailable"
    if status in (500, 502, 503, 504):
        return "unavailable"
    return "unknown"


def _request(path, api_key, method="GET", body=None, timeout=15):
    url = f"{API_BASE}/{path}?key={api_key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise ProviderError(_categorize_http_error(e), e.read().decode()[:300]) from e
    except urllib.error.URLError as e:
        raise ProviderError("unavailable", str(e.reason)) from e
    except TimeoutError as e:
        # A raw socket/SSL read timeout — distinct from urllib.error.URLError
        # (which wraps connection-establishment failures) and easy to miss:
        # it crashed the server's startup lifespan entirely the first time
        # this code ran against a real key, since nothing here caught it.
        raise ProviderError("unavailable", f"Timed out waiting for a response ({timeout}s).") from e
    except OSError as e:
        # Final backstop — this client exists specifically so a flaky
        # connection degrades to an honest error, never an unhandled crash.
        raise ProviderError("unavailable", str(e)) from e


def list_models(api_key):
    result = _request("models", api_key)
    return [m["name"].split("/")[-1] for m in result.get("models", [])]


def _tool_round_trip_ok(model, api_key):
    """A real generateContent call with a tool attached — accepted only if
    the model actually returns content, not just a 200 with an empty body.
    Listed availability (list-models) and real availability can differ."""
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Call the ping tool."}]}],
        "tools": [{"function_declarations": [
            {"name": "ping", "description": "test", "parameters": {"type": "object", "properties": {}}}
        ]}],
    }
    result = _request(f"models/{model}:generateContent", api_key, method="POST", body=body, timeout=30)
    candidates = result.get("candidates", [])
    if not candidates:
        return False
    parts = candidates[0].get("content", {}).get("parts", [])
    return bool(parts)


def pin_model(api_key):
    """First allowlisted model that completes a real tool-call round trip.
    Raises the LAST real provider error (e.g. a 404 model_unavailable),
    not a generic message, so Settings shows what actually happened."""
    available = set(list_models(api_key))
    last_error = None
    for candidate in ALLOWLIST:
        if candidate not in available:
            last_error = ProviderError("model_unavailable", f"{candidate} is not in this key's available models.")
            continue
        try:
            if _tool_round_trip_ok(candidate, api_key):
                return candidate
            last_error = ProviderError("model_unavailable", f"{candidate} returned no content on a tool-call round trip.")
        except ProviderError as e:
            last_error = e
    raise last_error or ProviderError("model_unavailable", "No allowlisted model completed a tool-call round trip.")


def generate(api_key, model, contents, function_declarations):
    body = {
        "contents": contents,
        "tools": [{"function_declarations": function_declarations}],
    }
    result = _request(f"models/{model}:generateContent", api_key, method="POST", body=body, timeout=30)
    candidates = result.get("candidates", [])
    if not candidates:
        raise ProviderError("unavailable", "No candidates returned.")
    parts = candidates[0].get("content", {}).get("parts", [])

    function_calls = [p["functionCall"] for p in parts if "functionCall" in p]
    text = "".join(p.get("text", "") for p in parts if "text" in p)
    # `parts` is the raw, unmodified list straight from the API — callers
    # that build a follow-up turn must reuse this exact list (not rebuild
    # one from function_calls/text alone) so sibling fields like
    # thoughtSignature round-trip unchanged. See chat.py::online_reply.
    return {"text": text, "function_calls": function_calls, "parts": parts}
