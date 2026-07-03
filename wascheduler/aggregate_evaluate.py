"""
Aggregate evaluation: run many synthetic jobs through the scheduler and
report average carbon/water savings vs. baseline.

IMPORTANT — read before citing these numbers anywhere:
This is NOT a benchmark against WaterWise's published ~21.91% carbon /
~14.78% water savings (Jiang et al. 2025, arxiv.org/abs/2501.17944).
WaterWise's numbers come from real production traces (Google Borg,
Alibaba) and PARSEC benchmark workloads, evaluated with an MILP-based
scheduler. This project uses synthetic jobs over illustrative mock
region profiles (see sources/mock.py) — different data, different
scale, different scheduling algorithm (min-max normalized greedy choice,
not MILP). The numbers below tell you whether THIS scheduler's own
co-optimization consistently beats ITS OWN baseline, and by roughly what
margin, on its own synthetic test set. Whether that's directionally
consistent with WaterWise (co-optimizing carbon+water beats a
carbon/water-unaware baseline) is worth noting; treating the two
percentages as numerically comparable is not — don't do that in any
write-up of this project.
"""

import statistics
from datetime import datetime, timedelta
import random as _random_module

from .evaluate import compare_to_baseline
from .models import Job
from .scheduler.baseline import schedule_baseline
from .scheduler.optimizer import schedule_job
from .sources.mock import MockSignalSource, MOCK_REGION_PROFILES


def generate_synthetic_jobs(
    n_jobs: int = 50,
    seed: int = 42,
    base_time: datetime = None,
    rand: _random_module.Random = None,
) -> list:
    """
    Generate n_jobs synthetic deferrable jobs spread over time, each able
    to run in any of the mock region profiles. Deterministic given the
    same seed (separate Random instance from MockSignalSource's own seed
    -- kept independent so job generation and signal generation can be
    reasoned about separately).

    rand: pass an existing seeded Random instance to keep drawing from
        the same stream (e.g. so the caller can also draw an unbiased
        home_region per job afterwards). Defaults to a fresh
        Random(seed) if not given.
    """
    rand = rand or _random_module.Random(seed)
    base_time = base_time or datetime(2026, 7, 1, 0, 0, 0)
    regions = list(MOCK_REGION_PROFILES.keys())

    jobs = []
    for i in range(n_jobs):
        demand_kwh = rand.uniform(10.0, 500.0)
        earliest_start = base_time + timedelta(hours=i * 2)
        deferral_hours = rand.uniform(6.0, 48.0)
        deadline = earliest_start + timedelta(hours=deferral_hours)
        jobs.append(
            Job(
                id=f"synthetic-job-{i:03d}",
                demand_kwh=round(demand_kwh, 1),
                earliest_start=earliest_start,
                deadline=deadline,
                candidate_regions=list(regions),  # can run in any mock region
            )
        )
    return jobs


