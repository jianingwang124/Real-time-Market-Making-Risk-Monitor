from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from datetime import datetime

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from risk_monitor.engine import RiskEngine


class EngineRunner:
    def __init__(self) -> None:
        self.engine = RiskEngine()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.started = False

    def start(self) -> None:
        if not self.started:
            self.started = True
            self.thread.start()

    def _run(self) -> None:
        asyncio.run(self.engine.run())


@st.cache_resource
def get_runner() -> EngineRunner:
    runner = EngineRunner()
    runner.start()
    return runner


def render_limit(flag: bool, label: str) -> None:
    if flag:
        st.error(f"{label}: BREACHED")
    else:
        st.success(f"{label}: OK")


def render_overview(snap: dict) -> None:
    metrics = snap["metrics"]
    greeks = snap["greeks"]
    flags = snap["risk_flags"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Delta (BTC)", f'{greeks.get("delta", 0.0):.4f}')
    c2.metric("Gamma", f'{greeks.get("gamma", 0.0):.4f}')
    c3.metric("Vega", f'{greeks.get("vega", 0.0):.4f}')
    c4.metric("OFI Top 10", f'{metrics.get("ofi_top10", 0.0):.4f}')

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Mid Price", f'{metrics.get("mid_price", 0.0):,.2f} USDT')
    r2.metric("Indifference Price", f'{metrics.get("indifference_price", 0.0):,.2f} USDT')
    r3.metric("Liq Cost (1m)", f'{metrics.get("liquidation_cost_1m", 0.0):,.2f} USDT')
    r4.metric("L-VaR", f'{metrics.get("lvar", 0.0):,.2f} USDT')

    st.subheader("Black Swan Stress")
    s1, s2 = st.columns(2)
    s1.metric("Stress Mid", f'{metrics.get("stress_mid", 0.0):,.2f} USDT')
    s2.metric("Stress Liq Cost", f'{metrics.get("stress_liquidation_cost", 0.0):,.2f} USDT')

    st.subheader("Risk Limits")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_limit(flags.get("delta_limit_breached", False), "Delta")
    with c2:
        render_limit(flags.get("ofi_limit_breached", False), "OFI")
    with c3:
        render_limit(flags.get("liq_cost_limit_breached", False), "Liquidity Cost")
    with c4:
        render_limit(flags.get("lvar_limit_breached", False), "L-VaR")


def render_market_charts(snap: dict) -> None:
    book = snap["books"].get("spot")
    trades = [trade for trade in snap["trades"] if trade.market == "spot"][-250:]
    history = snap.get("metrics_history", [])[-300:]

    if not book or not book.bids or not book.asks:
        st.info("Waiting for Binance Spot market data. Charts will populate after the first order-book update.")
        return

    best_bid, best_ask = book.bids[0][0], book.asks[0][0]
    spread_bps = ((best_ask - best_bid) / ((best_ask + best_bid) / 2.0)) * 10_000
    m1, m2, m3 = st.columns(3)
    m1.metric("Best Bid", f"{best_bid:,.2f}")
    m2.metric("Best Ask", f"{best_ask:,.2f}")
    m3.metric("Spread", f"{spread_bps:.2f} bps")

    left, right = st.columns((3, 2))
    with left:
        trade_fig = go.Figure()
        if trades:
            buy_trades = [trade for trade in trades if trade.side == "buy"]
            sell_trades = [trade for trade in trades if trade.side == "sell"]
            trade_fig.add_trace(
                go.Scatter(
                    x=[datetime.fromtimestamp(trade.ts_ms / 1000) for trade in trades],
                    y=[trade.price for trade in trades],
                    mode="lines",
                    line={"color": "#A8B7D1", "width": 1.5},
                    name="BTCUSDT trade price",
                )
            )
            trade_fig.add_trace(
                go.Scatter(
                    x=[datetime.fromtimestamp(trade.ts_ms / 1000) for trade in buy_trades],
                    y=[trade.price for trade in buy_trades],
                    mode="markers",
                    marker={"color": "#20C997", "size": 7},
                    name="Buyer initiated",
                )
            )
            trade_fig.add_trace(
                go.Scatter(
                    x=[datetime.fromtimestamp(trade.ts_ms / 1000) for trade in sell_trades],
                    y=[trade.price for trade in sell_trades],
                    mode="markers",
                    marker={"color": "#F05D5E", "size": 7},
                    name="Seller initiated",
                )
            )
        trade_fig.update_layout(
            title="Recent Aggregate Trades",
            height=350,
            margin={"l": 12, "r": 12, "t": 48, "b": 12},
            legend={"orientation": "h", "y": 1.12},
            template="plotly_dark",
        )
        trade_fig.update_yaxes(tickformat=",.0f", title="USDT")
        st.plotly_chart(
            trade_fig,
            use_container_width=True,
            config={"displayModeBar": False},
            key="recent_trade_chart",
        )

    with right:
        bid_levels = book.bids[:15]
        ask_levels = book.asks[:15]
        bid_depth, ask_depth = [], []
        running_bid, running_ask = 0.0, 0.0
        for _, qty in bid_levels:
            running_bid += qty
            bid_depth.append(running_bid)
        for _, qty in ask_levels:
            running_ask += qty
            ask_depth.append(running_ask)

        depth_fig = go.Figure()
        depth_fig.add_trace(
            go.Bar(
                x=bid_depth,
                y=[price for price, _ in bid_levels],
                orientation="h",
                marker_color="#20C997",
                name="Cumulative bids",
            )
        )
        depth_fig.add_trace(
            go.Bar(
                x=[-value for value in ask_depth],
                y=[price for price, _ in ask_levels],
                orientation="h",
                marker_color="#F05D5E",
                name="Cumulative asks",
            )
        )
        depth_fig.update_layout(
            title="L2 Liquidity Profile (15 levels)",
            barmode="overlay",
            height=350,
            margin={"l": 12, "r": 12, "t": 48, "b": 12},
            showlegend=False,
            template="plotly_dark",
        )
        depth_fig.update_xaxes(title="Cumulative BTC", zeroline=True, zerolinecolor="#77839B")
        depth_fig.update_yaxes(tickformat=",.0f", title="Price (USDT)")
        st.plotly_chart(
            depth_fig,
            use_container_width=True,
            config={"displayModeBar": False},
            key="l2_liquidity_profile_chart",
        )

    if history:
        history_times = [datetime.fromtimestamp(point["ts"]) for point in history]
        risk_fig = make_subplots(specs=[[{"secondary_y": True}]])
        risk_fig.add_trace(
            go.Bar(
                x=history_times,
                y=[point.get("ofi_top10", 0.0) for point in history],
                name="OFI Top 10",
                marker_color="#496A81",
                opacity=0.8,
            ),
            secondary_y=False,
        )
        risk_fig.add_trace(
            go.Scatter(
                x=history_times,
                y=[point.get("lvar", 0.0) for point in history],
                name="L-VaR",
                line={"color": "#F4A261", "width": 2.5},
            ),
            secondary_y=True,
        )
        risk_fig.update_layout(
            title="Order Flow and Liquidity-Adjusted VaR",
            height=310,
            margin={"l": 12, "r": 12, "t": 48, "b": 12},
            legend={"orientation": "h", "y": 1.12},
            template="plotly_dark",
        )
        risk_fig.update_yaxes(title_text="OFI", secondary_y=False)
        risk_fig.update_yaxes(title_text="USDT", tickformat=",.0f", secondary_y=True)
        st.plotly_chart(
            risk_fig,
            use_container_width=True,
            config={"displayModeBar": False},
            key="risk_time_series_chart",
        )
    else:
        st.caption("Collecting metric history for the OFI and L-VaR chart...")


def main() -> None:
    st.set_page_config(layout="wide", page_title="Binance MM Risk Monitor")
    st.markdown(
        """
        <style>
        .stApp { background: radial-gradient(circle at top, #16202f 0%, #0b1220 45%, #060b14 100%); color: #e6edf3; }
        section[data-testid="stSidebar"] { background: linear-gradient(180deg, #0e1628 0%, #0a0f19 100%); border-right: 1px solid rgba(148, 163, 184, 0.18); }
        .stTabs [data-baseweb="tab-list"] { gap: 0.75rem; }
        .stTabs [data-baseweb="tab"] { background: rgba(15, 23, 42, 0.82); color: #cbd5e1; border-radius: 999px; border: 1px solid rgba(148, 163, 184, 0.18); padding: 0.35rem 0.9rem; }
        .stTabs [aria-selected="true"] { background: linear-gradient(135deg, #1d4ed8 0%, #0f766e 100%); color: white; border-color: transparent; }
        div[data-testid="stMetric"] { background: rgba(15, 23, 42, 0.72); border: 1px solid rgba(148, 163, 184, 0.12); border-radius: 16px; padding: 1rem 1rem 0.75rem 1rem; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18); }
        .stButton > button { background: linear-gradient(135deg, #2563eb 0%, #0f766e 100%); color: white; border: none; }
        [data-testid="stMetricValue"] { color: #f8fafc; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Real-time Market Making Risk Monitor")
    st.caption("Binance Spot/Futures | live inventory, liquidity, and tail-risk controls")

    runner = get_runner()
    st.sidebar.header("Inventory")
    spot_pos = st.sidebar.number_input("Spot BTC Position", value=0.0, step=0.01, format="%.4f")
    fut_pos = st.sidebar.number_input("Futures BTC Position", value=0.0, step=0.01, format="%.4f")
    runner.engine.buffer.update_positions(spot_btc=spot_pos, futures_btc=fut_pos)
    st.sidebar.caption("Positions feed Delta and the Avellaneda-Stoikov indifference price.")

    overview_tab, charts_tab = st.tabs(["Risk Overview", "Market Charts"])
    snap = runner.engine.buffer.snapshot()
    with overview_tab:
        render_overview(snap)
    with charts_tab:
        render_market_charts(snap)

    time.sleep(1.0)
    st.rerun()


if __name__ == "__main__":
    main()
