from __future__ import annotations

import math
from typing import Iterable

import polars as pl

from risk_monitor.models import BookState


def _levels_to_df(levels: Iterable[list[float]], n: int) -> pl.DataFrame:
    clipped = list(levels)[:n]
    if not clipped:
        return pl.DataFrame({"price": [], "qty": []}, schema={"price": pl.Float64, "qty": pl.Float64})
    return pl.DataFrame(clipped, schema=["price", "qty"]).with_columns(
        pl.col("price").cast(pl.Float64),
        pl.col("qty").cast(pl.Float64),
    )


def compute_ofi(prev_book: BookState, curr_book: BookState, top_n: int = 10) -> float:
    """
    Top-N OFI approximation:
    positive => bid pressure, negative => ask pressure.
    """
    prev_bids = _levels_to_df(prev_book.bids, top_n)
    prev_asks = _levels_to_df(prev_book.asks, top_n)
    curr_bids = _levels_to_df(curr_book.bids, top_n)
    curr_asks = _levels_to_df(curr_book.asks, top_n)

    if prev_bids.height == 0 or prev_asks.height == 0 or curr_bids.height == 0 or curr_asks.height == 0:
        return 0.0

    bid_pressure = float(curr_bids["qty"].sum() - prev_bids["qty"].sum())
    ask_pressure = float(curr_asks["qty"].sum() - prev_asks["qty"].sum())
    return bid_pressure - ask_pressure


def mid_price(book: BookState) -> float:
    if not book.bids or not book.asks:
        return 0.0
    return (book.bids[0][0] + book.asks[0][0]) / 2.0


def inventory_delta(spot_btc: float, futures_btc: float) -> float:
    return float(spot_btc + futures_btc)


def indifference_price(
    mid: float,
    position_delta: float,
    gamma: float,
    sigma: float,
    horizon_seconds: float,
) -> float:
    # Avellaneda-Stoikov reservation (indifference) price.
    return float(mid - position_delta * gamma * (sigma**2) * horizon_seconds)


def liquidation_cost_1m(position_btc: float, book: BookState, penalty_bps: float = 5.0) -> float:
    """
    Expected cost (USDT) to liquidate current BTC inventory against top-of-book depth.
    Long inventory sells into bids; short inventory buys from asks.
    """
    size = abs(position_btc)
    if size <= 0 or not book.bids or not book.asks:
        return 0.0

    side_levels = book.bids if position_btc > 0 else book.asks
    df = _levels_to_df(side_levels, n=len(side_levels))
    if df.height == 0:
        return math.inf

    cum_df = df.with_columns(pl.col("qty").cum_sum().alias("cum_qty"))
    fillable = cum_df.filter(pl.col("cum_qty") >= size)

    if fillable.height == 0:
        return math.inf

    price_col = df["price"].to_list()
    qty_col = df["qty"].to_list()
    remaining = size
    cash = 0.0
    for px, qty in zip(price_col, qty_col):
        take = min(qty, remaining)
        cash += px * take
        remaining -= take
        if remaining <= 0:
            break

    mark = mid_price(book) * size
    impact = abs(mark - cash)
    fee_penalty = mark * (penalty_bps / 10000.0)
    return float(impact + fee_penalty)
