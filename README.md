# Binance Real-time Market Making Risk Monitor

Template for a production-oriented risk monitor for Binance Spot/Futures market making, with live WebSocket market data, low-latency analytics, stress testing, and dashboarding.

## 1) Objectives

- Detect intraday risk build-up in inventory, flow imbalance, and liquidity.
- Quantify tail risk via Liquidity-adjusted VaR (L-VaR) and stress scenarios.
- Surface limit breaches in real time with deterministic, thread-safe state handling.

## 2) Architecture

- **Data Layer** (`connector.py`)
  - `ccxt.pro` asyncio WebSocket manager.
  - Streams:
    - Level-2 order book (`watch_order_book`) for BTCUSDT Spot/Futures.
    - Aggregate trade proxy (`watch_trades`) for BTCUSDT Spot/Futures.
- **Analytics Layer** (`metrics.py`)
  - OFI (top 10 levels).
  - Inventory delta + Avellaneda-Stoikov indifference price.
  - 1-minute liquidation cost from current depth.
- **Risk Layer** (`stress_test.py`)
  - Liquidity-adjusted VaR.
  - Black swan scenario: down gap + bid-side liquidity decay.
- **Engine** (`engine.py`)
  - Async event queue.
  - Periodic risk loop.
  - Shared thread-safe buffer for UI/API consumers.
- **Interface** (`app.py`)
  - Streamlit dashboard for Greeks, risk metrics, and risk-limit status.

## 3) Project Structure

```text
.
├── app.py
├── pyproject.toml
├── README.md
├── requirements.txt
└── src
    └── risk_monitor
        ├── __init__.py
        ├── buffer.py
        ├── config.py
        ├── connector.py
        ├── engine.py
        ├── main.py
        ├── metrics.py
        ├── models.py
        └── stress_test.py
```

## 4) Runbook

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
streamlit run app.py
```

For headless engine execution:

```bash
python -m risk_monitor.main
```

## 5) Risk Control Baseline

- **Hard limits**
  - `max_abs_delta_btc`
  - `max_lvar_usdt`
  - `max_liquidation_cost_usdt`
  - `max_abs_ofi`
- **Limit policy**
  - Breach -> alert + UI red status.
  - Persistent breach -> throttle quoting / reduce inventory.
  - Severe breach -> kill-switch for strategy order gateway.

## 6) Operational Robustness Checklist

- **Data reliability**
  - WS reconnect with bounded retry.
  - Sequence sanity checks and stale-data detection.
- **Concurrency safety**
  - Shared state protected with lock (`SharedBuffer`).
  - Async producer/consumer decoupling via bounded queue.
- **Failure containment**
  - Risk loop independent from feed tasks.
  - Backpressure handling on queue overflow (drop oldest).
- **Observability**
  - Emit per-loop latency, queue depth, stale feed counters.
  - Export metrics to Prometheus/StatsD.
- **Disaster controls**
  - Graceful shutdown hooks.
  - Playbook for exchange/API outage and partial fills.

## 7) Production Hardening (Next)

- Add authenticated user data streams for exact account/position sync.
- Persist tick/risk snapshots for replay and post-trade forensics.
- Add unit tests for OFI, liquidation model, L-VaR, and stress scenarios.
- Add strategy gateway integration for automated risk actions.

