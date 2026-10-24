"""Preparation guidance and alert generation. Tailored only to what the
customer declares — never to anything inferred about them."""

ESTIMATE_CHANGE_THRESHOLD_HOURS = 2.0


def prep_guidance(household, risk):
    needs = household["declared_needs"]
    actions = [
        "Charge phones and essential devices now, before any outage starts.",
        "Keep flashlights and batteries accessible; avoid candles as a primary light source.",
        "Stay away from downed or sagging power lines and report them instead of approaching.",
    ]

    if risk["band"] in ("Moderate", "High"):
        actions.append("Have a few days of water, non-perishable food, and any needed medication on hand.")

    if needs.get("power_bank"):
        actions.append("Reserve your power bank for essential devices first — phone and any medical equipment.")

    if needs.get("needs_phone_for_work"):
        actions.append("Let your employer know you may be unreachable during the estimated restoration window; plan a backup way to connect (car charger, a neighbor's power, or a public space with power).")

    if needs.get("medical_device"):
        actions.append(
            "SAFETY: contact your medical device provider now for a backup-power plan. "
            "A power bank or generic battery is not a substitute for provider-approved backup power."
        )

    return actions


def alert_eligibility(household):
    return {
        "eligible": household["alert_opt_in"],
        "channel": household["alert_channel"] if household["alert_opt_in"] else None,
        "reason": "Opted in during account setup." if household["alert_opt_in"] else "Not opted in to alerts.",
    }


def escalation_triggers(household):
    triggers = [
        {"trigger": "Restoration estimate moves by 2 hours or more", "action": "Send an estimate-updated alert."},
        {"trigger": "Restoration marked complete", "action": "Send a restoration-complete confirmation."},
    ]
    if household["declared_needs"].get("medical_device"):
        triggers.append({
            "trigger": "Declared power-dependent medical device",
            "action": "Recommend a phone call and an emergency backup-power plan. Never promise priority restoration.",
        })
    return triggers


def _channel_label(channel):
    return {"sms": "SMS", "email": "Email"}.get(channel, channel or "none")


def build_alert_previews(household, case, estimate, previous_estimate=None):
    channel = household["alert_channel"]
    city = household["city"]
    previews = []

    previews.append({
        "type": "pre_storm",
        "timing": "Sent as soon as a storm watch covers your area.",
        "channel": _channel_label(channel),
        "message": f"Watt'sNext: A storm is approaching the {city} area. Review your preparation checklist in the app.",
    })

    if case["damage_items"] and any(not d.get("repaired", True) for d in case["damage_items"]):
        previews.append({
            "type": "outage_confirmed",
            "timing": "Sent once damage is assigned to your upstream path.",
            "channel": _channel_label(channel),
            "message": f"Watt'sNext: We show damage affecting power to your area ({city}). Estimated restoration: {estimate['low_hours']:.1f}-{estimate['high_hours']:.1f} h. This is a model estimate, not confirmed by the utility.",
        })

    moved = previous_estimate is not None and abs(estimate["high_hours"] - previous_estimate["high_hours"]) >= ESTIMATE_CHANGE_THRESHOLD_HOURS
    if moved:
        previews.append({
            "type": "estimate_updated",
            "timing": "Sent when the estimate moves by 2 hours or more.",
            "channel": _channel_label(channel),
            "message": f"Watt'sNext update: new estimated restoration window is {estimate['low_hours']:.1f}-{estimate['high_hours']:.1f} h (was {previous_estimate['low_hours']:.1f}-{previous_estimate['high_hours']:.1f} h).",
        })

    if estimate["reference_effort_hours"] == 0.0:
        previews.append({
            "type": "restoration_complete",
            "timing": "Sent when repairs on your path are marked complete.",
            "channel": _channel_label(channel),
            "message": f"Watt'sNext: Power should be back on in the {city} area per our simulation. Still out? Check your breakers, then report it.",
        })

    return previews
