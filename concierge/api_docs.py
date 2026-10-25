"""
Generates the /docs page: every endpoint, its method, and a real
request/response example. Plain HTML, no styling system — this is a
developer reference page, not part of the customer-facing UI.
"""
import html
import json

ENDPOINTS = [
    {
        "method": "GET", "path": "/api/cities",
        "description": "Cities with at least one sample household, each mapped to its household IDs.",
        "response": {"cities": {"Roanoke": ["h1", "h2", "h3", "h10", "h11", "h12"], "Vinton": ["h4"]}},
    },
    {
        "method": "GET", "path": "/api/households",
        "description": "All sample households (id, display name, city only — no case/declared-needs detail).",
        "response": {"households": [{"household_id": "h1", "display_name": "Household A", "city": "Roanoke"}]},
    },
    {
        "method": "POST", "path": "/api/session",
        "description": "Start a new chat session for a household. Resets scenario, history, and audit log.",
        "request": {"household_id": "h1"},
        "response": {"session_id": "3de16d8a22e94c279e5ba26ce166090f", "household_id": "h1"},
    },
    {
        "method": "POST", "path": "/api/chat",
        "description": (
            "Ask a question. Routes to Gemini (if connected) or the offline templates. Every number in "
            "the reply is validated against that turn's tool outputs (see MODEL_CARD.md); an "
            "unverifiable Gemini reply gets one retry, then an honest error."
        ),
        "request": {"session_id": "3de16d8a2...", "message": "Will I lose power and for how long?"},
        "response": {
            "text": "Risk is High (High confidence). ... Estimated restoration: 8.1-14.0 hours (median 10.8), from a seeded Monte Carlo simulation. Not confirmed by the utility.",
            "cards": {"risk": "{...evidence-tagged risk object...}", "restoration": "{...evidence-tagged restoration object...}"},
            "offline": True,
            "fallback": False,
        },
    },
    {
        "method": "POST", "path": "/api/whatif",
        "description": "Apply a scenario chip (block_access, clear_access, add_crews, complete_repairs, reset) to the session.",
        "request": {"session_id": "3de16d8a2...", "action": "block_access"},
        "response": {
            "scenario": {"access_blocked": True, "extra_crews": 0, "repairs_complete": False},
            "before": {"p10_hours": {"value": 8.1}, "p90_hours": {"value": 14.0}},
            "after": {"p10_hours": {"value": 11.1}, "p90_hours": {"value": 17.1}},
            "risk": "{...}", "prep": "{...}", "alerts": "{...}",
        },
    },
    {
        "method": "GET", "path": "/api/audit",
        "description": "Per-session audit log, newest first: inputs, tools called, outputs, validator result, data version, model name, for every chat/whatif turn.",
        "query": {"session_id": "3de16d8a2..."},
        "response": {"audit_log": [{"timestamp": "2026-10-25T00:05:23+00:00", "turn_type": "chat", "tools_called": ["get_risk", "get_restoration_estimate"], "validator": {"valid": True, "unverified": []}, "data_version": "a1b2c3d4e5f6", "model_name": "offline-rules-v1"}]},
    },
    {
        "method": "GET", "path": "/api/dashboard",
        "description": "Storm activity dashboard data for the session: risk, restoration, step timeline, alert matrix, event feed.",
        "query": {"session_id": "3de16d8a2..."},
        "response": {"scenario": "{...}", "risk": "{...}", "restoration": "{...}", "timeline": "{...}", "alerts": "[...]", "events": "[...]"},
    },
    {
        "method": "GET", "path": "/api/settings",
        "description": "Current provider connection state. Never returns the API key itself.",
        "response": {"model": None, "offline_mode": True, "connected": False, "last_error": None},
    },
    {
        "method": "POST", "path": "/api/settings",
        "description": "Set the Gemini API key (pins the first allowlisted model that completes a tool-call round trip) and/or toggle offline mode.",
        "request": {"api_key": "...", "offline_mode": False},
        "response": {"model": "gemini-2.5-flash", "offline_mode": False, "connected": True, "last_error": None},
    },
    {
        "method": "GET", "path": "/api/data-quality",
        "description": "Data issues found while building the risk model: circuit-label join exclusions (ambiguous and unmapped), unrepaired-with-repair-date records, and what's folded in vs. excluded.",
        "response": {
            "circuit_crosswalk": {"unique_pairs_mapped": 107, "ambiguous_pair_count": 14},
            "damage_join": {"total_damage_records": 1659, "joined": 1089, "unmapped": 570},
            "unrepaired_with_repair_date": {"count": 76, "of_unrepaired_total": 76},
            "backtest_summary": {"spearman_rank_correlation": 0.391, "interpretation": "Weak but positive signal..."},
        },
    },
    {
        "method": "GET", "path": "/docs",
        "description": "This page.",
    },
]


def _code(obj):
    if isinstance(obj, (dict, list)):
        return html.escape(json.dumps(obj, indent=2))
    return html.escape(str(obj))


def render_html():
    rows = []
    for ep in ENDPOINTS:
        parts = [f'<section class="endpoint">',
                 f'<h2><span class="method method-{ep["method"].lower()}">{ep["method"]}</span> <code>{html.escape(ep["path"])}</code></h2>',
                 f'<p>{html.escape(ep["description"])}</p>']
        if "request" in ep:
            parts.append(f'<h4>Request body</h4><pre>{_code(ep["request"])}</pre>')
        if "query" in ep:
            parts.append(f'<h4>Query params</h4><pre>{_code(ep["query"])}</pre>')
        if "response" in ep:
            parts.append(f'<h4>Response (example)</h4><pre>{_code(ep["response"])}</pre>')
        parts.append("</section>")
        rows.append("\n".join(parts))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Watt'sNext API docs</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 860px; margin: 40px auto; padding: 0 16px; color: #2E2E2E; line-height: 1.5; }}
  h1 {{ font-size: 24px; }}
  h2 {{ font-size: 17px; margin-top: 32px; }}
  h4 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: #5A5A5A; margin-bottom: 4px; }}
  code {{ background: #F2F2F2; padding: 2px 6px; border-radius: 4px; }}
  pre {{ background: #F2F2F2; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 13px; }}
  .method {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700; color: #fff; }}
  .method-get {{ background: #1F5FA8; }}
  .method-post {{ background: #D2352B; }}
  .endpoint {{ border-top: 1px solid #D9D9D9; padding-top: 16px; }}
  .intro {{ color: #5A5A5A; }}
</style>
</head>
<body>
<h1>Watt'sNext API</h1>
<p class="intro">All routes bind to 127.0.0.1 only. Every number a customer sees traces back to one of these
tool-backed endpoints — see MODEL_CARD.md for the methods behind the numbers, and
<code>/api/data-quality</code> below for exactly what was excluded and why.</p>
{"".join(rows)}
</body>
</html>"""
