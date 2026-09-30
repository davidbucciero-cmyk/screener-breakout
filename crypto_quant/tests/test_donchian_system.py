"""Tests du systeme de breakout Donchian (etape 19)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from crypto_quant.donchian_system import DonchianConfig, run_donchian_backtest
from crypto_quant.synthetic import synthetic_dataframe

FIXED_END_MS = 1_700_000_000_000


def _light_cfg(**overrides):
    base = dict(entry_window=10, trend_ma_window=30, exit_window=5, atr_period=10)
    base.update(overrides)
    return DonchianConfig(**base)


def test_basic_shape_and_no_nans():
    price_data = {
        "X": synthetic_dataframe(
            250, end_ms=FIXED_END_MS, drift=0.003, gbm_vol=0.004, momentum_rho=0.6, ou_theta=0.0, ou_sigma=0.0, seed=7
        ),
    }
    result = run_donchian_backtest(price_data, _light_cfg())

    assert len(result.equity) > 0
    assert not result.equity.isna().any()
    assert list(result.weights_history.columns) == list(price_data.keys())
    assert not result.weights_history.isna().any().any()


def test_entry_executes_at_next_day_open_not_signal_day_close():
    # Rupture nette et deliberee un jour donne : le signal se lit a la
    # cloture de ce jour-la, mais l'entree doit se faire a l'OUVERTURE du
    # jour SUIVANT (pas a la cloture du jour du signal) - cf. docstring
    # module, difference deliberee avec discrete_trading.py.
    n_flat = 40
    flat = np.full(n_flat, 100.0)
    n_up = 20
    breakout = 100 * (1.02 ** np.arange(1, n_up + 1))  # rupture nette et soutenue
    close = np.concatenate([flat, breakout])
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    index = pd.date_range("2024-01-01", periods=len(close), freq="D", tz="UTC")
    df = pd.DataFrame(
        {"open": open_, "high": close * 1.001, "low": close * 0.999, "close": close, "volume": 1.0}, index=index
    )
    price_data = {"X": df}

    cfg = _light_cfg(entry_window=10, trend_ma_window=20, exit_window=5, atr_period=10)
    result = run_donchian_backtest(price_data, cfg)

    assert result.closed_trades or (result.weights_history["X"] > 0).any(), "au moins une entree attendue sur cette rupture nette"
    # Si une position est ouverte, son prix d'entree doit correspondre a
    # l'ouverture d'un jour, jamais a une cloture (les deux series ne se
    # recoupent qu'aux points ou open==close, absent ici par construction
    # sauf le tout premier jour).
    for trade in result.closed_trades:
        entry_day_open = df.loc[trade.entry_date, "open"]
        assert trade.entry_price == entry_day_open


def test_stop_loss_closes_trade_at_loss_on_sharp_drop():
    n_up = 80
    up = 100 * (1.01 ** np.arange(n_up))
    crash = up[-1] * np.linspace(1.0, 0.5, 10)
    close = np.concatenate([up, crash])
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    high = close * 1.001
    low = close * 0.999
    low[n_up] = close[n_up - 1] * 0.5  # la bougie du krach casse tres bas, sous n'importe quel stop ATR raisonnable
    index = pd.date_range("2023-01-01", periods=len(close), freq="D", tz="UTC")
    price_data = {"X": pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)}

    cfg = _light_cfg(entry_window=10, trend_ma_window=30, exit_window=5, atr_period=14, atr_stop_multiple=2.0)
    result = run_donchian_backtest(price_data, cfg)

    stop_exits = [t for t in result.closed_trades if t.exit_reason == "stop"]
    assert stop_exits, "le krach doit declencher au moins une sortie sur stop"
    assert all(t.exit_price < t.entry_price for t in stop_exits), "une sortie sur stop doit acter une perte"


def test_channel_exit_closes_trade_on_pullback_below_prior_low():
    # Montee forte, puis repli progressif (sous le stop ATR trop lointain
    # pour se declencher en premier) qui finit par casser le plus bas des
    # exit_window jours precedents.
    n_up = 60
    up = 100 * (1.02 ** np.arange(n_up))
    peak = up[-1]
    n_down = 15
    down = peak * np.linspace(1.0, 0.80, n_down)  # repli progressif de 20%
    close = np.concatenate([up, down])
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    index = pd.date_range("2023-01-01", periods=len(close), freq="D", tz="UTC")
    price_data = {
        "X": pd.DataFrame(
            {"open": open_, "high": close * 1.002, "low": close * 0.998, "close": close}, index=index
        )
    }

    cfg = _light_cfg(entry_window=10, trend_ma_window=30, exit_window=5, atr_period=14, atr_stop_multiple=10.0)
    result = run_donchian_backtest(price_data, cfg)

    channel_exits = [t for t in result.closed_trades if t.exit_reason == "channel"]
    assert channel_exits, "le repli progressif doit finir par casser le canal de sortie"


def test_max_position_fraction_never_exceeded():
    price_data = {
        "A": synthetic_dataframe(250, end_ms=FIXED_END_MS, drift=0.003, gbm_vol=0.004, momentum_rho=0.6, seed=1),
        "B": synthetic_dataframe(250, end_ms=FIXED_END_MS, drift=0.003, gbm_vol=0.004, momentum_rho=0.6, seed=2),
        "C": synthetic_dataframe(250, end_ms=FIXED_END_MS, drift=0.003, gbm_vol=0.004, momentum_rho=0.6, seed=3),
    }
    cfg = _light_cfg(risk_per_trade=0.5, max_position_fraction=1.0)  # risk_per_trade volontairement agressif
    result = run_donchian_backtest(price_data, cfg)

    total_exposure = result.weights_history.sum(axis=1)
    assert (total_exposure <= 1.0 + 1e-3).all(), "l'exposition totale ne doit jamais depasser max_position_fraction"


def test_circuit_breaker_forces_flat_and_liquidates_open_trade():
    # Le stop ATR (tres eloigne) et le canal de sortie (tres large, 30
    # jours) sont deliberement neutralises pour isoler le coupe-circuit :
    # avec une position a poids plein (risk_per_trade agressif, plafonne a
    # max_position_fraction=1.0) et un krach de -20% en un seul jour, ni le
    # stop ni le canal (qui, sur une tendance haussiere de 80 jours, reste
    # tres en-dessous meme apres -20%) ne se declenchent - seul le
    # coupe-circuit de drawdown peut forcer la liquidation ici.
    n_up = 80
    up = 100 * (1.01 ** np.arange(n_up))
    crash_day = up[-1] * 0.8  # -20% en un seul jour
    close = np.concatenate([up, [crash_day], [crash_day] * 4])
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    index = pd.date_range("2023-01-01", periods=len(close), freq="D", tz="UTC")
    price_data = {
        "X": pd.DataFrame(
            {"open": open_, "high": close * 1.001, "low": close * 0.999, "close": close}, index=index
        )
    }

    cfg = _light_cfg(
        entry_window=10, trend_ma_window=20, exit_window=30, atr_period=10,
        halt_drawdown=0.15, resume_drawdown=0.05, circuit_breaker_cooldown=5,
        atr_stop_multiple=50.0, risk_per_trade=10.0, max_position_fraction=1.0,
    )
    result = run_donchian_backtest(price_data, cfg)

    coupe_circuit_exits = [t for t in result.closed_trades if t.exit_reason == "coupe-circuit"]
    assert coupe_circuit_exits, "le krach doit finir par forcer une liquidation via le coupe-circuit"
    assert not result.trading_allowed_history.all(), "le krach doit declencher le coupe-circuit a un moment donne"
    assert not result.weights_history.iloc[-1].gt(0).any(), "le coupe-circuit doit finir par forcer la liquidation"


def test_missing_open_column_raises():
    price_data = {
        "X": pd.DataFrame(
            {"high": [1.0] * 50, "low": [1.0] * 50, "close": [1.0] * 50},
            index=pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC"),
        )
    }
    with pytest.raises(ValueError, match="open"):
        run_donchian_backtest(price_data, DonchianConfig())


def test_missing_high_low_columns_raises():
    price_data = {
        "X": pd.DataFrame(
            {"open": [1.0] * 50, "close": [1.0] * 50},
            index=pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC"),
        )
    }
    with pytest.raises(ValueError, match="high.*low"):
        run_donchian_backtest(price_data, DonchianConfig())
