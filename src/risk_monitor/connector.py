from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Coroutine
try:
    import ccxt.pro as ccxt_client
    _HAS_CCXT_PRO = True
except ModuleNotFoundError:
    try:
        import ccxt.async_support as ccxt_client
        _HAS_CCXT_PRO = False
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Missing exchange client dependency. Install with: pip install ccxt"
        ) from exc

from risk_monitor.models import BookState, MarketEvent, TradeState


class BinanceWebSocketManager:
    """
    Async market-data manager for Binance Spot/Futures L2 depth + aggregate trades.
    Uses ccxt.pro streams when available, otherwise falls back to async REST polling.
    """

    def __init__(
        self,
        spot_symbol: str,
        futures_symbol: str,
        depth_levels: int,
        event_sink: Callable[[MarketEvent], Coroutine[None, None, None]],
    ) -> None:
        self.spot_symbol = spot_symbol
        self.futures_symbol = futures_symbol
        self.depth_levels = depth_levels
        self.event_sink = event_sink
        self._stop = asyncio.Event()
        self._spot: Any = None
        self._futures: Any = None
        self._last_trade_ts: dict[str, int] = {}

    async def connect(self) -> None:
        self._spot = ccxt_client.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        self._futures = ccxt_client.binance(
            {"enableRateLimit": True, "options": {"defaultType": "future"}}
        )

    async def close(self) -> None:
        self._stop.set()
        if self._spot:
            await self._spot.close()
        if self._futures:
            await self._futures.close()

    async def run(self) -> None:
        if self._spot is None or self._futures is None:
            await self.connect()

        workers = [
            asyncio.create_task(self._watch_depth(self._spot, self.spot_symbol, "spot")),
            asyncio.create_task(self._watch_trades(self._spot, self.spot_symbol, "spot")),
            asyncio.create_task(self._watch_depth(self._futures, self.futures_symbol, "futures")),
            asyncio.create_task(self._watch_trades(self._futures, self.futures_symbol, "futures")),
        ]

        await asyncio.wait(workers, return_when=asyncio.FIRST_EXCEPTION)
        for task in workers:
            task.cancel()
        await self.close()

    async def _watch_depth(self, exchange: Any, symbol: str, market: str) -> None:
        while not self._stop.is_set():
            try:
                if _HAS_CCXT_PRO:
                    book = await exchange.watch_order_book(symbol, self.depth_levels)
                else:
                    book = await exchange.fetch_order_book(symbol, limit=self.depth_levels)
                bids = [[float(px), float(sz)] for px, sz in book["bids"][: self.depth_levels]]
                asks = [[float(px), float(sz)] for px, sz in book["asks"][: self.depth_levels]]
                event = MarketEvent(
                    event_type="depth",
                    market=market,
                    ts_ms=int(book.get("timestamp") or time.time() * 1000),
                    payload={"book": BookState(bids=bids, asks=asks, ts_ms=int(time.time() * 1000))},
                )
                await self.event_sink(event)
                if not _HAS_CCXT_PRO:
                    await asyncio.sleep(0.2)
            except Exception:
                await asyncio.sleep(0.5)

    async def _watch_trades(self, exchange: Any, symbol: str, market: str) -> None:
        while not self._stop.is_set():
            try:
                if _HAS_CCXT_PRO:
                    trades = await exchange.watch_trades(symbol)
                else:
                    trades = await exchange.fetch_trades(symbol, limit=10)

                trade_key = f"{market}:{symbol}"
                last_ts = self._last_trade_ts.get(trade_key, 0)
                max_ts = last_ts

                for t in trades[-10:]:
                    ts_ms = int(t.get("timestamp") or time.time() * 1000)
                    if not _HAS_CCXT_PRO and ts_ms <= last_ts:
                        continue
                    trade = TradeState(
                        ts_ms=ts_ms,
                        price=float(t["price"]),
                        qty=float(t["amount"]),
                        side=str(t.get("side", "buy")),
                        market=market,
                    )
                    event = MarketEvent(
                        event_type="agg_trade",
                        market=market,
                        ts_ms=trade.ts_ms,
                        payload={"trade": trade},
                    )
                    await self.event_sink(event)
                    max_ts = max(max_ts, ts_ms)

                self._last_trade_ts[trade_key] = max_ts
                if not _HAS_CCXT_PRO:
                    await asyncio.sleep(0.2)
            except Exception:
                await asyncio.sleep(0.5)
