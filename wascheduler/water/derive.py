"""Derive water intensity (L/kWh) from an electricity power mix.

This is the core trick that makes this project buildable without a
dedicated real-time water API (which barely exists): take the power-mix
breakdown that carbon APIs already provide for free, and multiply by
known water-per-source factors.
"""

from .factors import WATER_FACTORS_L_PER_MWH, CONFIDENCE


def low_confidence_fraction(power_mix: dict) -> float:
    """
    Fraction (0-1) of a power mix coming from sources whose water factor
    is flagged confidence='low' in factors.py. Use this to warn when a
    scheduling decision leans heavily on uncertain water numbers.
    """
    if not power_mix:
        return 1.0  # unknown mix = treat as fully unreliable
    total = 0.0
    for source, fraction in power_mix.items():
        if fraction is None or fraction <= 0:
            continue
        if CONFIDENCE.get(source.lower(), "low") == "low":
            total += fraction
    return total


def derive_water_intensity_l_per_kwh(power_mix: dict) -> float:
    """
    power_mix: {"nuclear": 0.3, "wind": 0.2, "gas": 0.5, ...}
        Fractions of total generation by source. Does not need to sum
        to exactly 1.0 (small gaps/unknowns are tolerated).

    Returns: estimated water intensity in liters per kWh for that mix.
    """
    if not power_mix:
        return WATER_FACTORS_L_PER_MWH["unknown_default"] / 1000.0

    total_l_per_mwh = 0.0
    for source, fraction in power_mix.items():
        if fraction is None or fraction <= 0:
            continue
        factor = WATER_FACTORS_L_PER_MWH.get(
            source.lower(), WATER_FACTORS_L_PER_MWH["unknown_default"]
        )
        total_l_per_mwh += fraction * factor

    return total_l_per_mwh / 1000.0  # MWh -> kWh
