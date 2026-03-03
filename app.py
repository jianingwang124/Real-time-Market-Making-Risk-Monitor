from __future__ import annotations

import asyncio
import os
import threading
import time
import sys

import streamlit as st

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


def main() -> None:
    st.set_page_config(layout="wide", page_title="Binance MM Risk Monitor")
    st.title("Real-time Market Making Risk Monitor (Binance Spot/Futures)")

    runner = get_runner()
    st.sidebar.header("Inventory")
    spot_pos = st.sidebar.number_input("Spot BTC Position", value=0.0, step=0.01, format="%.4f")
    fut_pos = st.sidebar.number_input("Futures BTC Position", value=0.0, step=0.01, format="%.4f")
    runner.engine.buffer.update_positions(spot_btc=spot_pos, futures_btc=fut_pos)
    st.sidebar.caption("Positions feed Delta and indifference price.")

    placeholder = st.empty()
    while True:
        snap = runner.engine.buffer.snapshot()
        metrics = snap["metrics"]
        greeks = snap["greeks"]
        flags = snap["risk_flags"]

        with placeholder.container():
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Delta (BTC)", f'{greeks.get("delta", 0.0):.4f}')
            c2.metric("Gamma", f'{greeks.get("gamma", 0.0):.4f}')
            c3.metric("Vega", f'{greeks.get("vega", 0.0):.4f}')
            c4.metric("OFI Top10", f'{metrics.get("ofi_top10", 0.0):.4f}')

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Mid Price", f'{metrics.get("mid_price", 0.0):,.2f} USDT')
            r2.metric("Indifference Price", f'{metrics.get("indifference_price", 0.0):,.2f} USDT')
            r3.metric("Liq Cost (1m)", f'{metrics.get("liquidation_cost_1m", 0.0):,.2f} USDT')
            r4.metric("L-VaR", f'{metrics.get("lvar", 0.0):,.2f} USDT')

            st.subheader("Black Swan Stress")
            s1, s2 = st.columns(2)
            s1.metric("Stress Mid", f'{metrics.get("stress_mid", 0.0):,.2f} USDT')
            s2.metric(
                "Stress Liq Cost",
                f'{metrics.get("stress_liquidation_cost", 0.0):,.2f} USDT',
            )

            st.subheader("Risk Limits")
            render_limit(flags.get("delta_limit_breached", False), "Delta")
            render_limit(flags.get("ofi_limit_breached", False), "OFI")
            render_limit(flags.get("liq_cost_limit_breached", False), "Liquidity Cost")
            render_limit(flags.get("lvar_limit_breached", False), "L-VaR")

        time.sleep(1.0)


if __name__ == "__main__":
    main()
