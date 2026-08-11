from dataclasses import dataclass
from typing import Optional


@dataclass
class Listing:
    id: str
    titel: str
    preis: float
    ort: str
    zimmer: Optional[float]
    url: str
    quelle: str
