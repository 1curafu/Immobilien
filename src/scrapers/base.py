from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchConfig:
    stadt: str
    radius_km: float
    preis_max: float
    zimmer_min: Optional[float]
    rate_limit_sekunden: float = 2.0


class ScraperError(Exception):
    """Raised by a scraper when it fails; caught per-scraper in main.py so one
    broken portal never stops the others."""
