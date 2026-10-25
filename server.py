"""
Watt'sNext server: routes, in-memory sessions, chat orchestration, provider
connection. Binds to 127.0.0.1 only. No API keys are ever logged or written
to disk — they live only in the in-memory SETTINGS dict for this process.
"""
import json
import pathlib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, FileResponse, HTMLResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from concierge import api_docs, cases, chat, customer_services, data_version, env_config, gemini, privacy, tools, validator

DATA_DIR = pathlib.Path(__file__).parent / "data"

# key_source: None (no key yet) | "env" (.env/shell, never shown or editable
# from Settings) | "manual" (typed into the Settings field this session).
SETTINGS = {"api_key": None, "model": None, "offline_mode": False, "last_error": None, "key_source": None}
SESSIONS = {}

DEFAULT_SCENARIO = {"access_blocked": False, "extra_crews": 0, "repairs_complete": False}


def _connect_from_env():
    """Startup-time auto-connect. Never logs the key itself — only the
    resulting model name or an honest error category."""
    key = env_config.get_gemini_api_key()
    if not key:
        return
    try:
        model = gemini.pin_model(key)
        SETTINGS["api_key"] = key
        SETTINGS["model"] = model
        SETTINGS["key_source"] = "env"
        SETTINGS["offline_mode"] = False
        print(f"[startup] Connected to Gemini via .env/environment key — model: {model}")
    except gemini.ProviderError as e:
        SETTINGS["last_error"] = {"category": e.category, "message": e.message}
        print(f"[startup] GEMINI_API_KEY found but connection failed ({e.category}); falling back to Settings/offline mode.")


@asynccontextmanager
async def lifespan(app):
    # Tied to actual server startup (uvicorn's lifespan protocol), not mere
    # module import — a bare TestClient() (no `with`) never drives this, so
    # the test suite stays network-free regardless of a local .env.
    _connect_from_env()
    yield

MAX_MESSAGE_LENGTH = 2000


def _new_session(household_id):
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = {
        "household_id": household_id,
        "scenario": dict(DEFAULT_SCENARIO),
        "history": [],
        "previous_estimate": None,
        "events": [],
        "triggered_alerts": {},
        "audit_log": [],
    }
    return session_id


def _model_name():
    if SETTINGS["offline_mode"] or not SETTINGS["model"]:
        return "offline-rules-v1"
    return SETTINGS["model"]


def _log_audit(session, turn_type, inputs, tools_called, outputs, validator_result, privacy_violations=None):
    session["audit_log"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "turn_type": turn_type,
        "inputs": inputs,
        "tools_called": tools_called,
        "outputs": outputs,
        "validator": validator_result,
        "privacy_violations": privacy_violations or [],
        "data_version": data_version.VERSION,
        "model_name": _model_name(),
    })


def _log_event(session, event_type, detail):
    session["events"].append({
        "type": event_type,
        "detail": detail,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })


def _record_alerts(session, alerts_result):
    for preview in alerts_result.get("message_previews", []):
        if preview["type"] not in session["triggered_alerts"]:
            session["triggered_alerts"][preview["type"]] = preview
            _log_event(session, "alert_previewed", {"alert_type": preview["type"], "message": preview["message"]})


def _log_estimate_change(session, before, after):
    if before.get("fallback", {}).get("fallback") or after.get("fallback", {}).get("fallback"):
        return
    if before["p10_hours"]["value"] == after["p10_hours"]["value"] and before["p90_hours"]["value"] == after["p90_hours"]["value"]:
        return
    _log_event(session, "estimate_changed", {
        "before": [before["p10_hours"]["value"], before["p90_hours"]["value"]],
        "after": [after["p10_hours"]["value"], after["p90_hours"]["value"]],
    })


async def list_cities(request):
    return JSONResponse({"cities": cases.list_cities()})


async def list_households(request):
    households = [
        {"household_id": h["household_id"], "display_name": h["display_name"], "city": h["city"]}
        for h in cases.list_households()
    ]
    return JSONResponse({"households": households})


async def _json_body(request):
    """Input validation shared by every POST endpoint: must be a JSON object."""
    try:
        body = await request.json()
    except Exception:
        return None, JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return None, JSONResponse({"error": "request body must be a JSON object"}, status_code=400)
    return body, None


def _require_str(body, field, max_length=200):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        return None, JSONResponse({"error": f"'{field}' must be a non-empty string"}, status_code=400)
    if len(value) > max_length:
        return None, JSONResponse({"error": f"'{field}' exceeds {max_length} characters"}, status_code=400)
    return value, None


async def create_session(request):
    body, err = await _json_body(request)
    if err:
        return err
    household_id, err = _require_str(body, "household_id", max_length=50)
    if err:
        return err
    if cases.get_household(household_id) is None:
        return JSONResponse({"error": "unknown household_id"}, status_code=400)
    session_id = _new_session(household_id)
    return JSONResponse({"session_id": session_id, "household_id": household_id})


