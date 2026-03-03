from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketEvent:
    event_type: str
    market: str
    ts_ms: int
    payload: dict[str, Any]


@dataclass
class BookState:
    bids: list[list[float]] = field(default_factory=list)
    asks: list[list[float]] = field(default_factory=list)
    ts_ms: int = 0


@dataclass
class TradeState:
    ts_ms: int
    price: float
    qty: float
    side: str
    market: str

