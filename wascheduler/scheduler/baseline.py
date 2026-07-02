"""Baseline strategy: run the job immediately in a fixed 'home' region.

This is what most workloads do today with zero optimization — it's the
yardstick every other strategy gets measured against.
"""

from ..models import Job, ScheduleDecision, SignalReading
from ..water.derive import derive_water_intensity_l_per_kwh


def schedule_baseline(job: Job, home_region_signal: SignalReading) -> ScheduleDecision:
    water_l_per_kwh = home_region_signal.water_intensity_l_per_kwh
    if water_l_per_kwh is None:
        water_l_per_kwh = derive_water_intensity_l_per_kwh(home_region_signal.power_mix)

    return ScheduleDecision(
        job_id=job.id,
        chosen_region=home_region_signal.region,
        chosen_time=job.earliest_start,
        predicted_carbon_g=home_region_signal.carbon_intensity_gco2_per_kwh * job.demand_kwh,
        predicted_water_l=water_l_per_kwh * job.demand_kwh,
        strategy="baseline",
        reasoning=f"Ran immediately in default region {home_region_signal.region} — no optimization applied.",
    )
