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
