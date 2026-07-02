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
(weighting a liter of water by how scarce it is in that specific region),
which this V0 does not. If you want the real research-grade version, go
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
└── evaluate.py              # % carbon/water saved vs. baseline
```

## Roadmap

- **V0 (this)** — mock + real data sources, co-optimizer, baseline comparison
- **V1** — richer evaluation (aggregate stats across many jobs, benchmark
  against published figures like WaterWise's ~21% carbon / ~14% water savings
  to sanity-check the model)
- **V2** — LLM agent layer that reasons over the carbon/water trade-off and
  explains its scheduling decisions in natural language

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
  other countries' plant fleets — e.g. many Thai power plants use
  once-through seawater cooling, which barely touches freshwater at all,
  unlike the freshwater-cooling-tower assumptions baked into most of this
  table. Don't apply this table to a specific country without checking its
  actual generation fleet first.
- This project does not implement a water *scarcity* weighting (a liter in
  a drought region ≠ a liter in a water-abundant one) — WaterWise does; see
  the "Why this exists" section above.
