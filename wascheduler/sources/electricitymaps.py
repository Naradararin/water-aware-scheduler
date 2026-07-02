"""
Real data source backed by the ElectricityMaps API (free tier).

Free tier is NON-COMMERCIAL use only — fine for this learning/portfolio
project, but re-check terms before any commercial use.

Get a free key: https://www.electricitymaps.com/free-tier-api
Docs (verified against live docs during this project's research pass):
https://static.electricitymaps.com/api/docs/index.html

Endpoints used:
  GET https://api.electricitymap.org/v3/carbon-intensity/latest?zone=<ZONE>
  GET https://api.electricitymap.org/v3/power-breakdown/latest?zone=<ZONE>
Both require header: auth-token: <your key>
"""

import os
from datetime import datetime
from typing import Optional

import requests

from ..models import SignalReading
from .base import SignalSource

API_BASE = "https://api.electricitymap.org/v3"


class ElectricityMapsSource(SignalSource):
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ELECTRICITYMAPS_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ELECTRICITYMAPS_API_KEY not set. Get a free key at "
                "https://www.electricitymaps.com/free-tier-api and put it "
                "in a .env file (see .env.example)."
            )
        self.session = requests.Session()
        self.session.headers.update({"auth-token": self.api_key})

    def get_signal(self, region: str, timestamp: datetime = None) -> SignalReading:
        # `timestamp` is ignored here — this always fetches the latest reading.
        # Use get_signals_range() for a spread of hours (see NOTE below).
        carbon_resp = self.session.get(
            f"{API_BASE}/carbon-intensity/latest", params={"zone": region}
        )
        carbon_resp.raise_for_status()
        carbon_data = carbon_resp.json()

        mix_resp = self.session.get(
            f"{API_BASE}/power-breakdown/latest", params={"zone": region}
        )
        mix_resp.raise_for_status()
        mix_data = mix_resp.json()

        power_mix = self._normalize_power_breakdown(
            mix_data.get("powerProductionBreakdown", {})
        )

        return SignalReading(
            region=region,
            timestamp=datetime.fromisoformat(
                carbon_data["datetime"].replace("Z", "+00:00")
            ),
            carbon_intensity_gco2_per_kwh=carbon_data["carbonIntensity"],
            power_mix=power_mix,
        )

    def _normalize_power_breakdown(self, raw: dict) -> dict:
        """API returns absolute MW per source; convert to fractions."""
        clean = {k: v for k, v in raw.items() if v is not None and v > 0}
        total = sum(clean.values())
        if total == 0:
            return {}
        return {k: v / total for k, v in clean.items()}

    def get_signals_range(self, region: str, start: datetime, end: datetime) -> list:
        # NOTE: free tier historical access is limited (check your plan's
        # `access` list from the /v3/zones response). This V0 stub only
        # supports "latest" — implement `/carbon-intensity/past-range` and
        # `/power-breakdown/past` once you've confirmed your plan covers them.
        raise NotImplementedError(
            "Historical range fetch not implemented in V0 — use get_signal() "
            "for latest-only, or extend this once your plan's access is confirmed."
        )