def _session_or_404(session_id):
    if not isinstance(session_id, str):
        return None
    return SESSIONS.get(session_id)


async def chat_endpoint(request):
    body, err = await _json_body(request)
    if err:
        return err
    session_id, err = _require_str(body, "session_id", max_length=64)
    if err:
        return err
    message, err = _require_str(body, "message", max_length=MAX_MESSAGE_LENGTH)
    if err:
        return err
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)

    if chat.needs_live_data_refusal(message):
        reply = {"text": chat.OFFICIAL_LINKS_TEXT, "cards": {}, "fallback": False, "offline": False, "tools_called": [], "validator": {"valid": True, "unverified": []}}
    elif SETTINGS["offline_mode"]:
        reply = chat.offline_reply(message, session["household_id"], session["scenario"])
    elif SETTINGS["api_key"] and SETTINGS["model"]:
        try:
            reply = chat.online_reply(
                SETTINGS["api_key"], SETTINGS["model"], message,
                session["household_id"], session["scenario"], session["history"],
            )
        except gemini.ProviderError as e:
            SETTINGS["last_error"] = {"category": e.category, "message": e.message}
            return JSONResponse({
                "error": "provider_error",
                "category": e.category,
                "message": e.message,
                "offer_offline": True,
            }, status_code=502)
    elif SETTINGS["last_error"]:
        # A connection was attempted (at startup via .env, or manually) and
        # failed — never silently drop to offline over that; make the user
        # choose, same as a failure mid-conversation would.
        return JSONResponse({
            "error": "provider_error",
            "category": SETTINGS["last_error"]["category"],
            "message": SETTINGS["last_error"]["message"],
            "offer_offline": True,
        }, status_code=502)
    else:
        # No key anywhere, nothing ever attempted — offline is the honest
        # base state here, not a fallback from a failure.
        reply = chat.offline_reply(message, session["household_id"], session["scenario"])

    clean_text, privacy_violations = privacy.scrub(reply.get("text"))
    reply["text"] = clean_text

    session["history"].append({"role": "user", "parts": [{"text": message}]})
    if reply.get("text"):
        session["history"].append({"role": "model", "parts": [{"text": reply["text"]}]})
    restoration = reply.get("cards", {}).get("restoration")
    if restoration and not restoration.get("fallback", {}).get("fallback"):
        if session["previous_estimate"] is not None:
            _log_estimate_change(session, {
                "fallback": {"fallback": False},
                "p10_hours": {"value": session["previous_estimate"]["p10_hours"]},
                "p90_hours": {"value": session["previous_estimate"]["p90_hours"]},
            }, restoration)
        session["previous_estimate"] = {
            "p10_hours": restoration["p10_hours"]["value"],
            "p90_hours": restoration["p90_hours"]["value"],
        }
    if "alerts" in reply.get("cards", {}):
        _record_alerts(session, reply["cards"]["alerts"])

    _log_audit(
        session, "chat", {"message": message},
        reply.get("tools_called", []), reply.get("cards", {}),
        reply.get("validator", {"valid": True, "unverified": []}),
        privacy_violations,
    )

    return JSONResponse(reply)


WHATIF_ACTIONS = {
    "block_access": lambda s: s.update(access_blocked=True),
    "clear_access": lambda s: s.update(access_blocked=False),
    "add_crews": lambda s: s.update(extra_crews=s["extra_crews"] + 2),
    "complete_repairs": lambda s: s.update(repairs_complete=True),
    "reset": lambda s: s.update(DEFAULT_SCENARIO),
}


async def whatif_endpoint(request):
    body, err = await _json_body(request)
    if err:
        return err
    session_id, err = _require_str(body, "session_id", max_length=64)
    if err:
        return err
    action, err = _require_str(body, "action", max_length=32)
    if err:
        return err
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)
    if action not in WHATIF_ACTIONS:
        return JSONResponse({"error": "unknown action", "valid_actions": sorted(WHATIF_ACTIONS)}, status_code=400)

    household_id = session["household_id"]
    before = tools.get_restoration_estimate(household_id, **session["scenario"])

    WHATIF_ACTIONS[action](session["scenario"])
    _log_event(session, "whatif_applied", {"action": action})

    after = tools.get_restoration_estimate(household_id, **session["scenario"])
    risk = tools.get_risk(household_id, session["scenario"]["repairs_complete"])
    prep = tools.get_prep_guidance(household_id, session["scenario"]["repairs_complete"])
    alerts = tools.get_alert_info(household_id, **session["scenario"], previous_estimate=session["previous_estimate"])

    _log_estimate_change(session, before, after)
    _record_alerts(session, alerts)

    session["previous_estimate"] = {
        "p10_hours": after.get("p10_hours", {}).get("value"),
        "p90_hours": after.get("p90_hours", {}).get("value"),
    } if not after.get("fallback", {}).get("fallback") else None

    _log_audit(
        session, "whatif", {"action": action},
        [
            {"name": "get_restoration_estimate", "args": {"household_id": household_id, **session["scenario"]}},
            {"name": "get_risk", "args": {"household_id": household_id, "repairs_complete": session["scenario"]["repairs_complete"]}},
            {"name": "get_prep_guidance", "args": {"household_id": household_id, "repairs_complete": session["scenario"]["repairs_complete"]}},
            {"name": "get_alert_info", "args": {"household_id": household_id, **session["scenario"]}},
        ],
        {"before": before, "after": after, "risk": risk, "prep": prep, "alerts": alerts},
        {"valid": True, "unverified": []},
    )

    return JSONResponse({
        "scenario": session["scenario"],
        "before": before,
        "after": after,
        "risk": risk,
        "prep": prep,
        "alerts": alerts,
    })


