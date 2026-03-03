from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from risk_monitor.metrics import liquidation_cost_1m
from risk_monitor.models import BookState


def liquidity_adjusted_var(
    returns: Sequence[float],
    notional: float,
    liquidation_cost: float,
    confidence_level: float = 0.99,
) -> float:
    """
    L-VaR = market VaR + liquidation cost.
    returns: arithmetic returns samples.
    """
    if not returns:
        return float(liquidation_cost)
    arr = np.asarray(returns, dtype=float)
    pnl = notional * arr
    q = np.quantile(pnl, 1.0 - confidence_level)
    market_var = abs(float(q))
    return float(market_var + liquidation_cost)


def black_swan_scenario(
    book: BookState,
    position_btc: float,
    gap_down: float = 0.08,
    bid_decay: float = 0.7,
    penalty_bps: float = 5.0,
) -> dict[str, float]:
    """
    Stress: price gaps down and bid liquidity vanishes.
    - Applies gap to both sides to preserve spread shape.
    - Shrinks bid quantities aggressively.
    """
    if not book.bids or not book.asks:
        return {"stress_mid": 0.0, "stress_liquidation_cost": math.inf}

    shocked_bids = [[px * (1.0 - gap_down), qty * (1.0 - bid_decay)] for px, qty in book.bids]
    shocked_asks = [[px * (1.0 - gap_down), qty] for px, qty in book.asks]
    shocked_book = BookState(bids=shocked_bids, asks=shocked_asks, ts_ms=book.ts_ms)
    stress_cost = liquidation_cost_1m(position_btc, shocked_book, penalty_bps=penalty_bps)
    stress_mid = (shocked_book.bids[0][0] + shocked_book.asks[0][0]) / 2.0
    return {"stress_mid": float(stress_mid), "stress_liquidation_cost": float(stress_cost)}

