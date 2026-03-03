from __future__ import annotations

import asyncio
import time
from typing import Callable, Coroutine

import ccxt.pro as ccxtpro

from risk_monitor.models import BookState, MarketEvent, TradeState


class BinanceWebSocketManager:
    """
    Async WS manager for Binance Spot/Futures L2 depth + aggregate trades.
    Uses ccxt.pro unified streams.
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
        self._spot = None
        self._futures = None

    async def connect(self) -> None:
        self._spot = ccxtpro.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})
        self._futures = ccxtpro.binance(
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

    async def _watch_depth(self, exchange: ccxtpro.Exchange, symbol: str, market: str) -> None:
        while not self._stop.is_set():
            try:
                book = await exchange.watch_order_book(symbol, self.depth_levels)
                bids = [[float(px), float(sz)] for px, sz in book["bids"][: self.depth_levels]]
                asks = [[float(px), float(sz)] for px, sz in book["asks"][: self.depth_levels]]
                event = MarketEvent(
                    event_type="depth",
                    market=market,
                    ts_ms=int(book.get("timestamp") or time.time() * 1000),
                    payload={"book": BookState(bids=bids, asks=asks, ts_ms=int(time.time() * 1000))},
                )
                await self.event_sink(event)
            except Exception:
                await asyncio.sleep(0.5)

    async def _watch_trades(self, exchange: ccxtpro.Exchange, symbol: str, market: str) -> None:
        while not self._stop.is_set():
            try:
                trades = await exchange.watch_trades(symbol)
                for t in trades[-10:]:
                    trade = TradeState(
                        ts_ms=int(t.get("timestamp") or time.time() * 1000),
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
            except Exception:
                await asyncio.sleep(0.5)

