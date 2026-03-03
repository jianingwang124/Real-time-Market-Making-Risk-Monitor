from __future__ import annotations

import threading
from collections import deque
from copy import deepcopy

from risk_monitor.models import BookState, TradeState


class SharedBuffer:
    """Thread-safe shared state for async producer + dashboard consumer."""

    def __init__(self, max_trades: int = 5000) -> None:
        self._lock = threading.RLock()
        self.books: dict[str, BookState] = {}
        self.prev_books: dict[str, BookState] = {}
        self.trades: deque[TradeState] = deque(maxlen=max_trades)
        self.metrics: dict[str, float] = {}
        self.greeks: dict[str, float] = {"delta": 0.0, "gamma": 0.0, "vega": 0.0}
        self.positions: dict[str, float] = {"spot_btc": 0.0, "futures_btc": 0.0}
        self.risk_flags: dict[str, bool] = {}

    def update_book(self, market: str, book: BookState) -> None:
        with self._lock:
            if market in self.books:
                self.prev_books[market] = deepcopy(self.books[market])
            self.books[market] = deepcopy(book)

    def append_trade(self, trade: TradeState) -> None:
        with self._lock:
            self.trades.append(trade)

    def update_metrics(
        self,
        metrics: dict[str, float],
        greeks: dict[str, float],
        risk_flags: dict[str, bool],
    ) -> None:
        with self._lock:
            self.metrics.update(metrics)
            self.greeks = deepcopy(greeks)
            self.risk_flags = deepcopy(risk_flags)

    def update_positions(self, spot_btc: float, futures_btc: float) -> None:
        with self._lock:
            self.positions["spot_btc"] = float(spot_btc)
            self.positions["futures_btc"] = float(futures_btc)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "books": deepcopy(self.books),
                "prev_books": deepcopy(self.prev_books),
                "trades": list(self.trades),
                "metrics": deepcopy(self.metrics),
                "greeks": deepcopy(self.greeks),
                "positions": deepcopy(self.positions),
                "risk_flags": deepcopy(self.risk_flags),
            }

