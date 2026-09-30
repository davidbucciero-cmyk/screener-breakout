"""Tests du moteur a trades discrets (stop/breakeven/trailing/session)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from crypto_quant.discrete_trading import DiscreteTradeConfig, _session_filter, run_discrete_trade_backtest
from crypto_quant.synthetic import synthetic_dataframe

FIXED_END_MS = 1_700_000_000_000


def _trending_universe():
    return {
        "TREND_UP": synthetic_dataframe(
            400, end_ms=FIXED_END_MS, drift=0.004, gbm_vol=0.004, momentum_rho=0.6, ou_theta=0.0, ou_sigma=0.0, seed=7
        ),
    }


def test_run_discrete_trade_backtest_basic_shape_and_no_nans():
    price_data = _trending_universe()
    result = run_discrete_trade_backtest(price_data, DiscreteTradeConfig())

    assert len(result.equity) > 0
    assert not result.equity.isna().any()
    assert list(result.weights_history.columns) == list(price_data.keys())
    assert not result.weights_history.isna().any().any()


def test_stop_loss_closes_trade_at_loss_on_sharp_drop():
    # Montee courte (warm-up + une entree), puis chute brutale qui casse le
    # stop ATR avant tout declenchement de breakeven.
    n_up = 200
    up = 100 * (1.01 ** np.arange(n_up))
    crash = up[-1] * np.linspace(1.0, 0.5, 10)
    close = np.concatenate([up, crash])
    high = close * 1.001
    low = close * 0.999
    low[n_up] = close[n_up - 1] * 0.5  # la bougie du krach casse tres bas, sous n'importe quel stop ATR raisonnable
    index = pd.date_range("2023-01-01", periods=len(close), freq="D", tz="UTC")
    price_data = {"X": pd.DataFrame({"close": close, "high": high, "low": low}, index=index)}

    cfg = DiscreteTradeConfig(
        ema_fast=5, ema_slow=20, ema_vol_window=20, hurst_window=20, hurst_max_lag=8, ou_window=20,
        atr_period=14, atr_stop_multiple=2.0,
    )
    result = run_discrete_trade_backtest(price_data, cfg)

    stop_exits = [t for t in result.closed_trades if t.exit_reason == "stop"]
    assert stop_exits, "le krach doit declencher au moins une sortie sur stop"
    assert all(t.exit_price < t.entry_price for t in stop_exits), "une sortie sur stop doit acter une perte"


def test_breakeven_and_trailing_prevent_loss_after_large_gain():
    # Montee forte et soutenue (largement au-dela du seuil de breakeven),
    # puis repli qui doit finir par toucher un stop suiveur REMONTE bien
    # au-dessus du prix d'entree du trade initial. ou_significance_t tres
    # eleve desactive la contribution OU au score (bruit realiste mais
    # faible, momentum_rho fort) pour eviter les allers-retours signal/
    # re-entree qui, sinon, entament frequemment un tout NOUVEAU trade a
    # chaque repli mineur - un phenomene reel (cf. etape 15, README) mais
    # qui n'a rien a voir avec la mecanique de breakeven/trailing testee
    # ici. On ne verifie pas que TOUTE sortie sur stop est gagnante (des
    # trades ouverts tardivement PENDANT le repli peuvent legitimement
    # perdre un peu), seulement qu'AU MOINS UNE capture le gros gain.
    n_up = 300
    up = synthetic_dataframe(n_up, timeframe="1d", drift=0.006, gbm_vol=0.002, momentum_rho=0.7, ou_theta=0.0, ou_sigma=0.0, seed=21)
    peak_close = up["close"].iloc[-1]
    n_down = 20
    pullback_close = peak_close * np.linspace(1.0, 0.85, n_down)  # repli de 15%, sous le sommet mais pas sous l'entree
    pullback_index = pd.date_range(up.index[-1] + pd.Timedelta(days=1), periods=n_down, freq="D", tz="UTC")
    pullback = pd.DataFrame(
        {"close": pullback_close, "high": pullback_close * 1.002, "low": pullback_close * 0.998},
        index=pullback_index,
    )
    close_df = pd.concat([up[["close", "high", "low"]], pullback])
    price_data = {"X": close_df}

    cfg = DiscreteTradeConfig(
        ema_fast=10, ema_slow=40, ema_vol_window=40, hurst_window=40, hurst_max_lag=8,
        ou_window=40, ou_significance_t=50.0,
        atr_period=14, atr_stop_multiple=2.0, breakeven_r_multiple=1.0, trailing_atr_multiple=2.0,
    )
    result = run_discrete_trade_backtest(price_data, cfg)

    stop_exits = [t for t in result.closed_trades if t.exit_reason == "stop"]
    assert stop_exits, "le repli doit finir par toucher le stop suiveur remonte"
    assert any(t.exit_price > t.entry_price * 1.03 for t in stop_exits), (
        "au moins une sortie sur stop doit capturer un gain substantiel (breakeven+trailing ayant fonctionne)"
    )


def test_max_position_fraction_never_exceeded():
    price_data = {
        "A": synthetic_dataframe(300, end_ms=FIXED_END_MS, drift=0.004, gbm_vol=0.004, momentum_rho=0.6, seed=1),
        "B": synthetic_dataframe(300, end_ms=FIXED_END_MS, drift=0.004, gbm_vol=0.004, momentum_rho=0.6, seed=2),
        "C": synthetic_dataframe(300, end_ms=FIXED_END_MS, drift=0.004, gbm_vol=0.004, momentum_rho=0.6, seed=3),
    }
    cfg = DiscreteTradeConfig(risk_per_trade=0.5, max_position_fraction=1.0)  # risk_per_trade volontairement agressif
    result = run_discrete_trade_backtest(price_data, cfg)

    total_exposure = result.weights_history.sum(axis=1)
    # Tolerance de 0.1% : le poids enregistre est mesure APRES les couts de
    # transaction de ce pas de temps (equity finale legerement inferieure a
    # la base utilisee pour dimensionner les entrees), un ecart residuel
    # attendu et non un depassement reel du plafond.
    assert (total_exposure <= 1.0 + 1e-3).all(), "l'exposition totale ne doit jamais depasser max_position_fraction"


def test_market_regime_overlay_force_closes_open_trade():
    # BTC monte d'abord (pour laisser ALT/USD entrer en position via son
    # propre signal), PUIS retourne nettement a la baisse : doit forcer la
    # fermeture de la position ALT/USD ouverte, meme si le signal d'ALT
    # reste haussier - meme comportement que l'overlay du backtester a
    # poids continus. (Un BTC baissier des le debut bloquerait simplement
    # toute entree, sans jamais tester la fermeture forcee d'une position
    # deja ouverte.) ALT/USD utilise un prix bruite (synthetic_dataframe) :
    # un prix deterministe sans bruit fausse ou_meanreversion_signal (cf.
    # test_breakeven_and_trailing_prevent_loss_after_large_gain) et
    # empeche toute entree stable, masquant l'effet de l'overlay teste ici.
    n_up, n_down = 120, 180
    n = n_up + n_down
    btc_up = 100 * np.exp(0.004 * np.arange(n_up))
    btc_down = btc_up[-1] * np.exp(-0.01 * np.arange(1, n_down + 1))
    btc = np.concatenate([btc_up, btc_down])
    index = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    alt = synthetic_dataframe(
        n, timeframe="1d", drift=0.004, gbm_vol=0.002, momentum_rho=0.7, ou_theta=0.0, ou_sigma=0.0,
        seed=33, end_ms=int(index[-1].timestamp() * 1000),
    )

    price_data = {
        "BTC/USD": pd.DataFrame({"close": btc, "high": btc * 1.001, "low": btc * 0.999}, index=index),
        "ALT/USD": alt[["close", "high", "low"]],
    }
    cfg = DiscreteTradeConfig(
        ema_fast=10, ema_slow=40, ema_vol_window=40, hurst_window=40, hurst_max_lag=8,
        ou_window=40, ou_significance_t=50.0,
        market_regime_symbol="BTC/USD", market_regime_fast=5, market_regime_slow=50,
    )
    result = run_discrete_trade_backtest(price_data, cfg)

    regime_exits = [t for t in result.closed_trades if t.symbol == "ALT/USD" and t.exit_reason == "regime"]
    assert regime_exits, "l'overlay de regime BTC doit forcer au moins une sortie sur ALT/USD malgre son signal haussier"


def test_session_filter_pure_function_window_and_wraparound():
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")

    normal = _session_filter(index, 12, 16)
    assert list(normal[normal].index.hour) == [12, 13, 14, 15]

    wraparound = _session_filter(index, 22, 2)
    assert set(wraparound[wraparound].index.hour) == {22, 23, 0, 1}

    disabled = _session_filter(index, None, None)
    assert disabled.all()


def test_session_filter_blocks_entries_outside_window_on_intraday_data():
    # Sur des donnees INTRADAY (horaires), le filtre de session a un effet
    # reel (contrairement aux bougies journalieres, cf. avertissement dans
    # discrete_trading.py) : avec une fenetre qui exclut la bougie du matin,
    # aucune entree ne doit s'y produire.
    n = 400
    close = 100 * np.exp(0.0006 * np.arange(n))
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    price_data = {"X": pd.DataFrame({"close": close, "high": close * 1.0005, "low": close * 0.9995}, index=index)}

    cfg_no_filter = DiscreteTradeConfig(
        ema_fast=5, ema_slow=20, ema_vol_window=20, hurst_window=20, hurst_max_lag=8, ou_window=20,
    )
    cfg_filtered = DiscreteTradeConfig(
        ema_fast=5, ema_slow=20, ema_vol_window=20, hurst_window=20, hurst_max_lag=8, ou_window=20,
        session_start_hour=12, session_end_hour=16,
    )

    result_no_filter = run_discrete_trade_backtest(price_data, cfg_no_filter)
    result_filtered = run_discrete_trade_backtest(price_data, cfg_filtered)

    entries_no_filter = [t.entry_date for t in result_no_filter.closed_trades]
    entries_filtered = [t.entry_date for t in result_filtered.closed_trades]
    assert any(pd.Timestamp(d).hour not in range(12, 16) for d in entries_no_filter), (
        "le test suppose des entrees hors fenetre sans filtre, pour que le contraste soit demonstratif"
    )
    assert all(12 <= pd.Timestamp(d).hour < 16 for d in entries_filtered), (
        "avec le filtre de session, toute entree doit tomber dans la fenetre autorisee"
    )


def test_trend_gate_source_adx_requires_high_low_columns():
    price_data = {"X": pd.DataFrame(
        {"close": 100 * np.exp(0.001 * np.arange(200))},
        index=pd.date_range("2024-01-01", periods=200, freq="D", tz="UTC"),
    )}
    with pytest.raises(ValueError, match="high.*low|trend_gate_source"):
        run_discrete_trade_backtest(price_data, DiscreteTradeConfig(trend_gate_source="adx"))


def test_unknown_market_regime_symbol_raises():
    price_data = _trending_universe()
    with pytest.raises(ValueError, match="market_regime_symbol"):
        run_discrete_trade_backtest(price_data, DiscreteTradeConfig(market_regime_symbol="DOES_NOT_EXIST"))