async def audit_endpoint(request):
    session_id = request.query_params.get("session_id")
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)
    return JSONResponse({"audit_log": list(reversed(session["audit_log"]))})


async def dashboard_endpoint(request):
    session_id = request.query_params.get("session_id")
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)

    household_id = session["household_id"]
    scenario = session["scenario"]
    risk = tools.get_risk(household_id, scenario["repairs_complete"])
    restoration = tools.get_restoration_estimate(household_id, **scenario)
    timeline = tools.get_job_timeline(household_id, extra_crews=scenario["extra_crews"], repairs_complete=scenario["repairs_complete"])

    alerts = []
    for alert_type in customer_services.ALERT_TYPES:
        triggered = session["triggered_alerts"].get(alert_type)
        alerts.append({
            "type": alert_type,
            "timing": customer_services.ALERT_TIMINGS[alert_type],
            "triggered": triggered is not None,
            "message": triggered["message"] if triggered else None,
        })

    return JSONResponse({
        "scenario": scenario,
        "risk": risk,
        "restoration": restoration,
        "previous_estimate": session["previous_estimate"],
        "timeline": timeline,
        "alerts": alerts,
        "events": list(reversed(session["events"])),
    })


async def get_settings(request):
    return JSONResponse({
        "model": SETTINGS["model"],
        "offline_mode": SETTINGS["offline_mode"],
        "connected": bool(SETTINGS["model"]) and not SETTINGS["offline_mode"],
        "last_error": SETTINGS["last_error"],
        "key_source": SETTINGS["key_source"],
    })


async def update_settings(request):
    body, err = await _json_body(request)
    if err:
        return err

    if "offline_mode" in body and not isinstance(body["offline_mode"], bool):
        return JSONResponse({"error": "'offline_mode' must be a boolean"}, status_code=400)
    if "offline_mode" in body:
        SETTINGS["offline_mode"] = body["offline_mode"]

    api_key = body.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        return JSONResponse({"error": "'api_key' must be a string"}, status_code=400)
    if api_key:
        try:
            model = gemini.pin_model(api_key)
            SETTINGS["api_key"] = api_key
            SETTINGS["model"] = model
            SETTINGS["key_source"] = "manual"
            SETTINGS["last_error"] = None
            SETTINGS["offline_mode"] = False
        except gemini.ProviderError as e:
            SETTINGS["last_error"] = {"category": e.category, "message": e.message}
            return JSONResponse({
                "error": "provider_error",
                "category": e.category,
                "offer_offline": True,
            }, status_code=502)

    return await get_settings(request)


async def data_quality_endpoint(request):
    dq = json.loads((DATA_DIR / "data_quality.json").read_text())
    backtest = json.loads((DATA_DIR / "backtest.json").read_text())
    dq["backtest_summary"] = {
        "spearman_rank_correlation": backtest["spearman_rank_correlation"],
        "interpretation": backtest["interpretation"],
    }
    dq["data_version"] = data_version.VERSION
    return JSONResponse(dq)


async def docs_endpoint(request):
    return HTMLResponse(api_docs.render_html())


async def index(request):
    return FileResponse("static/index.html")


app = Starlette(routes=[
    Route("/", index),
    Route("/api/cities", list_cities),
    Route("/api/households", list_households),
    Route("/api/session", create_session, methods=["POST"]),
    Route("/api/chat", chat_endpoint, methods=["POST"]),
    Route("/api/whatif", whatif_endpoint, methods=["POST"]),
    Route("/api/audit", audit_endpoint),
    Route("/api/dashboard", dashboard_endpoint),
    Route("/api/settings", get_settings, methods=["GET"]),
    Route("/api/settings", update_settings, methods=["POST"]),
    Route("/api/data-quality", data_quality_endpoint),
    Route("/docs", docs_endpoint),
    Mount("/static", StaticFiles(directory="static"), name="static"),
], lifespan=lifespan)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
