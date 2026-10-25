# Watt'sNext — AEP Outage Concierge

*Know what's next when the power goes out.*

A customer-facing chat assistant for a storm. Python computes every number
(risk, restoration time, alerts); the language model only interprets
questions, calls tools, and explains results in plain language.

## Run it

```bash
pip install -r requirements.txt
python3 server.py
# open http://127.0.0.1:8000
```

Add your Gemini API key in Settings (gear icon) to enable the AI
conversation, or turn on "Offline explanation mode" to run entirely on
deterministic templates — no key needed. The app binds to 127.0.0.1 only;
the key is held in memory for the process and is never written to disk or
logged.

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
server.py                  Starlette routes, in-memory sessions, chat orchestration
concierge/
  engine.py                 Pure calculations: restoration effort, risk band, confidence, fallback
  cases.py                  Loads data/cases.json and data/sample.json
  customer_services.py      Preparation guidance and alert message generation
  tools.py                  The 4 tools exposed to the model, each evidence-tagged
  gemini.py                 Stdlib REST client: model listing, pinning, tool-call round trip
  chat.py                   Routes a message to the Gemini loop or offline templates
data/
  labor_reference.json      Install/removal hours by category, ILM, sourced from the AEP workbook
  cases.json                 4 real replay cases + 1 synthetic "no validated path" case
  sample.json                12 sample households, 3 per real case
scripts/
  build_data.py              One-time ETL from aep-data/ → data/*.json (no third-party deps)
  _dbf.py, _xlsx.py           Minimal stdlib readers for the raw shapefile/workbook formats
static/                      Plain HTML/CSS/JS, no build step
tests/                       unittest suite
aep-data/                    Organizer-supplied raw package (gitignored — not redistributed)
```

## Data provenance

The 4 real cases are grounded in the actual AEP HackOHI/O sample package
(`aep-data/`), not fully synthetic:

| Case | Station/Circuit | Cities | Why chosen |
|---|---|---|---|
| `transformer_roanoke` | STATION24/CIR114 | Roanoke, Hardy, Boones Mill | Real unrepaired transformer damage; 25 kVA is the modal size on this circuit |
| `wirepole_vinton` | STATION29/CIR6 | Vinton, Goodview, Blue Ridge | Real unrepaired primary-wire + pole damage |
| `wire_montvale` | STATION2/CIR60 | Montvale, Blue Ridge | Real unrepaired primary-wire damage |
| `calm_roanoke` | STATION10/CIR95 | Roanoke | Zero damage records — deliberately paired with the Roanoke transformer case to show risk follows the upstream path, not the city name |
| `no_path` | — | Roanoke | Synthetic: no validated upstream path, to exercise the cannot-predict fallback |

No premise IDs, addresses, equipment IDs, or precise coordinates reach the
browser — only city names and circuit-level damage summaries.

## Assumptions (shown in the UI as evidence tags)

- **Reference labor hours are crew-hours.** One crew per job; independent
  jobs run in parallel when crews are free (greedy list-scheduling across
  crews); the household's power returns only when every job on its path
  finishes.
- **Indirect labor multiplier = 4.5**, taken directly from the supplied
  workbook. It already covers drive time, safety briefing, and setup — not
  added again.
- **Scenario range = 75%–150%** of reference effort. Labeled "scenario
  range, not a confidence interval" everywhere it's shown.
- **Blocked access adds a flat +3 h assumption** to both ends of the range
  (not a workbook rate — there wasn't one for this).
- **Primary-conductor repair hours** have no per-span rate in the supplied
  workbook; the closest documented proxy (Dead-End/conductor-termination
  category) is used and tagged `Assumption`, not `Source data`.
- **Household-to-case assignment is always a replay assumption** — this is
  why confidence never exceeds Medium for any of the real cases.
- **Risk band and confidence are demonstration rules**, not calibrated
  probabilities, and are labeled as such everywhere.

## What is and isn't verified

- **Verified against the acceptance tests in `tests/test_engine.py`:** the
  transformer case computes exactly 6.7–13.5 h baseline and 9.7–16.5 h with
  blocked access, matching the brief's required numbers.
- **Not verified:** a live Gemini call. `concierge/gemini.py` implements the
  list-models → pin-a-model → tool-call round trip against the real REST
  API, but this sandbox has no API key or outbound network access to
  exercise it end-to-end. Offline mode (fully tested) is the guaranteed
  fallback path and is what the demo should lean on if the live call is
  flaky.
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

## Deploying to Vercel

The repository includes `vercel.json` and `api/index.py` for Vercel's Python
runtime. Import the repository into Vercel, then configure these environment
variables in the Vercel project settings:

- `DATABASE_URL` — pooled Neon connection string
- `DATABASE_URL_UNPOOLED` — direct Neon connection string for migrations only
- `NEON_BRANCH` — production branch identifier
- `GEMINI_API_KEY` — optional server-side Gemini key
- `GEMINI_MODEL` — optional model override, default `gemini-2.5-flash`
- `WATTSNEXT_USE_NEON=true`

Do not commit `.env.local` or API keys. Run migrations before the first
production deployment with `python scripts/migrate.py` using the direct Neon
URL. Vercel handles the Python function; it does not run the Dockerfile.

## Docker deployment

Build and run the included container with:

```bash
docker compose up --build
```

The container listens on port 8000 and uses `.env.local` only for local
development. For hosted Docker, inject secrets through the platform's secret
manager instead.

## CI/CD release process

Every pull request runs repository secret checks, Python compilation and
tests, JavaScript/build validation, migration-file checks, and a production
Docker smoke test. Dependabot keeps Python packages, npm packages, and GitHub
Actions current.

Production deployment is intentionally tag-gated. After the `production`
GitHub environment approval, pushing a tag such as `v1.0.0` deploys through
Vercel when `VERCEL_TOKEN`, `VERCEL_ORG_ID`, and `VERCEL_PROJECT_ID` are set as
repository or environment secrets. Neon migrations should be run separately
against the direct production connection before the deployment is approved.
