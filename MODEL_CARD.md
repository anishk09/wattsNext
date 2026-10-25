# Watt'sNext — Model Card

This covers the four quantitative models behind Watt'sNext's answers: the
risk model, step restoration, the Monte Carlo restoration-time estimate,
and the controls that keep all three honest. Written for a technical judge
who wants to know exactly what's measured, what's assumed, and what isn't
validated yet.

## Purpose

Given a sample household (picked by city), answer four questions a storm
customer actually asks: will I lose power, how long could repairs take,
what should I do to prepare, and do I qualify for alerts. Every number
comes from one of the models below, computed in Python — the language
model (when connected) only calls tools and explains their output; it
never computes a figure itself (enforced by the answer validator, below).

## Inputs

- **AEP sample data package** (`aep-data/`, gitignored, not redistributed):
  ARCOS damage records (`arcos_prod_damage_09_28_Clip.dbf`, 1,659 records,
  Oct 2022–Aug 2026, 75% concentrated in Feb 2025 — one dominant storm
  event), GIS asset tables (customers, transformers, poles, primary/
  secondary conductor, fuse banks, recloser banks, switches), the
  `matched_upstream.txt` premise-to-substation topology file, and the
  `Install_Labor_HackOHIO.xlsx` labor-hour reference workbook.
- **Synthetic elements, clearly labeled as such**: 12 demo households
  (city, declared needs, alert preferences) and their case assignment —
  real circuits, real damage, but which specific household sits on which
  circuit is a replay assumption (see `README.md`).

## Method 1 — Risk: exposure-normalized historical damage rate

