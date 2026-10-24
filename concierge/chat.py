"""
Chat orchestration: routes a user message to either the Gemini tool-calling
loop or the offline deterministic templates. Both paths produce the same
shape of response so the frontend never has to special-case the provider.

Safety guard runs first, regardless of mode: questions needing live or
account data never reach a tool call.
"""
import re

from . import tools, gemini

NO_LIVE_DATA_PATTERNS = [
    r"\bshelter\b", r"\bcredit\b", r"\bcompensation\b", r"\brebate\b",
    r"\bweather\b", r"\bforecast\b", r"\bcrew (location|position)\b",
    r"\blive (outage|map|feed)\b", r"\bis.*open\b", r"\bcurrent outage\b",
]

OFFICIAL_LINKS_TEXT = (
    "I don't have live or account data for that. For current outage maps and account-specific "
    "information, check the official Appalachian Power outage center (appalachianpower.com/outages) "
    "or, for shelter and relief needs, the American Red Cross (redcross.org)."
)

SYSTEM_INSTRUCTION = (
    "You are Watt'sNext, AEP's storm outage concierge. You never invent numbers — call the provided "
    "tools and explain their output. Never claim live weather, outage, or crew-position data. Never "
    "infer health information from context; only use what the customer explicitly declares. Answers to "
    "substantive questions should be 80-180 words covering: the direct answer, why, one or two next "
    "steps, and the main uncertainty. Follow-up answers should be 1-3 sentences. Ask at most one "
    "follow-up question. If a tool reports fallback=true, say plainly that a reliable estimate isn't "
    "available for this location and give general safety guidance plus the official outage link."
)


def needs_live_data_refusal(message):
    lowered = message.lower()
    return any(re.search(p, lowered) for p in NO_LIVE_DATA_PATTERNS)


def _word_count(text):
    return len(text.split())


def classify_intent(message):
    lowered = message.lower()
    if any(k in lowered for k in ("alert", "qualify", "notify", "notification")):
        return "alerts"
    if any(k in lowered for k in ("prepare", "get ready", "should i do", "safety")):
        return "prep"

    has_restoration = any(k in lowered for k in ("how long", "restoration", "repair", "fix", "back on", "back up"))
    has_risk = any(k in lowered for k in ("lose power", "risk", "going to lose", "will i"))
    if has_restoration and has_risk:
        return "risk_restoration"
    if has_restoration:
        return "restoration"
    if has_risk:
        return "risk"
    return "overview"


def _offline_answer(intent, household_id, scenario):
    cards = {}
    fallback = tools.get_fallback_status(household_id)
    if fallback["fallback"]:
        return {
            "text": f"{fallback['reason']} Follow general storm safety guidance and check the official "
                    "Appalachian Power outage map for live information.",
            "cards": {},
            "fallback": True,
        }

    if intent in ("risk", "risk_restoration", "overview"):
        cards["risk"] = tools.get_risk(household_id, scenario["repairs_complete"])
    if intent in ("restoration", "risk_restoration", "overview"):
        cards["restoration"] = tools.get_restoration_estimate(household_id, **scenario)
    if intent in ("prep", "restoration", "risk_restoration", "overview"):
        cards["prep"] = tools.get_prep_guidance(household_id, scenario["repairs_complete"])
    if intent in ("alerts", "overview"):
        cards["alerts"] = tools.get_alert_info(household_id, **scenario)

    text = _render_offline_text(intent, cards)
    return {"text": text, "cards": cards, "fallback": False}


def _render_offline_text(intent, cards):
    parts = []
    if "risk" in cards:
        r = cards["risk"]
        if r["fallback"]["fallback"]:
            parts.append(f"Risk: {r['fallback']['reason']}")
        else:
            parts.append(
                f"Risk is {r['risk_band']['value']} ({r['confidence']['value']} confidence). {r['risk_reason']} {r['confidence']['note']}"
            )
    if "restoration" in cards:
        e = cards["restoration"]
        if e["reference_effort_hours"]["value"] == 0.0:
            parts.append("Power should be back on per this simulation — if yours is still out, check your breakers, then report it.")
        else:
            parts.append(
                f"Estimated restoration: {e['low_hours']['value']}-{e['high_hours']['value']} hours. "
                "This is a scenario range, not a confidence interval, and not confirmed by the utility."
            )
    if "prep" in cards:
        all_actions = cards["prep"]["actions"]
        if intent == "prep":
            shown = all_actions
        else:
            safety = [a for a in all_actions if a.startswith("SAFETY:")]
            other = [a for a in all_actions if not a.startswith("SAFETY:")]
            shown = safety + other[: max(1, 3 - len(safety))]
        parts.append("What you can do: " + "; ".join(shown) + ".")
    if "alerts" in cards:
        a = cards["alerts"]
        if a["eligible"]:
            parts.append(f"You're eligible for alerts via {a['channel']}.")
        else:
            parts.append("You're not currently opted in to alerts.")
    if not parts:
        parts.append("Ask me whether you'll lose power, how long repairs could take, how to prepare, or whether you qualify for alerts.")
    return " ".join(parts)


def offline_reply(message, household_id, scenario):
    intent = classify_intent(message)
    result = _offline_answer(intent, household_id, scenario)
    result["offline"] = True
    return result


def online_reply(api_key, model, message, household_id, scenario, history):
    contents = list(history) + [{"role": "user", "parts": [{"text": message}]}]
    response = gemini.generate(api_key, model, contents, tools.FUNCTION_DECLARATIONS)

    cards = {}
    if response["function_calls"]:
        function_response_parts = []
        for call in response["function_calls"]:
            name = call["name"]
            args = dict(call.get("args", {}))
            args.setdefault("household_id", household_id)
            for key in ("access_blocked", "extra_crews", "repairs_complete"):
                if key in scenario and key not in args:
                    args[key] = scenario[key]
            result = tools.DISPATCH[name](**args)
            cards[name.replace("get_", "")] = result
            function_response_parts.append({
                "functionResponse": {"name": name, "response": result}
            })
        contents.append({"role": "model", "parts": [{"functionCall": c} for c in response["function_calls"]]})
        contents.append({"role": "user", "parts": function_response_parts})
        response = gemini.generate(api_key, model, contents, tools.FUNCTION_DECLARATIONS)

    return {"text": response["text"], "cards": cards, "fallback": False, "offline": False}
