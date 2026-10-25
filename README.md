# Watt'sNext — AEP Outage Concierge

*Know what's next when the power goes out.*

A customer-facing chat assistant for a storm. Python computes every number
(risk, restoration time, alerts); the language model only interprets
questions, calls tools, and explains results in plain language.

**Methods** (see `MODEL_CARD.md` for the full writeup): risk is an
exposure-normalized historical damage rate per circuit, empirical-Bayes
shrunk toward the system-wide rate; restoration time is a seeded Monte
Carlo simulation returning P10/P50/P90, filtered by step restoration (only
damage between the household and its nearest closed upstream protective
device counts); every number in a reply is checked against that turn's
tool output before it's shown. `GET /docs` lists every API endpoint;
`GET /api/data-quality` shows exactly what was excluded from the risk
model and why.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env   # then put your Gemini key in .env
python3 server.py
# open http://127.0.0.1:8000
```

**API key, in order of priority:**
1. `GEMINI_API_KEY` in the shell environment.
2. `GEMINI_API_KEY` in a `.env` file in the project root (copy
   `.env.example`, which ships with an empty key — `.env` itself is
   gitignored and was never committed).
3. Neither present → the Settings dialog (gear icon) accepts a key, or
   "Offline explanation mode" runs entirely on deterministic templates,
   no key needed at all.

If a key is found via (1) or (2), the server connects automatically on
startup — no need to open Settings before chatting. Settings then shows
"Key loaded from .env — model: &lt;name&gt;" instead of an editable key
field; the key itself is never displayed, logged, or returned by any API
response. The app binds to 127.0.0.1 only; the key lives in memory for
the process only.

To regenerate `data/*.json` from the raw AEP package (only needed if the
source package in `aep-data/` changes):

```bash
python3 scripts/build_data.py
```

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

## Folder map

```
server.py                  Starlette routes, sessions, audit log, input validation, chat orchestration
MODEL_CARD.md               Full method writeup: risk model, step restoration, Monte Carlo, controls
concierge/
  engine.py                 Pure calculations: risk (historical rate), step restoration, Monte Carlo
  cases.py                  Loads data/cases.json and data/sample.json
  customer_services.py      Preparation guidance and alert message generation
  tools.py                  The 5 tools exposed to the model, each evidence-tagged
  gemini.py                 Stdlib REST client: model listing, pinning, tool-call round trip
  chat.py                   Routes a message to the Gemini loop or offline templates
  validator.py               Answer validator: every number/band must trace to tool output
  privacy.py                 Redacts premise/equipment IDs, coordinates, facility keywords
  data_version.py            Sha256 fingerprint of data/ for the audit log
  env_config.py               Reads GEMINI_API_KEY from the shell env or .env (stdlib, no python-dotenv)
  api_docs.py                Renders GET /docs
data/
  labor_reference.json      Install/removal hours by category, ILM, sourced from the AEP workbook
  cases.json                 4 real replay cases + 1 synthetic "no validated path" case, each with
                              a circuit_id, risk_status, and a real upstream_chain
  sample.json                12 sample households, 3 per real case
  risk_model.json            Per-circuit and per-asset-type historical rates, EB fit, band thresholds
  backtest.json               Risk-model backtest methodology and results
  data_quality.json           Join exclusions, ambiguous pairs, the bogus-repair-date finding
scripts/
  build_data.py              ETL from aep-data/ → cases.json/sample.json/labor_reference.json
  build_risk_model.py         ETL from aep-data/ → risk_model.json/backtest.json/data_quality.json
  _circuit_join.py            Shared (station, circuit) -> circuit_id crosswalk, used by both
  _dbf.py, _xlsx.py           Minimal stdlib readers for the raw shapefile/workbook formats
static/                      Plain HTML/CSS/JS, no build step
tests/                       unittest suite (62 tests)
aep-data/                    Organizer-supplied raw package (gitignored — not redistributed)
```

Rebuild order after changing `aep-data/`: `build_data.py` then
`build_risk_model.py` (cases.json's `upstream_chain` needs the crosswalk
that `build_risk_model.py` also uses, but both scripts import it fresh
from `_circuit_join.py`, so either order works — this note is about intent,
not a hard dependency).

## Data provenance

The 4 real cases are grounded in the actual AEP HackOHI/O sample package
(`aep-data/`), not fully synthetic:

| Case | Station/Circuit | Cities | Why chosen |
|---|---|---|---|
| `transformer_roanoke` | STATION24/CIR114 | Roanoke, Hardy, Boones Mill | Real unrepaired transformer damage; 25 kVA is the modal size on this circuit |
| `wirepole_vinton` | STATION29/CIR6 | Vinton, Goodview, Blue Ridge | Real unrepaired primary-wire + pole damage. This circuit's label is **ambiguous** in the GIS asset tables (maps to two different `circuit_id`s) — risk honestly falls back for it; restoration still works (see `MODEL_CARD.md`) |
| `wire_montvale` | STATION2/CIR60 | Montvale, Blue Ridge | Real unrepaired primary-wire damage |
| `calm_roanoke` | STATION10/CIR95 | Roanoke | Zero damage records — deliberately paired with the Roanoke transformer case to show risk follows the upstream path, not the city name |
| `no_path` | — | Roanoke | Synthetic: no validated upstream path, to exercise the cannot-predict fallback |

No premise IDs, addresses, equipment IDs, or precise coordinates reach the
browser — only city names and circuit-level damage summaries.

## Assumptions (shown in the UI as evidence tags; full detail in `MODEL_CARD.md`)

- **Reference labor hours are crew-hours.** One crew per job; independent
  jobs run in parallel when crews are free (greedy list-scheduling across
  crews); the household's power returns only when every job *on its
  segment* finishes — only damage between the household and its nearest
  closed upstream protective device counts (step restoration).
- **Indirect labor multiplier = 4.5**, taken directly from the supplied
  workbook. It already covers drive time, safety briefing, and setup — not
  added again.
- **Restoration time is a seeded Monte Carlo simulation** (2,000 runs)
  over labor-hour variance (triangular 0.6×/1.0×/1.8× per job) and crew
  availability (0–1.5 h dispatch delay per crew), returning P10/P50/P90 —
  not the old flat 75%–150% multiply. Seeded on case + scenario, so the
  same inputs always reproduce the same numbers.
- **Blocked access adds a flat +3 h assumption** to P10/P50/P90 alike
  (not a workbook rate — there wasn't one for this).
- **Primary-conductor repair hours** have no per-span rate in the supplied
  workbook; the closest documented proxy (Dead-End/conductor-termination
  category) is used and tagged `Assumption`, not `Source data`.
- **Household-to-case assignment is always a replay assumption.**
- **Risk is an exposure-normalized historical damage rate per circuit**
  (empirical-Bayes shrunk toward the system-wide rate, storm setting
  scales it as a stated assumption), never a calibrated probability — see
  `MODEL_CARD.md` for the backtest (weak-to-moderate signal, honestly
  reported) and exactly how circuit labels were joined and what was
  excluded.

## What is and isn't verified

- **Verified against the acceptance tests in `tests/test_engine.py`:** the
  transformer case's Monte Carlo P10/P50/P90 (8.1/10.8/14.0 h baseline,
  11.1/13.7/17.1 h blocked-access) is reproducible run to run, and its
  relationship to the brief's original fixed-band numbers (6.7–13.5 h /
  9.7–16.5 h) is documented in the test file and `MODEL_CARD.md`.
- **Not verified:** a live Gemini call. `concierge/gemini.py` implements the
  list-models → pin-a-model → tool-call round trip against the real REST
  API, but this sandbox has no API key or outbound network access to
  exercise it end-to-end. Offline mode (fully tested) is the guaranteed
  fallback path and is what the demo should lean on if the live call is
  flaky.
- **Not independently validated:** the risk model's backtest (Spearman
  ρ=0.39 from the one storm event in this sample) and step restoration's
  phase-filtering (no real demo case has upstream-of-device damage to
  exercise it — proven with a synthetic case instead). Both are honestly
  scoped as "the mechanism is real and tested, not that it's been proven
  on this specific data." Full detail in `MODEL_CARD.md`.
- **Verified in a real browser** (headless Chrome, driven via CDP since
  this machine's `--window-size` flag floors around 500px and silently
  clamps anything smaller — a true 375px viewport needs a device-metrics
  override) at both desktop and a true 375px mobile width: topbar, starter
  questions, what-if chips, risk/restoration/alerts cards, and SMS-style
  alert previews all wrap correctly with no horizontal overflow, in both
  flows (direct chat and the what-if chips). One real bug was caught and
  fixed this way: the three-lane card's "What you can do" lane rendered
  empty whenever a restoration estimate was shown without prep guidance
  alongside it (the compound "will I lose power and for how long" question,
  and every what-if chip response) — restoration answers now always
  include prep guidance, and the UI has a defensive fallback besides.
- **Never implemented on purpose:** live weather/outage/crew-position data,
  shelter status, compensation/credit eligibility, or any inference of
  health information — all explicitly out of scope per the brief's hard
  rules. These questions get an honest "I don't have that" answer pointing
  to the official Appalachian Power and Red Cross sites.

## Controls and visibility

- **Answer validator**: every number and band word in a reply must appear
  in that turn's tool output or the reply is rejected (one retry online,
  then an honest error). See `concierge/validator.py`.
- **Audit log**: `GET /api/audit?session_id=...` — inputs, tools called,
  outputs, validator result, data version, model name, for every turn.
- **Privacy filter**: `concierge/privacy.py` redacts premise/equipment IDs,
  coordinates, and facility keywords from every reply before it leaves
  the server (a backstop — the data files never carry these fields).
- **API docs**: `GET /docs` lists every endpoint with a real request/
  response example. `GET /api/data-quality` shows exactly what was
  excluded from the risk model and why.
