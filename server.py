"""
Watt'sNext server: routes, in-memory sessions, chat orchestration, provider
connection. Binds to 127.0.0.1 only. No API keys are ever logged or written
to disk — they live only in the in-memory SETTINGS dict for this process.
"""
import uuid
from datetime import datetime, timezone

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, FileResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from concierge import cases, chat, customer_services, gemini, tools

SETTINGS = {"api_key": None, "model": None, "offline_mode": False, "last_error": None}
SESSIONS = {}

DEFAULT_SCENARIO = {"access_blocked": False, "extra_crews": 0, "repairs_complete": False}


def _new_session(household_id):
    session_id = uuid.uuid4().hex
    SESSIONS[session_id] = {
        "household_id": household_id,
        "scenario": dict(DEFAULT_SCENARIO),
        "history": [],
        "previous_estimate": None,
        "events": [],
        "triggered_alerts": {},
    }
    return session_id


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


async def create_session(request):
    body = await request.json()
    household_id = body.get("household_id")
    if cases.get_household(household_id) is None:
        return JSONResponse({"error": "unknown household_id"}, status_code=400)
    session_id = _new_session(household_id)
    return JSONResponse({"session_id": session_id, "household_id": household_id})


def _session_or_404(session_id):
    return SESSIONS.get(session_id)


async def chat_endpoint(request):
    body = await request.json()
    session_id = body.get("session_id")
    message = (body.get("message") or "").strip()
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)

    if chat.needs_live_data_refusal(message):
        reply = {"text": chat.OFFICIAL_LINKS_TEXT, "cards": {}, "fallback": False, "offline": False}
    elif SETTINGS["offline_mode"] or not SETTINGS["api_key"] or not SETTINGS["model"]:
        reply = chat.offline_reply(message, session["household_id"], session["scenario"])
    else:
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
                "offer_offline": True,
            }, status_code=502)

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

    return JSONResponse(reply)


WHATIF_ACTIONS = {
    "block_access": lambda s: s.update(access_blocked=True),
    "clear_access": lambda s: s.update(access_blocked=False),
    "add_crews": lambda s: s.update(extra_crews=s["extra_crews"] + 2),
    "complete_repairs": lambda s: s.update(repairs_complete=True),
    "reset": lambda s: s.update(DEFAULT_SCENARIO),
}


async def whatif_endpoint(request):
    body = await request.json()
    session_id = body.get("session_id")
    action = body.get("action")
    session = _session_or_404(session_id)
    if session is None:
        return JSONResponse({"error": "unknown session_id"}, status_code=404)
    if action not in WHATIF_ACTIONS:
        return JSONResponse({"error": "unknown action"}, status_code=400)

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

    return JSONResponse({
        "scenario": session["scenario"],
        "before": before,
        "after": after,
        "risk": risk,
        "prep": prep,
        "alerts": alerts,
    })


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
    })


async def update_settings(request):
    body = await request.json()

    if "offline_mode" in body:
        SETTINGS["offline_mode"] = bool(body["offline_mode"])

    api_key = body.get("api_key")
    if api_key:
        try:
            model = gemini.pin_model(api_key)
            SETTINGS["api_key"] = api_key
            SETTINGS["model"] = model
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


async def index(request):
    return FileResponse("static/index.html")


app = Starlette(routes=[
    Route("/", index),
    Route("/api/cities", list_cities),
    Route("/api/households", list_households),
    Route("/api/session", create_session, methods=["POST"]),
    Route("/api/chat", chat_endpoint, methods=["POST"]),
    Route("/api/whatif", whatif_endpoint, methods=["POST"]),
    Route("/api/dashboard", dashboard_endpoint),
    Route("/api/settings", get_settings, methods=["GET"]),
    Route("/api/settings", update_settings, methods=["POST"]),
    Mount("/static", StaticFiles(directory="static"), name="static"),
])


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
