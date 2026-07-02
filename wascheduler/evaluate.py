"""Compare a scheduling decision against the baseline and report % saved."""

from .models import ScheduleDecision
from .water.scarcity import (
    normalize_scarcity,
    THAILAND_BASELINE_WATER_STRESS_SCORE,
    THAILAND_BASELINE_WATER_STRESS_LABEL,
)


def compare_to_baseline(baseline: ScheduleDecision, optimized: ScheduleDecision) -> dict:
    def pct_saved(base_val, opt_val):
        if base_val <= 0:
            return 0.0
        return round((base_val - opt_val) / base_val * 100, 1)

    result = {
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

    # --- Water scarcity context (informational only) ---
    # This block does NOT feed back into scheduling decisions. The bws
    # score is a single constant for Thailand (see water/scarcity.py),
    # and multiplying every candidate's water number by the same constant
    # cannot change which candidate the optimizer's min-max normalization
    # picks (see optimizer.py:schedule_job). It's included here purely to
    # give the raw liter numbers above some real-world context: what they
    # mean in a country WRI rates as "High" baseline water stress.
    scarcity_multiplier = 1 + normalize_scarcity(THAILAND_BASELINE_WATER_STRESS_SCORE)
    result["water_scarcity_context"] = {
        "note": (
            "Informational only -- does not affect the scheduling decision. "
            "See water/scarcity.py for why a constant national score cannot "
            "influence min-max normalized optimization."
        ),
        "region": "Thailand",
        "bws_score": THAILAND_BASELINE_WATER_STRESS_SCORE,
        "bws_label": THAILAND_BASELINE_WATER_STRESS_LABEL,
        "scarcity_multiplier": round(scarcity_multiplier, 3),
        "baseline_water_l_scarcity_weighted": round(
            baseline.predicted_water_l * scarcity_multiplier, 2
        ),
        "optimized_water_l_scarcity_weighted": round(
            optimized.predicted_water_l * scarcity_multiplier, 2
        ),
    }

    return result
