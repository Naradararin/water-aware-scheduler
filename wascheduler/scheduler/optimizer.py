"""
Two-signal co-optimizing scheduler — the core contribution of this project.

Improvement over the V0 spec's pseudo-code: instead of an arbitrary
WEIGHT_SCALE constant to make gCO2 and liters comparable, this uses
min-max normalization ACROSS THE CANDIDATE SET at decision time. Both
signals get rescaled to [0, 1] relative to the options actually available
for this job, then combined with alpha/beta. This is more defensible
than a fixed magic-number scale because "what counts as a big water
number" genuinely depends on which regions/times are on the table for
a given job.
"""

from ..llm.reasoning import generate_reasoning_llm
from ..models import Job, ScheduleDecision, SignalReading
from ..water.derive import derive_water_intensity_l_per_kwh


def _ensure_water(signal: SignalReading) -> float:
    if signal.water_intensity_l_per_kwh is None:
        signal.water_intensity_l_per_kwh = derive_water_intensity_l_per_kwh(signal.power_mix)
    return signal.water_intensity_l_per_kwh


def _normalize(value: float, vmin: float, vmax: float) -> float:
    if vmax - vmin < 1e-9:
        return 0.0
    return (value - vmin) / (vmax - vmin)


def schedule_job(
    job: Job,
    signals: list,
    alpha: float = 0.5,
    beta: float = 0.5,
    strategy_label: str = "balanced",
    skip_llm_reasoning: bool = False,
) -> ScheduleDecision:
    """
    alpha: weight given to carbon (0-1)
    beta:  weight given to water (0-1)
    (alpha + beta need not be exactly 1.0, but keeping them normalized
    makes the resulting score easier to interpret)

    skip_llm_reasoning: if True, never call generate_reasoning_llm() and
        use the plain f-string explanation instead, even if
        NVIDIA_NIM_API_KEY is set. Intended for batch/aggregate runs
        (many schedule_job() calls in a loop) where making one network
        call per job would be slow and could hit NIM's free-tier rate
        limit (~40 req/min) for no real benefit — the LLM explanation is
        for human-readable single-decision output, not something an
        aggregate-stats run reads.
    """
    candidates = [
        s
        for s in signals
        if s.region in job.candidate_regions
        and job.earliest_start <= s.timestamp <= job.deadline
    ]
    if not candidates:
        raise ValueError(
            f"No candidate signals for job {job.id} within its region/time window."
        )

    for s in candidates:
        _ensure_water(s)

    carbon_vals = [s.carbon_intensity_gco2_per_kwh for s in candidates]
    water_vals = [s.water_intensity_l_per_kwh for s in candidates]
    c_min, c_max = min(carbon_vals), max(carbon_vals)
    w_min, w_max = min(water_vals), max(water_vals)

    def score(s: SignalReading) -> float:
        c_score = _normalize(s.carbon_intensity_gco2_per_kwh, c_min, c_max)
        w_score = _normalize(s.water_intensity_l_per_kwh, w_min, w_max)
        return alpha * c_score + beta * w_score

    best = min(candidates, key=score)

    fallback_reasoning = (
        f"Chose {best.region} at {best.timestamp} "
        f"(alpha={alpha}, beta={beta}). Candidates ranged "
        f"{c_min:.0f}-{c_max:.0f} gCO2/kWh and {w_min:.2f}-{w_max:.2f} L/kWh."
    )
    if skip_llm_reasoning:
        reasoning = fallback_reasoning
    else:
        reasoning = generate_reasoning_llm(
            job=job,
            best=best,
            alpha=alpha,
            beta=beta,
            c_min=c_min,
            c_max=c_max,
            w_min=w_min,
            w_max=w_max,
            fallback_reasoning=fallback_reasoning,
        )

    return ScheduleDecision(
        job_id=job.id,
        chosen_region=best.region,
        chosen_time=best.timestamp,
        predicted_carbon_g=best.carbon_intensity_gco2_per_kwh * job.demand_kwh,
        predicted_water_l=best.water_intensity_l_per_kwh * job.demand_kwh,
        strategy=strategy_label,
        reasoning=reasoning,
    )
