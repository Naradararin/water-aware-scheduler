# Water-Aware Compute Scheduler (V0)

A two-signal (carbon + water) co-optimizing scheduler for deferrable compute
workloads — built as a learning project and portfolio piece, not a commercial
product.

## Why this exists — and prior art (read this first)

**Correction, added after further research:** an earlier version of this
README claimed this was the first open-source carbon+water co-optimizing
scheduler. That was wrong, and was based on checking only one architecture
(Carbon Aware SDK) rather than searching broadly. It isn't first.

**[WaterWise](https://arxiv.org/pdf/2501.17944)** (Zenodo, 2025) already is —
its own authors describe it as "the first open-source framework to enable
exploration of carbon and water [sustainability trade-offs]," evaluated
against real production traces (Google Borg, Alibaba), and it's more
sophisticated than this project: it models a **water scarcity factor**
that actually influences scheduling decisions (weighting a liter of water
by how scarce it is in that specific region, region-by-region and
time-by-time). This project has a much narrower version: a single constant
Thailand baseline-water-stress score (see `water/scarcity.py`), included
for reporting context only — it cannot influence which region/time gets
picked, since a constant applied equally to every candidate is
mathematically inert under the min-max normalization this project's
optimizer uses. See "Known limitations" below for why, and what it would
take to make it real. If you want the real research-grade version, go
read WaterWise first — this project doesn't replace it.

**What this project actually is:** a small, readable reimplementation built
specifically as a companion to the Green Software Foundation's
[Carbon Aware SDK](https://github.com/Green-Software-Foundation/carbon-aware-sdk)
ecosystem — same data backbone (ElectricityMaps), same pluggable
data-source pattern, extended from the SDK's single-signal
(`EmissionsData.Rating`, carbon-only) core model to two signals. As far as
this project's research went, nothing plays that specific role in the SDK's
own ecosystem today. That's a narrower, more honest claim than "first
open-source" — and it's the actual value here: a learning artifact for
understanding the carbon/water trade-off and Stage-C agent-building
practice, not a research contribution.

Carbon and water don't always agree: a region running mostly on hydropower
can look great on carbon and bad on water (reservoir evaporation); a region
with more thermal generation can be the reverse. The demo run below shows
this happening with real (mock) numbers — see the confidence warnings next
to the output, though, before treating any of it as solid.

## The trick that makes this solo-buildable

There's no real-time public water API. So instead of trying to find one, this
derives water intensity from the same power-mix data that carbon APIs
(ElectricityMaps) already provide for free:

```
water_intensity(region, time) = Σ  power_mix_fraction[source] × water_factor[source]
```

Water factors are sourced from Macknick et al. (2012), *Environmental Research
Letters* — see `wascheduler/water/factors.py` for the full table, sourcing,
and confidence notes. **These are order-of-magnitude estimates for a
prototype, not measured plant-level data** — read the caveats in that file
before relying on these numbers for anything beyond learning/demo purposes.

## Quickstart

```bash
pip install -r requirements.txt
python demo.py
```

This runs entirely on **mock data** (see `wascheduler/sources/mock.py`) — no
API key needed to see it work end-to-end.

### Switching to real data

**Important — read before signing up:** ElectricityMaps' permanent free tier
is limited to **a single zone**, and is split into three specific paths:
a 14-day **Trial** (multi-zone, all signals, but expires), a **Home
Assistant** license (permanent but tied to a restricted `/home-assistant`
endpoint that likely doesn't include the power-mix breakdown this project
needs), and **Academic** access (requires an institutional email). There
isn't a plain "general-purpose, permanent, multi-zone, free" option — this
was confirmed by testing the actual signup flow, not assumed.

This project was tested against real data using the **14-day Trial**
(selected "Asia & Oceania" + "EU + UK" zones, "Carbon Intensity" +
"Electricity Mix" signals). After the trial expires, real-data mode simply
stops working and the demo automatically falls back to mock — no code
changes needed either way.

1. Get a key via whichever path fits you (see caveat above):
   https://www.electricitymaps.com/free-tier-api
2. `cp .env.example .env` and fill in `ELECTRICITYMAPS_API_KEY`
3. Run `python demo.py` — it auto-detects the key and switches to
   `ElectricityMapsSource` for you (see `get_source()` in `demo.py`).
   No manual code edits needed.
   Note: `get_signals_range()` isn't implemented for the real source (see
   `sources/electricitymaps.py`) — real-data mode uses one "latest" reading
   per region rather than an hourly window like mock mode does.

### Optional: LLM-generated explanations

By default, `ScheduleDecision.reasoning` is a plain f-string built from the
same numbers the optimizer already computed. If you set an NVIDIA NIM API
key, that field is instead filled in by an LLM call that writes a fresh,
plain-English explanation grounded in those same numbers (see
`wascheduler/llm/reasoning.py`). This is an explanation layer only — it
runs *after* `schedule_job()` has already deterministically picked the
region/time via min-max normalized scoring, and has no way to influence
that choice.

1. Get a free key: https://build.nvidia.com/settings/api-keys
2. Add `NVIDIA_NIM_API_KEY` to your `.env` (see `.env.example`)
3. Run `python demo.py` as usual — no other changes needed.

If the key is missing, or the API call fails for any reason (network,
rate limit, bad key), it silently falls back to the plain f-string —
this layer is optional and additive; nothing else in the project depends
on it.

### Optional: LLM advisory second opinion (non-authoritative)

Same NVIDIA NIM key also enables a second, separate LLM call per decision
(see `wascheduler/llm/advisory.py`, wired into `demo.py`): after
`schedule_job()` has already picked a region/time, `advisory_reconsideration()`
asks the LLM to compare that choice against its best cross-region
runner-up (including drought context) and say whether it's worth a
second look. It returns `{should_reconsider, reason, checked}` and
**never reads back into or modifies the actual decision** — same
one-way-street constraint as the reasoning layer above, just asking a
different question ("is this worth reconsidering?" instead of "why was
this picked?"). This is explicitly a first, cautious step toward a
possible future V2 mode (see Roadmap) where an LLM might eventually be
allowed to influence scheduling in narrow, guardrailed cases — nothing
in the repo does that yet.

Sample output (`python demo.py`, real ElectricityMaps + NIM data, France
and Germany both under real "Alert" drought conditions at the time):

```
water_only   -> region=DE   carbon=  7900.0 gCO2 (+68.4%)  water=  21.42 L (+56.9%)
             reasoning: We chose to run the job in region DE...
             advisory (informational only, does not change the decision): reconsider=True
             The chosen region DE has a water intensity of 0.43 L/kWh, which is relatively
             low, but Germany is experiencing Alert drought conditions...
```

This module doubles the NIM calls `demo.py` makes per run (one for
reasoning, one for advisory, per decision — 18 total across the 3
sample jobs × 3 strategies) — see the rate-limit note in "Known
limitations" below.

**Two targeted, non-general fabrication guards**, both added after live
testing caught real failures (not hypothetical ones) — see
`advisory.py`'s own docstrings for the full story of each:
1. Reuses `reasoning.py`'s job-location guard.
2. A second guard (`_reason_claims_unsupported_drought_status`) catches
   the LLM asserting a drought severity (Alert/Warning/etc) for a region
   whose name never actually appears in the real bulletin text — e.g. an
   observed case where the model claimed Norway was in "Baltic Sea
   region" Alert conditions when the real bulletin never mentions Norway
   at all. This guard checks for the severity word and the region name
   co-occurring in the *same clause* (sentences split on `.!?`, then
   comma/semicolon as a fallback) rather than anywhere in the whole
   response — an earlier whole-text version of this check produced false
   positives, discarding legitimate responses that correctly described
   one region's real drought status while merely *naming* a different
   region elsewhere in the same sentence.

Like the reasoning-layer guard, **these are targeted backstops for the
specific failure modes observed during testing, not general hallucination
detectors** — an LLM can invent ungrounded claims in many other phrasings
neither guard will catch. Any guard hit, parse failure, missing key, or
network error collapses to `should_reconsider=False` — this module is
deliberately built to fail toward "no concern" rather than toward
inventing one, since an advisory layer that's wrong in the "concerning"
direction is more dangerous, especially as a stepping-stone toward a mode
where "reconsider" might eventually change real decisions.

## Who this is for (and who it isn't)

Be precise about this, because it's easy to blur: this scheduler is useful
to whoever **controls where a compute job runs** — a cloud provider, a
data-center operator, an ML platform team. It is **not** a tool for
communities living near a data center's water source — they have no lever
to pull here; nothing in this repo gives them decision-making power over
where a job gets scheduled.

If the goal is informing or empowering a community near a water-stressed
data center, that's a different project (a transparency/monitoring
dashboard, not a scheduler) — don't conflate the two just because both
involve "water" and "data centers."

## What the demo shows

Running `python demo.py` schedules sample jobs three ways — carbon-only,
water-only, and balanced — and compares each to a naive baseline (run
immediately in a fixed home region). Watch for cases where **carbon-only and
water-only pick different regions** — that's the core finding this project
demonstrates: carbon-aware scheduling and water-aware scheduling are not the
same optimization problem.

**Also watch the `[!]` confidence warnings** printed next to results — they
flag when a decision leans on power-mix sources (e.g. hydro, gas) whose
water factor is marked low-confidence in `water/factors.py`. In the current
mock data, the "carbon-only" strategy's headline result depends ~87% on
low-confidence data — treat that result as "the mechanism works," not "this
number is accurate."

## Aggregate evaluation across the full alpha/beta range

`python -m wascheduler.aggregate_evaluate` (see `wascheduler/aggregate_evaluate.py`)
runs 50 synthetic jobs through baseline + optimizer and reports carbon/water
saved vs. baseline as an **aggregate-totals ratio**:
`(sum(baseline) - sum(optimized)) / sum(baseline) * 100`. This is the
headline number because it weights every job by its actual footprint — an
earlier version of this evaluation averaged each job's own saved-% instead,
which let a handful of small-baseline jobs swing the mean by hundreds of
percentage points (one outlier alone was -1584%) without ever appearing in
the totals. That per-job mean/median/min/max/stdev is still reported by the
module, but as a secondary, outlier-sensitive diagnostic — not the headline.

Sweeping `alpha` (carbon weight) from 1.0 to 0.0 (`beta = 1 - alpha`), seed=42,
50 jobs, gives:

| alpha | beta | carbon saved (aggregate %) | water saved (aggregate %) |
|------:|-----:|----------------------------:|----------------------------:|
|  1.0  | 0.0  | **+89.59**                  | -36.38                      |
|  0.8  | 0.2  | +89.59                      | -36.38                      |
|  0.54 | 0.46 | +80.65                      | -31.47                      |
|  0.53 | 0.47 | +1.74                       | +10.32                      |
|  0.52 | 0.48 | -69.96                      | +47.53                      |
|  0.5  | 0.5  | -73.53                      | **+49.31**                  |
|  0.2  | 0.8  | -73.65                      | +49.33                      |
|  0.0  | 1.0  | -73.88                      | +49.34                      |

**The finding: this is a step function, not a gradient.** Carbon and water
savings stay essentially flat across most of the alpha range and then flip
almost entirely within a narrow band around **alpha ≈ 0.53**, rather than
trading off smoothly as alpha decreases. Two things explain why:

1. **The mock region set is small and clusters into two camps.** FR
   (nuclear-heavy) and NO (hydro-heavy) are both low-carbon/high-water; DE
   and TH (gas/coal-leaning) are both high-carbon/low-water (see per-region
   numbers in "Why this exists" above). With only 4 regions forming two
   tight clusters, there's little middle ground for the optimizer's
   min-max score to land on — most jobs' argmin flips from "carbon cluster"
   to "water cluster" over a similar, narrow range of alpha, so the
   *aggregate* result flips sharply too instead of drifting.
2. **`alpha=0.5` does not mean "50/50 outcome."** Because the min-max
   normalization rescales carbon and water to [0, 1] independently per job
   before combining them, whichever axis has the tighter relative spread
   in a given job's candidate set exerts more effective pull on the combined
   score. The flip point landing near alpha≈0.53 rather than exactly 0.5 is
   a symptom of that asymmetry, not a coincidence.

**Practical takeaway:** for this scheduler on this mock data, there is no
"mild compromise" region of alpha — you get close to the pure-carbon-only
outcome (+89.6% carbon / -36.4% water) or close to the pure-water-only
outcome (-73.9% carbon / +49.3% water), depending on which side of ~0.53
you land on. Treat any alpha/beta choice near the boundary as unstable
(compare the alpha=0.53 vs 0.52 rows above — a 0.01 change flips the sign
of both metrics), and don't read "balanced, alpha=0.5" as a moderate
setting; on this data it behaves like the water-only extreme. Whether a
larger/more granular region set (real ElectricityMaps data across many
zones) would smooth this into a true gradient instead of a step is open —
this project's mock profile count (4) is too small to tell.

## Project structure

```
wascheduler/
├── models.py              # Region, Job, SignalReading, ScheduleDecision
├── sources/
│   ├── base.py             # abstract interface
│   ├── mock.py              # offline testing, no API key needed
│   └── electricitymaps.py   # real data via ElectricityMaps API
├── water/
│   ├── factors.py           # water intensity table (Macknick et al. 2012)
│   └── derive.py             # power-mix -> water intensity
├── scheduler/
│   ├── baseline.py           # naive "run now" strategy
│   └── optimizer.py           # two-signal co-optimizer (min-max normalized)
├── llm/
│   ├── reasoning.py          # optional LLM-generated decision explanations (NVIDIA NIM)
│   ├── drought_context.py    # minimal RAG layer: live EU drought bulletin excerpt
│   └── advisory.py           # Stage 1 advisory second opinion (non-authoritative)
└── evaluate.py              # % carbon/water saved vs. baseline
```

## Roadmap

- **V0 (this)** — mock + real data sources, co-optimizer, baseline comparison,
  optional LLM-generated explanations of each decision (see "Optional:
  LLM-generated explanations" above)
- **V1 (this)** — aggregate evaluation across many synthetic jobs
  (`wascheduler/aggregate_evaluate.py`), reported as an aggregate-totals
  ratio rather than an outlier-sensitive per-job average, swept across the
  full alpha/beta range — see "Aggregate evaluation" above. Not a benchmark
  against WaterWise's published figures (different data, different
  scheduler — see the module's docstring and "Why this exists" above).
- **V2 (in progress)** — an LLM/agent layer that actually *reasons over* the
  carbon/water trade-off and influences which region/time gets picked.
  **Stage 1** of this is built: `wascheduler/llm/advisory.py`'s
  `advisory_reconsideration()`, wired into `demo.py` (see "Optional: LLM
  advisory second opinion" above), asks an LLM whether an already-made
  decision is worth a second look. It's still non-authoritative — it only
  flags a concern for a human to read, it does not change the decision.
  The full V2 goal (an LLM/agent actually allowed to influence which
  region/time gets picked, in narrow guardrailed cases) is not built yet.

  **Why Stage 2 isn't open yet — this isn't just "not built," it's
  actively blocked by evidence from Stage 1 testing.** Stage 1 was
  deliberately scoped as a low-risk trial specifically to answer the
  question "is this LLM reliable enough to eventually influence real
  decisions?" before writing any override logic. The answer so far is
  no, and it's not a hypothetical concern:

  - Live testing caught the LLM fabricating a drought claim — asserting
    Norway was under "Alert" drought conditions as part of the "Baltic
    Sea regions," when the real EDO bulletin never mentions Norway at
    all (and Norway isn't a Baltic state). This wasn't a rare edge case
    found by adversarial prompting; it showed up during ordinary sample
    testing.
  - The guard written to catch that failure mode needed **two
    iterations** to get right. The first version, checking for
    severity-word-plus-region-name anywhere in the whole response, was
    too broad: it started discarding *correct* responses (e.g. one that
    accurately described France's real Alert status while merely
    *naming* the runner-up region elsewhere in the same sentence). It
    took a second pass — restricting the check to same-clause
    co-occurrence — to catch the real fabrication without punishing
    legitimate answers.
  - Both guards that exist today are still targeted backstops for
    *observed* failure modes, not general hallucination detectors (see
    "Known limitations" below). There's no reason to assume these are
    the only ways this model can fabricate a claim — they're just the
    ones that happened to surface during this project's own testing.

  If a non-authoritative advisory layer — where a wrong answer costs
  nothing but a misleading print statement — took two rounds of live
  failures and fixes to get even this far, that's a direct argument
  against giving the same LLM authority to change an actual scheduling
  decision, where a wrong answer has a real (if small-scale, in this
  project) cost. Stage 2 would need at minimum: a broader-than-two-cases
  track record of Stage 1's flags being accurate across many real runs,
  and/or hard bounds on what override is even allowed to do (e.g. only
  permitted when the chosen-vs-runner-up score gap is small enough that
  being wrong barely matters). Neither exists yet.

## Known limitations (read before citing this anywhere)

- Water factors are technology-median estimates, not per-plant measured data
- Cooling technology (once-through vs. tower vs. dry) isn't modeled — it
  causes bigger variation than fuel type alone
- Hydropower's water factor is especially uncertain/contested — treat with
  extra skepticism
- No embodied water (hardware manufacturing) is included, only operational
  generation water
- `gas`, `oil`, `biomass`, and `geothermal` factors in `water/factors.py` are
  flagged `confidence="low"` — verify against the Macknick et al. 2012
  primary source before relying on them
- All water factors are US-literature averages. They may not transfer to
  other countries' plant fleets. E.g., an earlier draft of this README
  claimed Thai plants mostly use once-through seawater cooling — checked
  against EGAT's own sustainability disclosures and that was wrong: EGAT's
  major thermal/combined-cycle plants draw from freshwater sources (rivers,
  canals, dams — e.g. Bang Pakong plant from the Bang Pakong River, North/
  South Bangkok plants from the Chao Phraya River). Don't apply this table
  to a specific country without checking its actual generation fleet and
  cooling-water sources first — this project got that wrong once already.
- A water scarcity weighting is implemented (`water/scarcity.py`, Thailand
  baseline water-stress score from WRI Aqueduct 4.0, CC BY 4.0), but it is
  informational only and does not affect scheduling decisions. It's a
  single national constant applied equally to every candidate in a job's
  comparison set — and multiplying every candidate by the same constant
  cannot change which one `optimizer.py`'s min-max normalization picks (the
  math cancels out). Surfaced in `evaluate.py`'s `water_scarcity_context`
  field for reporting, not fed back into `schedule_job()`. Making it
  actually influence decisions would require per-region/per-time scarcity
  data, which runs into basin-vs-administrative-boundary granularity
  mismatches not yet resolved — left as future work, not attempted here.
- The optional LLM-generated explanation (`wascheduler/llm/reasoning.py`) is
  an explanation layer only — it cannot influence which region/time gets
  picked, since it runs after `schedule_job()` has already deterministically
  decided that via min-max normalized scoring. It's prompted to use only the
  numbers it's given, but LLM output isn't guaranteed accurate or
  deterministic; treat it as a readability layer, not a source of truth.
  Falls back to the plain f-string automatically on any failure (missing
  key, network error, rate limit, etc).
- `generate_reasoning_llm()` (`wascheduler/llm/reasoning.py`) and
  `advisory_reconsideration()` (`wascheduler/llm/advisory.py`) each make
  one network call per scheduled job whenever `NVIDIA_NIM_API_KEY` is
  set — there's no batching or rate-limit handling, and `demo.py` now
  calls both per decision (2 calls × 3 strategies × 3 jobs = 18 calls per
  run). NVIDIA NIM's free tier caps around 40 requests/minute, so running
  many jobs in quick succession (e.g. `aggregate_evaluate.py`, which
  intentionally skips both LLM layers for exactly this reason via
  `skip_llm_reasoning=True`) could hit 429 errors if it didn't. The
  fallback f-string / `checked=False` result still works fine in that
  case (see each module's `except Exception` block), but it's worth
  knowing before scripting a large batch run against either layer.
- The advisory layer's two fabrication guards (see "Optional: LLM
  advisory second opinion" above) are targeted backstops for the specific
  failure modes observed during this project's own testing (an invented
  job location; an invented drought severity for a region not actually in
  the bulletin) — not general hallucination detectors. An LLM can invent
  ungrounded claims in other phrasings neither guard catches. Passing
  both guards means "this specific known failure mode wasn't detected in
  this response," not "this response is fully grounded."
