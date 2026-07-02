"""Core data models for the water-aware compute scheduler."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Region:
    code: str  # e.g. "FR", "DE", "NO", "TH"
    display_name: str
    timezone: str = "UTC"


@dataclass
class SignalReading:
    """A single (region, timestamp) snapshot of grid conditions."""

    region: str
    timestamp: datetime
    carbon_intensity_gco2_per_kwh: float
    power_mix: dict  # {"nuclear": 0.3, "wind": 0.2, ...} fractions, should sum to ~1.0
    water_intensity_l_per_kwh: Optional[float] = None  # filled in by water/derive.py


@dataclass
class Job:
    """A deferrable compute workload."""

    id: str
    demand_kwh: float
    earliest_start: datetime
    deadline: datetime
    candidate_regions: list = field(default_factory=list)


@dataclass
class ScheduleDecision:
    job_id: str
    chosen_region: str
    chosen_time: datetime
    predicted_carbon_g: float
    predicted_water_l: float
    strategy: str = ""  # e.g. "carbon_only", "water_only", "balanced", "baseline"
    reasoning: str = ""  # used in V2 (agent explanation)
