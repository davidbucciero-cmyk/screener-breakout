"""Genere les donnees pour le dashboard (crypto_quant/dashboard/index.html).

Tout sort du vrai pipeline (run_backtest / WalkForwardValidator /
compute_live_weights), aucun chiffre invente. Par defaut utilise des
donnees synthetiques (pas d'acces reseau requis) ; remplace `price_data`
par un vrai historique CCXTDataFeed des que Kraken est accessible pour
avoir un dashboard sur donnees de marche reelles.

Usage: python -m crypto_quant.dashboard
"""
import json
import os
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from crypto_quant.backtest import (
    BacktestConfig,
    WalkForwardValidator,
    compute_live_weights,
    compute_symbol_signals,
    run_backtest,
)
from crypto_quant.metrics import summarize_performance
from crypto_quant.synthetic import synthetic_dataframe

FIXED_END_MS = 1_759_000_000_000  # horodatage fixe pour reproductibilite du jeu de demo
N_PERIODS = 2200  # ~ 3 mois de bougies 1h

# Univers par defaut du projet (config.py), avec des dynamiques synthetiques
# variees (tendance, retour a la moyenne, marche aleatoire) pour illustrer
# les 3 regimes geres par le systeme.
DEMO_UNIVERSE_KWARGS = {
    "BTC/USD": dict(start_price=62000, drift=0.0006, gbm_vol=0.006, momentum_rho=0.35, ou_theta=0.02, ou_sigma=0.01, seed=101),
    "ETH/USD": dict(start_price=3400, drift=-0.0003, gbm_vol=0.007, momentum_rho=0.3, ou_theta=0.015, ou_sigma=0.012, seed=102),
    "SOL/USD": dict(start_price=145, drift=0.0002, gbm_vol=0.009, ou_theta=0.06, ou_sigma=0.02, seed=103),
    "ADA/USD": dict(start_price=0.45, drift=0.0, gbm_vol=0.008, ou_theta=0.0, ou_sigma=0.0, seed=104),
    "XRP/USD": dict(start_price=0.55, drift=0.0004, gbm_vol=0.0065, momentum_rho=0.25, ou_theta=0.01, ou_sigma=0.008, seed=105),
}


def series_to_points(s: pd.Series, max_points: int = 300):
    if len(s) > max_points:
        step = len(s) // max_points
        s = s.iloc[::step]
    return [{"t": ts.isoformat(), "v": float(v)} for ts, v in s.items()]


def _clean(d: dict) -> dict:
    return {k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in d.items()}


def generate_dashboard_data(price_data: dict, cfg: BacktestConfig, data_source_label: str) -> dict:
    result = run_backtest(price_data, cfg)
    summary = summarize_performance(result.equity, periods_per_year=8760, weights_history=result.weights_history)

    config_grid = [
        BacktestConfig(ema_fast=8, ema_slow=32),
        BacktestConfig(ema_fast=12, ema_slow=48),
        BacktestConfig(ema_fast=16, ema_slow=64),
    ]
    validator = WalkForwardValidator(config_grid, n_splits=4, periods_per_year=8760, min_valid_periods=30)
    oos_equity, fold_results = validator.run(price_data)
    oos_summary = summarize_performance(oos_equity, periods_per_year=8760)

    aligned_signals = {s: compute_symbol_signals(df, cfg) for s, df in price_data.items()}
    live_weights = compute_live_weights(price_data, cfg)

    current_state = []
    for symbol in price_data:
        sig = aligned_signals[symbol].dropna(subset=["hurst", "ema_trend", "ewma_vol"]).iloc[-1]
        hurst = float(sig["hurst"])
        regime = "Tendance" if hurst > 0.55 else ("Retour a la moyenne" if hurst < 0.45 else "Neutre")
        current_state.append(
            {
                "symbol": symbol,
                "close": float(sig["close"]),
                "hurst": hurst,
                "regime": regime,
                "ema_trend": float(sig["ema_trend"]) if pd.notna(sig["ema_trend"]) else None,
                "ou_signal": float(sig["ou_signal"]) if pd.notna(sig["ou_signal"]) else None,
                "ewma_vol": float(sig["ewma_vol"]),
                "target_weight": float(live_weights.get(symbol, 0.0)),
            }
        )

    return {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "data_source": data_source_label,
        "config": {
            "pairs": list(price_data.keys()),
            "timeframe": "1h",
            "target_vol": cfg.target_vol,
            "max_leverage": cfg.max_leverage,
            "transaction_cost_bps": cfg.transaction_cost_bps,
            "halt_drawdown": cfg.halt_drawdown,
        },
        "backtest_summary": _clean(summary),
        "oos_summary": _clean(oos_summary),
        "equity_curve": series_to_points(result.equity),
        "oos_equity_curve": series_to_points(oos_equity),
        "weights_history": {symbol: series_to_points(result.weights_history[symbol]) for symbol in price_data},
        "fold_results": [
            {
                "train_start": f.train_start.isoformat(),
                "train_end": f.train_end.isoformat(),
                "test_start": f.test_start.isoformat(),
                "test_end": f.test_end.isoformat(),
                "chosen_ema": f"{f.chosen_config.ema_fast}/{f.chosen_config.ema_slow}",
                "train_sharpe": None if np.isnan(f.train_sharpe) else float(f.train_sharpe),
            }
            for f in fold_results
        ],
        "current_state": current_state,
    }


def main():
    price_data = {
        symbol: synthetic_dataframe(N_PERIODS, end_ms=FIXED_END_MS, **kwargs)
        for symbol, kwargs in DEMO_UNIVERSE_KWARGS.items()
    }
    cfg = BacktestConfig()
    output = generate_dashboard_data(
        price_data,
        cfg,
        data_source_label="synthetique (pipeline reel, donnees de marche simulees - Kraken inaccessible depuis cette session)",
    )

    out_dir = os.path.join(os.path.dirname(__file__), "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dashboard.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Ecrit : {out_path}")
    print("OOS summary:", json.dumps(output["oos_summary"], indent=2))


if __name__ == "__main__":
    main()
