"""
water/scarcity.py

Water-scarcity weighting layer for the water-aware compute scheduler.

Scope decision (2026-07-02): Thailand-only. Cross-country comparison was
intentionally cut for this module -- see project handoff notes. If
cross-country scarcity weighting is needed later, switch from a single
hardcoded score to a lookup table keyed by ElectricityMaps zone -> gid_0,
sourced from the same dataset (country_baseline sheet, filtered per zone).

Data source (verified primary source, not inferred):
    World Resources Institute, Aqueduct 4.0 Country Rankings.
    Kuzma, S., M.F.P. Bierkens, S. Lakshman, T. Luo, L. Saccoccia,
    E. H. Sutanudjaja, and R. Van Beek. 2023. "Aqueduct 4.0: Updated
    decision-relevant global water risk indicators." Technical Note.
    Washington, DC: World Resources Institute.
    doi.org/10.46830/writn.23.00061
    Download: https://www.wri.org/data/aqueduct-40-country-rankings
    License: CC BY 4.0 (attribution required)

Indicator used: bws (baseline water stress), country-level aggregation,
weight scheme = "Tot" (total gross water withdrawal -- domestic +
industrial + irrigation + livestock combined). This is WRI's own
demand-weighted aggregation from sub-basin to country level; no custom
aggregation logic was built for this, since WRI already publishes it.

Sensitivity check across weight schemes for Thailand (all from the same
downloaded file, country_baseline sheet, gid_0 == 'THA', indicator_name
== 'bws'), confirming the Tot-weighted score is not an outlier:
    Irr (irrigation)  3.641575331   cat 3  High (40-80%)
    Tot (total)        3.623007642  cat 3  High (40-80%)   <- used below
    Ind (industrial)   3.411990021  cat 3  High (40-80%)
    Liv (livestock)    3.277960321  cat 3  High (40-80%)
    Dom (domestic)     3.216910911  cat 3  High (40-80%)
    One (unweighted)   2.880291007  cat 2  Medium-High (20-40%)

All weighted schemes land in the same "High" category; only the
unweighted score drops a category. Tot is the most defensible default
since it reflects actual water demand rather than treating every basin
equally regardless of how much water is drawn there.
"""

# bws score for Thailand, weight="Tot", from country_baseline sheet of
# the Aqueduct 4.0 Country Rankings download (file: 
# Aqueduct40_rankings_download_Y2023M07D05.xlsx). Score scale is 0-5.
THAILAND_BASELINE_WATER_STRESS_SCORE = 3.623007642
THAILAND_BASELINE_WATER_STRESS_LABEL = "High (40-80%)"
THAILAND_BASELINE_WATER_STRESS_RANK = 39  # out of ~180 countries, 1 = most stressed

# WRI's bws score scale is 0-5 (not 0-1). Keep this explicit rather than
# assuming -- an unlabeled "0-5" constant silently used as if it were a
# fraction is exactly the kind of mistake this project has flagged
# before as a category of risk to watch for.
BWS_SCORE_MAX = 5.0


def normalize_scarcity(score: float, max_score: float = BWS_SCORE_MAX) -> float:
    """
    Normalize a WRI Aqueduct bws-style score (0-5) to a 0-1 fraction.

    Raises ValueError if score is outside [0, max_score] -- fail loudly
    rather than silently producing a nonsensical weight.
    """
    if not (0.0 <= score <= max_score):
        raise ValueError(
            f"scarcity score {score} outside expected range [0, {max_score}]"
        )
    return score / max_score


def apply_scarcity_weight(
    water_intensity: float,
    scarcity_score: float = THAILAND_BASELINE_WATER_STRESS_SCORE,
    max_score: float = BWS_SCORE_MAX,
) -> float:
    """
    Apply a water-scarcity weighting on top of a water_intensity value.

    water_intensity: output of water/derive.py (L per kWh, from the
        power-mix -> Macknick et al. 2012 factor derivation).
    scarcity_score: WRI Aqueduct bws score, 0-5 scale. Defaults to the
        Thailand Tot-weighted score above.

    Formula: weighted = water_intensity * (1 + normalized_scarcity)
        A region with scarcity_score = 0 (no stress) leaves water_intensity
        unchanged (multiplier = 1.0). Thailand's score of 3.62 gives a
        multiplier of ~1.72 -- i.e. water used in a "High" stress region
        is weighted as if it were ~72% more consequential than the same
        volume used in a zero-stress region.

    This is a scope-narrowing choice, not a claim of physical equivalence
    between liters and stress -- it's a relative weighting for the
    optimizer's min-max normalization step, same spirit as the existing
    carbon/water co-optimization design.
    """
    normalized = normalize_scarcity(scarcity_score, max_score)
    return water_intensity * (1 + normalized)


if __name__ == "__main__":
    # Quick manual check -- ASCII-safe output only (Windows cp1252 console).
    example_intensity = 1.8  # placeholder L/kWh, replace with real derive.py output
    weighted = apply_scarcity_weight(example_intensity)
    print(f"water_intensity={example_intensity}  ->  weighted={weighted:.4f}")
    print(f"Thailand bws score: {THAILAND_BASELINE_WATER_STRESS_SCORE} "
          f"({THAILAND_BASELINE_WATER_STRESS_LABEL}, rank {THAILAND_BASELINE_WATER_STRESS_RANK})")
