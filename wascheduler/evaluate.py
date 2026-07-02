"""Compare a scheduling decision against the baseline and report % saved."""

from .models import ScheduleDecision


def compare_to_baseline(baseline: ScheduleDecision, optimized: ScheduleDecision) -> dict:
    def pct_saved(base_val, opt_val):
        if base_val <= 0:
            return 0.0
        return round((base_val - opt_val) / base_val * 100, 1)

    return {
        "job_id": optimized.job_id,
        "strategy": optimized.strategy,
        "baseline_region": baseline.chosen_region,
        "optimized_region": optimized.chosen_region,
        "carbon_saved_pct": pct_saved(baseline.predicted_carbon_g, optimized.predicted_carbon_g),
        "water_saved_pct": pct_saved(baseline.predicted_water_l, optimized.predicted_water_l),
        "baseline_carbon_g": round(baseline.predicted_carbon_g, 1),
        "optimized_carbon_g": round(optimized.predicted_carbon_g, 1),
        "baseline_water_l": round(baseline.predicted_water_l, 2),
        "optimized_water_l": round(optimized.predicted_water_l, 2),
    }