def run_aggregate_evaluation(
    n_jobs: int = 50,
    seed: int = 42,
    alpha: float = 0.5,
    beta: float = 0.5,
    strategy_label: str = "balanced",
) -> dict:
    """
    Runs n_jobs synthetic jobs through baseline + optimizer and compares
    each pair. Returns two kinds of stats for carbon_saved_pct and
    water_saved_pct:

    - "*_aggregate": the PRIMARY number. Computed as a ratio of totals --
      (sum(baseline) - sum(optimized)) / sum(baseline) * 100 -- across all
      n_jobs. This is the headline figure: it weights every job by its
      actual carbon/water footprint, so a handful of tiny-baseline jobs
      can't dominate the result.
    - "*_per_job": mean/median/min/max/stdev of each job's own saved_pct.
      Kept as a SECONDARY, diagnostic stat -- it's sensitive to outliers
      from jobs with a small baseline denominator (e.g. a low-demand job
      with a tiny baseline_carbon_g can swing to +/-1000%+ even when its
      absolute impact on the total is negligible). Useful for spotting
      per-job variance, not for headline reporting.

    skip_llm_reasoning is always True here -- see optimizer.py docstring.
    Aggregate stats don't read individual reasoning strings, and calling
    an LLM once per job would be slow and could hit NIM's free-tier rate
    limit for no benefit to this function's output.
    """
    source = MockSignalSource(seed=seed)
    rand = _random_module.Random(seed)
    jobs = generate_synthetic_jobs(n_jobs=n_jobs, seed=seed, rand=rand)

    carbon_saved = []
    water_saved = []
    per_job_results = []

    for job in jobs:
        # Pulls from the same seeded Random used for job generation, so the
        # baseline's "home region" is deterministic but not biased toward
        # whichever region happens to be first in MOCK_REGION_PROFILES
        # (that region -- FR -- has a low-carbon/high-water profile, which
        # was silently favoring the baseline's carbon numbers).
        home_region = rand.choice(job.candidate_regions)
        baseline_signal = source.get_signal(home_region, job.earliest_start)
        baseline_decision = schedule_baseline(job, baseline_signal)

        signals = []
        for region in job.candidate_regions:
            signals.extend(
                source.get_signals_range(region, job.earliest_start, job.deadline)
            )

        optimized_decision = schedule_job(
            job,
            signals,
            alpha=alpha,
            beta=beta,
            strategy_label=strategy_label,
            skip_llm_reasoning=True,
        )

        comparison = compare_to_baseline(baseline_decision, optimized_decision)
        carbon_saved.append(comparison["carbon_saved_pct"])
        water_saved.append(comparison["water_saved_pct"])
        per_job_results.append(comparison)

    def _stats(values: list) -> dict:
        return {
            "mean": round(statistics.mean(values), 2),
            "median": round(statistics.median(values), 2),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0,
        }

    def _aggregate_saved_pct(baseline_key: str, optimized_key: str) -> float:
        baseline_total = sum(r[baseline_key] for r in per_job_results)
        optimized_total = sum(r[optimized_key] for r in per_job_results)
        if baseline_total <= 0:
            return 0.0
        return round((baseline_total - optimized_total) / baseline_total * 100, 2)

    return {
        "n_jobs": n_jobs,
        "seed": seed,
        "alpha": alpha,
        "beta": beta,
        "strategy_label": strategy_label,
        "carbon_saved_pct_aggregate": _aggregate_saved_pct("baseline_carbon_g", "optimized_carbon_g"),
        "water_saved_pct_aggregate": _aggregate_saved_pct("baseline_water_l", "optimized_water_l"),
        "carbon_saved_pct_per_job": _stats(carbon_saved),
        "water_saved_pct_per_job": _stats(water_saved),
        "waterwise_reference_note": (
            "WaterWise (Jiang et al. 2025) reports >=21.91% carbon and "
            ">=14.78% water savings vs. an unaware baseline, on real "
            "production traces (Google Borg, Alibaba) with an MILP "
            "scheduler. The numbers above are from this project's own "
            "synthetic mock-data test set with a min-max-normalized "
            "greedy scheduler -- not directly comparable. See this "
            "module's docstring."
        ),
        "per_job_results": per_job_results,
    }


if __name__ == "__main__":
    # ASCII-safe output only (Windows cp1252 console).
    result = run_aggregate_evaluation()
    print(f"Aggregate evaluation over {result['n_jobs']} synthetic jobs "
          f"(seed={result['seed']}, alpha={result['alpha']}, beta={result['beta']})")
    print()
    print("Carbon saved vs baseline, aggregate-totals ratio (%): "
          f"{result['carbon_saved_pct_aggregate']}")
    print("Water saved vs baseline, aggregate-totals ratio (%): "
          f"{result['water_saved_pct_aggregate']}")
    print()
    print("Per-job spread (sensitive to small-baseline outliers -- diagnostic only):")
    print("  Carbon saved vs baseline (%):")
    for k, v in result["carbon_saved_pct_per_job"].items():
        print(f"    {k}: {v}")
    print("  Water saved vs baseline (%):")
    for k, v in result["water_saved_pct_per_job"].items():
        print(f"    {k}: {v}")
    print()
    print("[!] " + result["waterwise_reference_note"])
