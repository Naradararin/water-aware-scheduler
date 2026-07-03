"""
End-to-end demo of the two-signal (carbon + water) scheduler.

Auto-selects data source:
  - If ELECTRICITYMAPS_API_KEY is set (via .env), uses REAL live data —
    but only "latest" readings per region (historical range isn't
    implemented for the real source yet, see sources/electricitymaps.py).
  - Otherwise, falls back to MOCK data so this always runs end-to-end
    with zero setup.

Proves the core claim of this project: a carbon-only strategy and a
water-only strategy do NOT always agree on where/when to run a job —
which is exactly why a two-signal scheduler is worth building. See
README "Who this is for" and "Known limitations" before treating any
of this as more than a learning/demo artifact.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from wascheduler.models import Job
from wascheduler.scheduler.optimizer import schedule_job
from wascheduler.scheduler.baseline import schedule_baseline
from wascheduler.evaluate import compare_to_baseline
from wascheduler.water.derive import low_confidence_fraction

load_dotenv()  # reads .env if present

HOME_REGION = "TH"  # default/no-optimization region
CANDIDATE_REGIONS = ["FR", "DE", "NO", "TH"]


def get_source():
    """Auto-select data source: real ElectricityMaps if a key is set, else mock."""
    api_key = os.environ.get("ELECTRICITYMAPS_API_KEY")
    if api_key:
        from wascheduler.sources.electricitymaps import ElectricityMapsSource
        print("[using ElectricityMaps - real live data, 'latest' readings only]")
        return ElectricityMapsSource(api_key=api_key), True
    else:
        from wascheduler.sources.mock import MockSignalSource
        print("[no ELECTRICITYMAPS_API_KEY found - using mock data. "
              "See README 'Switching to real data' to use live data instead.]")
        return MockSignalSource(seed=42), False


def load_jobs(now: datetime) -> list:
    with open("data/sample_jobs.json") as f:
        raw_jobs = json.load(f)
    jobs = []
    for rj in raw_jobs:
        jobs.append(
            Job(
                id=rj["id"],
                demand_kwh=rj["demand_kwh"],
                earliest_start=now + timedelta(hours=rj["earliest_start_offset_hours"]),
                deadline=now + timedelta(hours=rj["deadline_offset_hours"]),
                candidate_regions=rj["candidate_regions"],
            )
        )
    return jobs


def build_signals(source, is_real: bool, now: datetime) -> list:
    """Real source only supports 'latest' (see electricitymaps.py NOTE),
    so in real mode we take one latest reading per region and stamp it
    across the job window so the optimizer still has candidates to
    compare. In mock mode we get genuine hour-by-hour variation."""
    all_signals = []
    for region in CANDIDATE_REGIONS:
        if is_real:
            signal = source.get_signal(region)
            all_signals.append(signal)
        else:
            all_signals.extend(
                source.get_signals_range(region, now, now + timedelta(hours=24))
            )
    return all_signals


def main():
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    source, is_real = get_source()

    all_signals = build_signals(source, is_real, now)
    jobs = load_jobs(now)
    home_signal = source.get_signal(HOME_REGION) if is_real else source.get_signal(HOME_REGION, now)

    if is_real:
        # In real "latest only" mode, jobs must accept the single latest
        # timestamp per region rather than a future window.
        for job in jobs:
            job.earliest_start = min(s.timestamp for s in all_signals)
            job.deadline = max(s.timestamp for s in all_signals) + timedelta(minutes=1)

    print("=" * 78)
    print("WATER-AWARE SCHEDULER - DEMO RUN")
    print("=" * 78)

    strategies = [
        ("carbon_only", 1.0, 0.0),
        ("water_only", 0.0, 1.0),
        ("balanced", 0.5, 0.5),
    ]

    for job in jobs:
        window_hours = (job.deadline - job.earliest_start).total_seconds() / 3600
        print(f"\nJob: {job.id}  (demand={job.demand_kwh} kWh, "
              f"window starts +{(job.earliest_start - now).total_seconds() / 3600:.0f}h, "
              f"deadline in {window_hours:.0f}h)")

        baseline = schedule_baseline(job, home_signal)
        print(f"  baseline     -> region={baseline.chosen_region:4s} "
              f"carbon={baseline.predicted_carbon_g:8.1f} gCO2  "
              f"water={baseline.predicted_water_l:7.2f} L")

        for label, alpha, beta in strategies:
            decision = schedule_job(job, all_signals, alpha=alpha, beta=beta, strategy_label=label)
            comparison = compare_to_baseline(baseline, decision)

            chosen_signal = next(
                s for s in all_signals
                if s.region == decision.chosen_region and s.timestamp == decision.chosen_time
            )
            low_conf = low_confidence_fraction(chosen_signal.power_mix)
            flag = f"  [!] {low_conf:.0%} of mix is low-confidence water data" if low_conf > 0.25 else ""

            print(f"  {label:12s} -> region={decision.chosen_region:4s} "
                  f"carbon={decision.predicted_carbon_g:8.1f} gCO2 ({comparison['carbon_saved_pct']:+5.1f}%)  "
                  f"water={decision.predicted_water_l:7.2f} L ({comparison['water_saved_pct']:+5.1f}%){flag}")
            # ASCII-safe: LLM reasoning text can contain characters the
            # Windows cp1252 console can't encode (em-dashes, curly quotes).
            reasoning_ascii = decision.reasoning.encode("ascii", "replace").decode("ascii")
            print(f"               reasoning: {reasoning_ascii}")

    print("\n" + "=" * 78)
    print("Look at carbon_only vs water_only above - when they pick DIFFERENT")
    print("regions, that's the core insight this project demonstrates:")
    print("carbon-aware scheduling and water-aware scheduling are not the same thing.")
    print("=" * 78)


if __name__ == "__main__":
    main()
