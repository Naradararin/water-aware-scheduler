"""
Water consumption factors by electricity generation source.

PRIMARY SOURCE:
Macknick, J., Newmark, R., Heath, G., & Hallett, K.C. (2012).
"Operational water consumption and withdrawal factors for electricity
generating technologies: A review of existing literature."
Environmental Research Letters, 7(4), 045802.

These are MEDIAN operational water CONSUMPTION factors (water that does
not return to its source), converted from gal/MWh to L/MWh (1 gal = 3.78541 L).

*** IMPORTANT CAVEATS — read before relying on these numbers for anything
    beyond a prototype/learning project ***

1. Water use varies enormously by COOLING TECHNOLOGY (once-through vs.
   cooling tower vs. dry cooling) — far more than by fuel type alone.
   These values assume a generic/common cooling configuration and are
   order-of-magnitude estimates, not measured plant-level data.
2. Entries marked confidence="low" are approximations that were NOT
   directly confirmed against the primary source table during this
   project's research pass — verify against the paper's Table 1/2/3
   before using in any published claim.
3. Hydropower is especially contested: reservoir evaporation estimates
   vary by orders of magnitude and there's active methodological debate
   about whether/how to attribute it to electricity generation.
"""

# L/MWh — divide by 1000 to get L/kWh
WATER_FACTORS_L_PER_MWH = {
    "wind": 0.0,
    "solar": 3.8,            # utility-scale PV, ~1 gal/MWh median (Macknick 2012, Table 1)
    "nuclear": 2544.0,       # cooling tower, ~672 gal/MWh median (Macknick 2012, Table 2)
    "coal": 2044.0,          # steam/tower, ~540 gal/MWh (secondary source, cross-check vs. Table 2)
    "csp": 3430.0,           # concentrating solar, tower cooling, ~906 gal/MWh median (Table 1)
    "hydro": 2500.0,         # HIGH UNCERTAINTY — see caveat #3 above
    "geothermal": 1500.0,    # approximate — verify against primary source
    "gas": 750.0,            # combined cycle — approximate placeholder, verify against Table 2
    "oil": 2000.0,           # approximate — assumed similar to coal steam plants
    "biomass": 2000.0,       # approximate — assumed similar steam-cycle profile
    "unknown": 1500.0,       # fallback for unclassified generation
    "unknown_default": 1500.0,  # fallback for power_mix keys not in this table at all
    "hydro discharge": 0.0,  # storage flow, not primary generation — treat as neutral
    "battery discharge": 0.0,  # storage flow, not primary generation — treat as neutral
}

CONFIDENCE = {
    "wind": "high",
    "solar": "high",
    "nuclear": "medium",
    "coal": "medium",
    "csp": "medium",
    "hydro": "low",
    "geothermal": "low",
    "gas": "low",
    "oil": "low",
    "biomass": "low",
    "unknown": "low",
    "unknown_default": "low",
    "hydro discharge": "high",
    "battery discharge": "high",
}
