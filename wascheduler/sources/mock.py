"""
Mock signal source so the scheduler can be built and tested end-to-end
BEFORE you have an ElectricityMaps API key.

The region profiles below are illustrative approximations of real grid
character (e.g. France is nuclear-heavy, Norway is hydro-heavy) — they
are NOT live data and should never be treated as such. Swap to
ElectricityMapsSource once you have a key.
"""

import random
from datetime import datetime, timedelta

from ..models import SignalReading
from .base import SignalSource

# Illustrative (not live) power-mix snapshots, roughly shaped after each
# grid's known character, for demo purposes only.
MOCK_REGION_PROFILES = {
    "FR": {"nuclear": 0.65, "hydro": 0.10, "wind": 0.10, "gas": 0.15},   # nuclear-heavy
    "DE": {"wind": 0.30, "coal": 0.35, "gas": 0.20, "solar": 0.15},      # mixed/coal-leaning
    "NO": {"hydro": 0.90, "wind": 0.10},                                 # hydro-heavy
    "TH": {"gas": 0.55, "coal": 0.15, "hydro": 0.05, "solar": 0.10, "biomass": 0.15},  # Thailand-ish mix
}

# Rough illustrative gCO2/kWh emission factor per source — NOT authoritative,
# only used to make the mock carbon numbers internally consistent.
_MOCK_CARBON_FACTORS = {
    "nuclear": 12, "wind": 11, "solar": 45, "hydro": 24,
    "gas": 490, "coal": 820, "biomass": 230,
}


class MockSignalSource(SignalSource):
    def __init__(self, seed: int = 42):
        self._rand = random.Random(seed)

    def _carbon_from_mix(self, mix: dict) -> float:
        return sum(
            mix.get(s, 0) * _MOCK_CARBON_FACTORS.get(s, 500) for s in mix
        )

    def get_signal(self, region: str, timestamp: datetime = None) -> SignalReading:
        timestamp = timestamp or datetime.utcnow()
        base_mix = MOCK_REGION_PROFILES.get(region, MOCK_REGION_PROFILES["TH"])

        # small deterministic-ish jitter so different hours aren't identical
        mix = {
            k: max(0.0, v + self._rand.uniform(-0.03, 0.03))
            for k, v in base_mix.items()
        }
        total = sum(mix.values()) or 1.0
        mix = {k: v / total for k, v in mix.items()}

        return SignalReading(
            region=region,
            timestamp=timestamp,
            carbon_intensity_gco2_per_kwh=self._carbon_from_mix(mix),
            power_mix=mix,
        )

    def get_signals_range(self, region: str, start: datetime, end: datetime) -> list:
        signals = []
        t = start
        while t <= end:
            signals.append(self.get_signal(region, t))
            t += timedelta(hours=1)
        return signals
