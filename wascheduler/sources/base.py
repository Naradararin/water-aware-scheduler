"""Abstract interface all signal sources must implement.

This mirrors the pluggable data-source pattern used by Carbon Aware SDK,
but each SignalReading carries power_mix so a water intensity can always
be derived downstream — the two-signal extension point that the original
SDK's single-signal EmissionsData model doesn't have room for.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import SignalReading


class SignalSource(ABC):
    @abstractmethod
    def get_signal(self, region: str, timestamp: datetime = None) -> SignalReading:
        """Return the latest (or nearest) signal reading for a region."""
        ...

    @abstractmethod
    def get_signals_range(self, region: str, start: datetime, end: datetime) -> list:
        """Return a list of SignalReading covering [start, end]."""
        ...
