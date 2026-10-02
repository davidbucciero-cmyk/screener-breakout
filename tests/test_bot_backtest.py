import numpy as np
import pandas as pd
import pytest

from bot.backtest import GATE, gate, metrics
from bot.strategies import COST, simulate_trades, trend_positions


def _flat(n=10, price=100.0):
    idx = pd.date_range('2024-01-01', periods=n, freq='h', tz='UTC')
    return pd.DataFrame({'open': price, 'high': price, 'low': price, 'close': price, 'volume': 1.0}, index=idx)


def test_round_trip_on_flat_price_costs_two_sides():
    df = _flat()
    entries = pd.Series(False, index=df.index + pd.Timedelta(hours=1))
    entries.iloc[2] = True  # decision a la cloture de la bougie 2
    r, trades = simulate_trades(df, entries, stop_pct=pd.Series(0.05, index=entries.index),
                                target_pct=pd.Series(0.05, index=entries.index), max_hours=3)
    assert len(trades) == 1
    assert trades.iloc[0]['pnl'] == pytest.approx((1 - COST) ** 2 - 1)
    assert (1 + r).prod() - 1 == pytest.approx((1 - COST) ** 2 - 1)
    assert trades.iloc[0]['hours'] == 3


def test_stop_exits_at_stop_price_even_if_target_hit_same_candle():
    df = _flat()
    df.iloc[4, df.columns.get_loc('low')] = 90.0
    df.iloc[4, df.columns.get_loc('high')] = 120.0
    entries = pd.Series(False, index=df.index + pd.Timedelta(hours=1))
    entries.iloc[2] = True
    _, trades = simulate_trades(df, entries, stop_pct=pd.Series(0.05, index=entries.index),
                                target_pct=pd.Series(0.10, index=entries.index), max_hours=24)
    t = trades.iloc[0]
    assert t['exit_price'] == pytest.approx(95.0)  # pire cas : stop avant objectif
    assert t['reason'] == 'stop'


def test_gap_below_stop_fills_at_open():
    df = _flat()
    df.iloc[4, [df.columns.get_loc(c) for c in ('open', 'low', 'close')]] = [80.0, 79.0, 81.0]
    entries = pd.Series(False, index=df.index + pd.Timedelta(hours=1))
    entries.iloc[2] = True
    _, trades = simulate_trades(df, entries, stop_pct=pd.Series(0.05, index=entries.index),
                                target_pct=pd.Series(0.10, index=entries.index), max_hours=24)
    assert trades.iloc[0]['exit_price'] == pytest.approx(80.0)


def test_trend_positions_ignore_future():
    rng = np.random.default_rng(1)
    n = 24 * 400
    idx = pd.date_range('2023-01-01', periods=n, freq='h', tz='UTC')
    close = pd.Series(20000 * np.exp(np.cumsum(rng.normal(0.0001, 0.005, n))), index=idx)
    df = pd.DataFrame({'open': close, 'high': close, 'low': close, 'close': close, 'volume': 1.0})
    pos, _ = trend_positions(df)
    cut = n - 24 * 30
    tampered = df.copy()
    tampered.iloc[cut:] *= 5
    pos2, _ = trend_positions(tampered)
    pd.testing.assert_series_equal(pos.iloc[:cut], pos2.iloc[:cut])
    assert pos.between(0, 1).all()


def test_metrics_and_gate():
    idx = pd.date_range('2024-01-01', periods=24 * 730, freq='h', tz='UTC')
    r = pd.Series(0.0, index=idx)
    r.iloc[::24] = 0.002  # gain regulier, aucune perte
    r.iloc[12::48] = -0.001
    trades = pd.DataFrame({'pnl': [0.01, 0.02, -0.005]})
    m = metrics(r, trades)
    assert m['hit_rate'] == pytest.approx(2 / 3)
    assert m['max_drawdown'] > -0.01
    assert m['sharpe'] > 1.5 and m['t_stat'] > 2.0
    g = gate(m)
    assert g['passed'] is True
    m_bad = dict(m, max_drawdown=-0.2)
    assert gate(m_bad)['passed'] is False
    assert set(GATE) <= set(g)


def _random_df(n=24 * 500, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2023-01-01', periods=n, freq='h', tz='UTC')
    close = pd.Series(20000 * np.exp(np.cumsum(rng.normal(0.00005, 0.006, n))), index=idx)
    return pd.DataFrame({'open': close.shift(1).fillna(close.iloc[0]), 'high': close * 1.002,
                         'low': close * 0.998, 'close': close, 'volume': 1.0})


@pytest.mark.parametrize('name', ['D', 'E', 'F'])
def test_new_strategies_ignore_future(name):
    from bot.strategies import NEW_STRATEGIES
    df = _random_df()
    cut = len(df) - 24 * 40
    tampered = df.copy()
    tampered.iloc[cut:] *= 3
    r1, _ = NEW_STRATEGIES[name](df)
    r2, _ = NEW_STRATEGIES[name](tampered)
    # Le rendement de la bougie `cut` elle-meme change (prix falsifie) ; tout ce qui precede doit etre identique.
    pd.testing.assert_series_equal(r1.iloc[:cut], r2.iloc[:cut])


def test_rsi2_extremes():
    from bot.strategies import rsi
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert rsi(up, 2).iloc[-1] == pytest.approx(100.0)
    assert rsi(-up + 100, 2).iloc[-1] == pytest.approx(0.0)


def test_gate_tightens_t_stat_with_number_of_tests():
    from bot.backtest import t_threshold
    assert t_threshold(1) == pytest.approx(2.0, abs=0.05)
    assert t_threshold(6) > t_threshold(3) > 2.0
