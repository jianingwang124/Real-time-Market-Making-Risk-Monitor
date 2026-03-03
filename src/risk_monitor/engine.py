from __future__ import annotations

import asyncio
from collections import deque

from risk_monitor.buffer import SharedBuffer
from risk_monitor.config import EngineConfig, RISK_LIMITS
from risk_monitor.connector import BinanceWebSocketManager
from risk_monitor.metrics import (
    compute_ofi,
    indifference_price,
    inventory_delta,
    liquidation_cost_1m,
    mid_price,
)
from risk_monitor.models import BookState, MarketEvent
from risk_monitor.stress_test import black_swan_scenario, liquidity_adjusted_var


class RiskEngine:
    def __init__(self, cfg: EngineConfig | None = None) -> None:
        self.cfg = cfg or EngineConfig()
        self.buffer = SharedBuffer()
        self.queue: asyncio.Queue[MarketEvent] = asyncio.Queue(maxsize=10000)
        self.returns = deque(maxlen=5000)
        self._last_mid = None
        self._running = False
        self.connector = BinanceWebSocketManager(
            spot_symbol=self.cfg.spot_symbol,
            futures_symbol=self.cfg.futures_symbol,
            depth_levels=self.cfg.depth_levels,
            event_sink=self.on_event,
        )

    async def on_event(self, event: MarketEvent) -> None:
        if self.queue.full():
            _ = self.queue.get_nowait()
            self.queue.task_done()
        await self.queue.put(event)

    async def run(self) -> None:
        self._running = True
        tasks = [
            asyncio.create_task(self.connector.run()),
            asyncio.create_task(self._consume_events()),
            asyncio.create_task(self._risk_loop()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc:
                raise exc

    async def stop(self) -> None:
        self._running = False
        await self.connector.close()

    async def _consume_events(self) -> None:
        while self._running:
            event = await self.queue.get()
            try:
                if event.event_type == "depth":
                    book: BookState = event.payload["book"]
                    self.buffer.update_book(event.market, book)
                    curr_mid = mid_price(book)
                    if curr_mid > 0 and self._last_mid and self._last_mid > 0:
                        ret = (curr_mid / self._last_mid) - 1.0
                        self.returns.append(ret)
                    if curr_mid > 0:
                        self._last_mid = curr_mid
                elif event.event_type == "agg_trade":
                    self.buffer.append_trade(event.payload["trade"])
            finally:
                self.queue.task_done()

    async def _risk_loop(self) -> None:
        while self._running:
            snap = self.buffer.snapshot()
            spot_book = snap["books"].get("spot")
            prev_spot_book = snap["prev_books"].get("spot")
            if spot_book:
                delta = inventory_delta(
                    snap["positions"]["spot_btc"], snap["positions"]["futures_btc"]
                )
                mid = mid_price(spot_book)
                ofi = (
                    compute_ofi(prev_spot_book, spot_book, top_n=self.cfg.ofi_levels)
                    if prev_spot_book
                    else 0.0
                )
                res_price = indifference_price(
                    mid=mid,
                    position_delta=delta,
                    gamma=self.cfg.inventory_gamma,
                    sigma=self.cfg.inventory_sigma,
                    horizon_seconds=self.cfg.horizon_seconds,
                )
                liq_cost = liquidation_cost_1m(
                    position_btc=delta,
                    book=spot_book,
                    penalty_bps=self.cfg.liquidation_penalty_bps,
                )
                lvar = liquidity_adjusted_var(
                    returns=list(self.returns),
                    notional=abs(delta) * mid,
                    liquidation_cost=liq_cost,
                    confidence_level=self.cfg.confidence_level,
                )
                stress = black_swan_scenario(
                    book=spot_book,
                    position_btc=delta,
                    gap_down=self.cfg.black_swan_gap,
                    bid_decay=self.cfg.black_swan_bid_decay,
                    penalty_bps=self.cfg.liquidation_penalty_bps,
                )

                metrics = {
                    "mid_price": mid,
                    "ofi_top10": ofi,
                    "indifference_price": res_price,
                    "liquidation_cost_1m": liq_cost,
                    "lvar": lvar,
                    "stress_mid": stress["stress_mid"],
                    "stress_liquidation_cost": stress["stress_liquidation_cost"],
                }
                greeks = {"delta": delta, "gamma": 0.0, "vega": 0.0}
                risk_flags = {
                    "delta_limit_breached": abs(delta) > RISK_LIMITS["max_abs_delta_btc"],
                    "lvar_limit_breached": lvar > RISK_LIMITS["max_lvar_usdt"],
                    "liq_cost_limit_breached": liq_cost
                    > RISK_LIMITS["max_liquidation_cost_usdt"],
                    "ofi_limit_breached": abs(ofi) > RISK_LIMITS["max_abs_ofi"],
                }
                self.buffer.update_metrics(metrics=metrics, greeks=greeks, risk_flags=risk_flags)

            await asyncio.sleep(self.cfg.risk_refresh_ms / 1000.0)

