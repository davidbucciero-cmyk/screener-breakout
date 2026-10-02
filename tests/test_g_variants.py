import numpy as np
import pandas as pd

from bot.g_variants import VARIANTS, btc_below_sma200
from tests.test_bot_multi import _dfs


def test_late_listed_asset_is_never_held_before_listing():
    dfs = _dfs(n=24 * 500)
    sol = dfs['SOLUSDT'].copy()
    sol.iloc[: 24 * 300] = np.nan  # SOL cotee seulement apres 300 jours
    dfs['SOLUSDT'] = sol
    for name, fn in VARIANTS.items():
        _, _, w = fn(dfs)
        assert (w['SOLUSDT'].iloc[: 24 * 300] == 0).all(), name
        assert (w.sum(axis=1) <= 1 + 1e-9).all(), name


def test_btc_filter_ignores_future():
    dfs = _dfs(n=24 * 500)
    a = btc_below_sma200(dfs)
    t = {k: v.copy() for k, v in dfs.items()}
    t['BTCUSDT'].iloc[24 * 450:] *= 0.1
    b = btc_below_sma200(t)
    cut = t['BTCUSDT'].index[24 * 450].floor('D')
    pd.testing.assert_series_equal(a[a.index < cut], b[b.index < cut])
    assert b.iloc[-1]


def test_variants_ignore_future():
    dfs = _dfs(n=24 * 500)
    t = {k: v.copy() for k, v in dfs.items()}
    cut = 24 * 450
    for d in t.values():
        d.iloc[cut:] *= 3
    for name, fn in VARIANTS.items():
        r1, r2 = fn(dfs)[0], fn(t)[0]
        pd.testing.assert_series_equal(r1.iloc[:cut], r2.iloc[:cut], obj=name)
