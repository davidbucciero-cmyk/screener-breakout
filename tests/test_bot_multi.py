import numpy as np
import pandas as pd
import pytest

from bot.multi import diversified_trend, rotation_momentum


def _dfs(n=24 * 400, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2023-01-01', periods=n, freq='h', tz='UTC')
    out = {}
    for k, s in enumerate(('BTCUSDT', 'ETHUSDT', 'SOLUSDT')):
        c = pd.Series(100 * (k + 1) * np.exp(np.cumsum(rng.normal(0.0001, 0.006 + 0.002 * k, n))), index=idx)
        out[s] = pd.DataFrame({'open': c, 'high': c, 'low': c, 'close': c, 'volume': 1.0})
    return out


@pytest.mark.parametrize('fn', [rotation_momentum, diversified_trend])
def test_multi_asset_ignores_future_and_stays_unlevered(fn):
    dfs = _dfs()
    r1, t1, w1 = fn(dfs)
    n = len(r1)
    cut = n - 24 * 30
    tampered = {s: d.copy() for s, d in dfs.items()}
    for d in tampered.values():
        d.iloc[cut:] *= 4
    r2, _, _ = fn(tampered)
    pd.testing.assert_series_equal(r1.iloc[:cut], r2.iloc[:cut])
    assert (w1.sum(axis=1) <= 1 + 1e-9).all() and (w1 >= 0).all().all()
    assert {'entry_time', 'pnl'} <= set(t1.columns)


def test_rotation_holds_at_most_one_asset():
    _, _, w = rotation_momentum(_dfs())
    assert ((w > 0).sum(axis=1) <= 1).all()


def test_top3_holds_at_most_three_and_funding_forces_cash():
    from bot.funding import crowded_longs
    from bot.multi import rotation_momentum
    dfs = _dfs()
    _, _, w = rotation_momentum(dfs, top_k=3)
    assert ((w > 0).sum(axis=1) <= 3).all() and (w.sum(axis=1) <= 1 + 1e-9).all()
    days = w.index.floor('D').unique()
    risk_off = pd.Series(True, index=days)
    _, _, w_off = rotation_momentum(dfs, risk_off=risk_off)
    assert (w_off == 0).all().all()


def test_crowded_longs_ignores_future():
    from bot.funding import crowded_longs
    rng = np.random.default_rng(0)
    idx = pd.date_range('2022-01-01', periods=3 * 800, freq='8h', tz='UTC')
    f = pd.Series(rng.normal(0.0001, 0.0001, len(idx)), index=idx)
    a = crowded_longs(f)
    f2 = f.copy()
    f2.iloc[-300:] = 0.01
    b = crowded_longs(f2)
    cut = f.index[-300].floor('D')
    pd.testing.assert_series_equal(a[a.index < cut], b[b.index < cut])
    assert b.loc[cut + pd.Timedelta(days=10)]  # pic de funding detecte des qu'il apparait


def test_blend_averages_returns():
    from bot.multi import blend
    idx = pd.date_range('2024-01-01', periods=3, freq='h', tz='UTC')
    t = pd.DataFrame({'entry_time': [], 'pnl': []})
    r, _ = blend((pd.Series([0.01, 0.0, 0.02], index=idx), t), (pd.Series([0.03, 0.0, 0.0], index=idx), t))
    assert list(r.round(4)) == [0.02, 0.0, 0.01]


def test_report_runs_g_and_h_on_three_coins_only(monkeypatch):
    import bot.run_backtest as rb
    seen = []
    monkeypatch.setattr(rb, 'MULTI', {'G - x': lambda d: (seen.append(sorted(d)), (pd.Series(0.0, index=d['BTCUSDT'].index),
                                                         pd.DataFrame({'entry_time': [], 'pnl': []}), None))[1]})
    monkeypatch.setattr(rb, 'blend', lambda *a: a[0])
    from tests.test_bot_state import _candles
    from bot.multi import UNIVERSE
    n = 24 * 365 * 3
    others = {s: _candles(n=n, seed=20 + i) for i, s in enumerate(UNIVERSE) if s != 'BTCUSDT'}
    results = {}
    monkeypatch.setitem(rb.__dict__, 'run_strategies', lambda df: results)
    try:
        rb.build_report(_candles(n=n), others=others)
    except KeyError:
        pass  # le panier K attend les vraies strategies ; seul l'univers passe a G nous interesse ici
    assert seen == [['BTCUSDT', 'ETHUSDT', 'SOLUSDT']]
