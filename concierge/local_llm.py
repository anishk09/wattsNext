"""Local OpenLLaMA adapter via an Ollama-compatible HTTP API."""
import json, os, urllib.request, urllib.error

BASE_URL = os.environ.get("OPENLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("OPENLLAMA_MODEL", "openllama")

class LocalProviderError(Exception):
    pass

def generate(prompt, timeout=30):
    body = {"model": MODEL, "stream": False, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(BASE_URL.rstrip("/") + "/api/chat", data=json.dumps(body).encode(), method="POST", headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode())
        text = result.get("message", {}).get("content", "").strip()
        if not text: raise LocalProviderError("Local model returned no text")
        return text
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise LocalProviderError(str(exc)) from exc