**What it replaced**: a rule ("any unrepaired damage on the household's
path ⇒ High, otherwise storm setting decides"). That rule couldn't
distinguish a circuit with one minor fault from one hit repeatedly, and
ignored every circuit's actual damage history.

**Now**: for each circuit, `rate = damage records / asset count on that
circuit` (the "exposure" — customer count for the overall rate; the
circuit's own transformer/primary/secondary/fuse-bank/recloser-bank/
switch count for the per-asset-type rate, since only those six asset
tables carry a trustworthy circuit label — see Data joins below). Raw
rates are then **Poisson-Gamma empirical-Bayes shrunk** toward the
system-wide rate: `shrunk_rate = (α + damage_count) / (β + exposure)`,
where α and β come from a method-of-moments fit to the cross-circuit rate
distribution (isolating the "true" between-circuit variance from Poisson
sampling noise). This pulls thinly-measured circuits toward the system
average instead of letting a single damage record swing their rate to an
extreme.

The shrunk rate is scaled by a **storm-setting multiplier** — calm ×0.6,
moderate ×1.0, severe ×1.6 — a **stated assumption**, not fit from data
(this sample has one storm event to observe, not enough to fit a
multiplier from). The result is banded Low/Moderate/High by fixed
thresholds (the shrunk-rate distribution's 33rd/66th percentiles across
all circuits).

**Confidence** comes from effective sample size: exposure compared to β
(the EB fit's own natural scale). `exposure < β` → Low, `β ≤ exposure <
5β` → Medium, `exposure ≥ 5β` → High. A circuit whose label can't be
trusted for the join (see below) **falls back** entirely rather than
showing a confident-looking number built on nothing.

**Never presented as a calibrated outage probability** — every risk
answer says so explicitly, and the evidence tag on the band reads
"demonstration rule, not a calibrated probability."

### Data joins — and what got excluded

ARCOS damage records carry a free-text `(Substation, Circuit)` pair
(e.g. `STATION2`/`CIR60`), not the asset tables' numeric `circuit_id`.
There's no supplied crosswalk, so `scripts/_circuit_join.py` builds one
from the union of the six asset tables that carry **both** fields. A
`(station, circuit)` pair seen with more than one `circuit_id` across
those tables is **ambiguous** and excluded, never guessed at.
`NEAR_FID` (a spatial nearest-feature index in the damage extract) is
**never used** — it's an analysis artifact, not a validated key.

Result: **1,089 of 1,659 damage records (66%) joined**; 570 unmapped
(the `(station, circuit)` pair never appears in any asset table), 14
`(station, circuit)` pairs excluded as ambiguous. Full counts and the
exact excluded pairs: `GET /api/data-quality`.

**This directly affected the demo.** The `wirepole_vinton` case's circuit
(`STATION29`/`CIR6`) is one of the 14 ambiguous pairs — it maps to both
`circuit_id` `0000005` and `0000006` depending which asset table you ask.
Rather than silently pick one, `cases.json` carries `risk_status:
"ambiguous_circuit_label"` for it, and `engine.check_risk_fallback()` —
a fallback condition **separate** from the existing path-validity one —
makes the risk answer honestly fall back for that household, while the
restoration estimate (which doesn't depend on the population-level join)
keeps working normally.

### Backtest

Trained on damage reported before 2025-02-01 (Feb 2025 is 75% of all
records — the one storm this sample actually captures), evaluated against
damage reported on/after that date: does the trained rate rank which
circuits the storm hits?

- **Spearman rank correlation: 0.391** — pre-storm history correlates
  with storm-time damage, but weakly.
- Full methodology and numbers: `data/backtest.json`.

**Honest read**: a positive, non-trivial signal — meaningfully better
than chance — but nowhere near strong enough to lean on alone. Treat the
risk band as a starting point for conversation, not a forecast. With one
storm event and ~29 damaged circuits in this sample, there isn't enough
data to validate a stronger claim, and the UI doesn't make one.

## Method 2 — Step restoration: real upstream protective devices

**What it replaced**: a household's restoration time counted every
damage item assigned to its case, regardless of where on the circuit it
was.

**Now**: `scripts/build_data.py` extracts a real upstream device chain
per case from `matched_upstream.txt` — one representative premise on
that circuit, household's own transformer → protective devices (nearest
first) → circuit breaker — each device hop joined to its real
`normal_sta` (Closed/Open) via `location_n` against
`Recloser_Bank_Clip`/`Fuse_Bank_Clip`/`Switch_Clip` (chain IDs don't
match any table's own `id` field; location codes do — this join was
discovered while building this feature).

`engine.restoration_phases()` finds the **nearest normally-closed
protective device** and splits damage into **local** (blocks the
household: its own transformer always, plus anything matched to a
device at or before that nearest-closed device) vs **upstream** (matched
to a device type beyond it — isolated by that device; crews still fix
it, but it doesn't extend this household's time). Non-device damage
(primary/secondary/pole) has no finer position in the source data than
"this circuit," so it's **conservatively assumed local** — a stated
assumption, not a measurement.

**Honest result for the actual demo data**: all 4 real cases' damage is
transformer/primary/pole, which this model always treats as local, so
the restoration numbers are **unchanged** from before this feature
existed (verified: the acceptance ranges still hold). The mechanism
itself is real and tested — proved with a synthetic case (a real-shaped
chain plus device-type damage beyond the nearest closed device) in
`tests/test_engine.py::StepRestoration` — but this dataset's granularity
doesn't give it anything to filter on the cases we actually have.

## Method 3 — Monte Carlo restoration time (P10/P50/P90)

**What it replaced**: `reference_effort_hours × 0.75` / `× 1.5`, a flat
deterministic multiply.

**Now**: a **seeded** Monte Carlo simulation (2,000 runs) over two
stated-assumption distributions, neither fit from data (this sample has
no historical per-job duration variance to fit against):

- **Labor hours per job**: `triangular(0.6×, 1.0×, 1.8× reference)` —
  asymmetric, replacing the old symmetric-looking flat multiply.
- **Crew availability**: a `uniform(0, 1.5)` hour dispatch/travel delay
  sampled per crew before its first job.

The seed is `sha256(case_id | access_blocked | extra_crews)` truncated
to an int — **stable across process restarts** (Python's built-in
`hash()` of strings is deliberately randomized per-process and would
have silently broken reproducibility). The same case + scenario always
reproduces the same P10/P50/P90.

**Acceptance-number relationship** (documented in
`tests/test_engine.py::TransformerAcceptanceRanges`'s docstring): the
original fixed-band acceptance numbers were baseline 6.7–13.5 h,
blocked-access 9.7–16.5 h. The new P10/P50/P90: baseline **8.1 / 10.8 /
14.0 h**, blocked-access **11.1 / 13.7 / 17.1 h**. Narrower but shifted
later — the crew-delay term has no symmetric downside, and the
triangular distribution's long right tail pulls the upper percentiles up
versus the old flat multiply. `reference_effort_hours` itself (9.0 h) is
unchanged — same labor-workbook math as before.

## Controls

- **Answer validator** (`concierge/validator.py`): every number and band
  word in a reply must appear in that turn's tool outputs (checked
  against the full JSON of the cards dict, including evidence notes) or
  the reply is rejected. The online (Gemini) path gets one retry with an
  explicit correction instruction; if that also fails, the customer sees
  an honest error plus the same answer rebuilt from the offline
  templates (deterministic from tool output, always valid).
- **Audit log** (`GET /api/audit`, per session): timestamp, turn type,
  inputs, tools called with args, outputs, validator result,
  `data_version` (a sha256 fingerprint of the `data/` files that drove
  the answer), and `model_name`.
- **Input validation**: every POST endpoint requires a JSON object body;
  string fields are type/length/non-empty checked (message capped at
  2,000 characters); malformed input returns 400 with a clear message.
- **Privacy filter** (`concierge/privacy.py`): redacts long ID numbers
  (premise/equipment, 8+ digits), location codes with an embedded letter
  block, GIS-precision coordinates (7+ decimal digits), and
  facility-location keywords from every chat reply before it leaves the
  server. The data files never carry these fields in the first place
  (see `README.md`), so this is a backstop, not the primary defense —
  violations are logged to the audit entry so the control is
  demonstrably live, not just assumed.

## Assumptions (all stated, all evidence-tagged in the UI)

- Household-to-case assignment (which real circuit a demo household sits
  on) is a replay assumption.
- Storm-setting rate multiplier (0.6× / 1.0× / 1.6×): not fit from data.
- Risk band thresholds: percentiles of the shrunk-rate distribution
  across this sample's circuits, not a utility-published standard.
- Non-device damage (primary/secondary/pole) is assumed local to the
  household for step restoration — no finer position in the source data.
- Monte Carlo distribution shapes (triangular labor hours, uniform crew
  delay) and their parameters: stated assumptions, not fit from data.
- Indirect labor multiplier (4.5×) and all labor-hour figures: from the
  supplied workbook, except primary-conductor and capacitor/light/step-
  transformer rates, which have no workbook entry and use a documented
  proxy category (see `README.md`).

## Limits / what is NOT validated

- The risk model's backtest shows a weak-to-moderate signal (ρ=0.39)
  from one storm event — not independently validated against a second
  storm, and not a calibrated probability under any interpretation.
- 34% of damage records (570/1,659) never joined to a circuit at all and
  are excluded from every rate computation — the "system rate" and every
  circuit's rate are a lower bound on true damage, not a complete count.
- Step restoration's phase-filtering has no real-data case where it
  changes a restoration number — only synthetic-case test coverage
  proves the mechanism itself works.
- The answer validator checks for *verifiability* (every number traces
  to tool output), not *correctness* of the underlying model — it can't
  catch a tool itself computing something wrong, only the model
  inventing something the tools never said.
- No live Gemini call has been exercised in this environment (no network
  access during development); the online path is implemented against the
  documented REST API shape but unverified end-to-end. Offline mode
  (fully tested) is the demo-safe fallback.
- Never implemented, on purpose: live weather/outage/crew-position data,
  shelter status, compensation/credit eligibility, or any inference of
  health information.
