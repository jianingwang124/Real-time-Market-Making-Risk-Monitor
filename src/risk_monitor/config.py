from dataclasses import dataclass


@dataclass(frozen=True)
class EngineConfig:
    spot_symbol: str = "BTC/USDT"
    futures_symbol: str = "BTC/USDT:USDT"
    depth_levels: int = 50
    ofi_levels: int = 10
    markout_window_sec: int = 60
    risk_refresh_ms: int = 1000
    inventory_gamma: float = 0.1
    inventory_sigma: float = 0.02
    horizon_seconds: int = 60
    confidence_level: float = 0.99
    black_swan_gap: float = 0.08
    black_swan_bid_decay: float = 0.7
    liquidation_penalty_bps: float = 5.0


RISK_LIMITS = {
    "max_abs_delta_btc": 1.5,
    "max_lvar_usdt": 120000.0,
    "max_liquidation_cost_usdt": 75000.0,
    "max_abs_ofi": 50.0,
}

