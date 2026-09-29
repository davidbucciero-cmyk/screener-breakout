"""Tests du backtester (etape 5)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from crypto_quant.backtest import BacktestConfig, compute_live_weights, run_backtest
from crypto_quant.synthetic import synthetic_dataframe

FIXED_END_MS = 1_700_000_000_000


def _small_multi_asset_universe():
    return {
        "TREND_UP": synthetic_dataframe(
            300, end_ms=FIXED_END_MS, drift=0.003, gbm_vol=0.005, momentum_rho=0.6, ou_theta=0.0, ou_sigma=0.0, seed=42
        ),
        "MEANREV": synthetic_dataframe(
            300, end_ms=FIXED_END_MS, drift=0.0, gbm_vol=0.0005, ou_theta=0.25, ou_sigma=0.03, seed=6
        ),
    }


def test_run_backtest_basic_shape_and_no_nans():
    price_data = _small_multi_asset_universe()
    cfg = BacktestConfig()
    result = run_backtest(price_data, cfg)

    assert len(result.equity) > 0
    assert not result.equity.isna().any()
    assert list(result.weights_history.columns) == list(price_data.keys())
    assert not result.weights_history.isna().any().any()
    assert result.equity.iloc[0] == cfg.initial_capital


def test_leverage_never_exceeds_max_leverage():
    price_data = _small_multi_asset_universe()
    cfg = BacktestConfig(max_leverage=1.0)
    result = run_backtest(price_data, cfg)

    total_exposure = result.weights_history.sum(axis=1)
    assert (total_exposure <= 1.0 + 1e-9).all(), "L'exposition totale ne doit jamais depasser max_leverage (spot)"
    assert (total_exposure >= 0).all()


def test_transaction_costs_reduce_final_equity():
    price_data = _small_multi_asset_universe()

    cfg_no_cost = BacktestConfig(transaction_cost_bps=0.0)
    cfg_high_cost = BacktestConfig(transaction_cost_bps=200.0)

    result_no_cost = run_backtest(price_data, cfg_no_cost)
    result_high_cost = run_backtest(price_data, cfg_high_cost)

    assert result_high_cost.turnover_history.sum() > 0, "Le test suppose du turnover reel pour etre significatif"
    assert result_high_cost.equity.iloc[-1] < result_no_cost.equity.iloc[-1], (
        "Des couts de transaction plus eleves doivent reduire l'equity finale, toutes choses egales par ailleurs"
    )


def test_rebalance_threshold_zero_is_backward_compatible():
    # threshold=0.0 (valeur par defaut) doit rebalancer a chaque bougie,
    # exactement comme avant l'ajout du parametre.
    price_data = _small_multi_asset_universe()
    result_default = run_backtest(price_data, BacktestConfig())
    result_explicit_zero = run_backtest(price_data, BacktestConfig(rebalance_threshold=0.0))
    pd.testing.assert_frame_equal(result_default.weights_history, result_explicit_zero.weights_history)
    pd.testing.assert_series_equal(result_default.equity, result_explicit_zero.equity)


def test_rebalance_threshold_reduces_turnover():
    # Trouve en investiguant le resultat tres negatif sur donnees reelles
    # (etape 9, README) : sur des signaux qui bougent peu bougie a bougie, un
    # rebalancement systematique genere un turnover (et donc un cout cumule)
    # bien plus eleve que necessaire par rapport a l'horizon reel du signal.
    price_data = _small_multi_asset_universe()
    result_no_threshold = run_backtest(price_data, BacktestConfig(rebalance_threshold=0.0))
    result_with_threshold = run_backtest(price_data, BacktestConfig(rebalance_threshold=0.1))

    assert result_no_threshold.turnover_history.sum() > 0, "Le test suppose du turnover reel sans seuil"
    assert result_with_threshold.turnover_history.sum() < result_no_threshold.turnover_history.sum(), (
        "Une zone morte doit strictement reduire le turnover cumule"
    )


def test_rebalance_threshold_still_liquidates_immediately_on_circuit_breaker():
    # Un seuil de rebalancement eleve ne doit JAMAIS empecher la liquidation
    # d'urgence du coupe-circuit (action de risque, pas de signal). Reutilise
    # le meme krach construit a la main que test_drawdown_circuit_breaker_
    # halts_during_backtest_crash (voir sa docstring pour le pourquoi).
    n_uptrend = 25
    uptrend = 100 * (1.002 ** np.arange(n_uptrend))
    crash_bottom = uptrend[-1] * 0.65
    n_flat, n_recovery = 30, 40
    flat = np.full(n_flat, crash_bottom)
    recovery = np.linspace(crash_bottom, crash_bottom * 1.5, n_recovery)
    close = np.concatenate([uptrend, [crash_bottom], flat, recovery])
    index = pd.date_range("2024-01-01", periods=len(close), freq="h", tz="UTC")
    price_data = {"CRASH": pd.DataFrame({"close": close}, index=index)}

    cfg = BacktestConfig(
        ema_fast=5, ema_slow=20, ema_vol_window=20,
        hurst_window=20, hurst_max_lag=8, ou_window=20,
        halt_drawdown=0.20, resume_drawdown=0.10, circuit_breaker_cooldown=20,
        rebalance_threshold=0.9,  # seuil enorme : ne devrait jamais bloquer une liquidation d'urgence
    )
    result = run_backtest(price_data, cfg)

    halted_periods = ~result.trading_allowed_history
    assert halted_periods.any(), "Le test suppose qu'un coupe-circuit se declenche reellement sur ce crash simule"
    # Sur chaque bougie ou le trading est coupe, le poids detenu doit etre nul
    # (liquidation immediate), quel que soit rebalance_threshold.
    assert (result.weights_history.loc[halted_periods].abs().sum(axis=1) < 1e-9).all()


def test_drawdown_circuit_breaker_halts_during_backtest_crash():
    # Serie construite a la main (pas le generateur synthetique) pour un
    # controle total. Montee courte (juste assez pour la periode de warm-up
    # des signaux), puis krach de -35% en UNE SEULE bougie : le poids
    # applique a ce passage a ete decide juste avant, avec les donnees
    # d'avant le krach - impossible pour le modele de l'eviter en reagissant
    # plus vite, ce qui rend le test deterministe. Un krach etale sur
    # plusieurs bougies laisserait le modele (EMA rapide) se degager avant
    # que le seuil de drawdown soit atteint, ce qui ne testerait alors que
    # la reactivite du signal, pas le coupe-circuit lui-meme.
    n_uptrend = 25
    uptrend = 100 * (1.002 ** np.arange(n_uptrend))
    crash_bottom = uptrend[-1] * 0.65  # -35% en une bougie
    n_flat, n_recovery = 30, 40
    flat = np.full(n_flat, crash_bottom)
    recovery = np.linspace(crash_bottom, crash_bottom * 1.5, n_recovery)
    close = np.concatenate([uptrend, [crash_bottom], flat, recovery])

    index = pd.date_range("2024-01-01", periods=len(close), freq="h", tz="UTC")
    price_data = {"CRASH": pd.DataFrame({"close": close}, index=index)}

    cfg = BacktestConfig(
        ema_fast=5, ema_slow=20, ema_vol_window=20,
        hurst_window=20, hurst_max_lag=8, ou_window=20,
        halt_drawdown=0.20, resume_drawdown=0.10, circuit_breaker_cooldown=20,
    )
    result = run_backtest(price_data, cfg)

    assert not result.trading_allowed_history.all(), "Le krach de -35% doit declencher le coupe-circuit au moins une fois"
    assert result.trading_allowed_history.iloc[-1], "Le cooldown doit finir par autoriser une reprise"

    # Pendant la halte, aucune position ne doit etre ouverte (poids nul).
    halted_periods = ~result.trading_allowed_history
    assert (result.weights_history.loc[halted_periods].sum(axis=1) == 0).all()

    # La reprise doit intervenir exactement cooldown_periods bougies apres la
    # halte (puisque le prix reste plat pendant la halte, seul le cooldown
    # peut expliquer la reprise, pas une recuperation de l'equity).
    first_halt_idx = result.trading_allowed_history.values.tolist().index(False)
    resumed = result.trading_allowed_history.iloc[first_halt_idx:]
    first_resume_offset = resumed.values.tolist().index(True)
    assert first_resume_offset == cfg.circuit_breaker_cooldown


def test_compute_live_weights_returns_series_summing_to_at_most_max_leverage():
    price_data = _small_multi_asset_universe()
    cfg = BacktestConfig(max_leverage=1.0)

    weights = compute_live_weights(price_data, cfg)

    assert set(weights.index) == set(price_data.keys())
    assert (weights >= 0).all(), "Long-only : jamais de poids negatif"
    assert weights.sum() <= 1.0 + 1e-9


def test_compute_live_weights_raises_on_insufficient_history():
    price_data = {"TINY": synthetic_dataframe(10, end_ms=FIXED_END_MS, drift=0.0, gbm_vol=0.01, seed=1)}
    cfg = BacktestConfig()  # fenetres par defaut (100) >> 10 bougies disponibles
    with pytest.raises(ValueError):
        compute_live_weights(price_data, cfg)


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK: {t.__name__}")
    print(f"\nTous les tests backtest.py passent ({len(tests)} tests).")
