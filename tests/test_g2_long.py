import numpy as np
import pandas as pd

from bot.multi import rotation_momentum
from bot.run_g2_long import as_frame, build_report, parse_prices


def test_parse_coinmetrics_prices():
    rows = [{'time': '2015-10-02T00:00:00.000000000Z', 'PriceUSD': '237.5'},
            {'time': '2015-10-01T00:00:00.000000000Z', 'PriceUSD': '236.1'}, {'time': '2015-10-03T00:00:00Z'}]
    s = parse_prices(rows)
    assert list(s) == [236.1, 237.5] and str(s.index.tz) == 'UTC'


def test_daily_bars_apply_decision_to_next_day_only():
    idx = pd.date_range('2015-01-01', periods=400, freq='D', tz='UTC')
    up = pd.Series(np.linspace(100, 300, 400), index=idx)
    flat = pd.Series(100.0, index=idx)
    dfs = {'BTCUSDT': as_frame(up), 'ETHUSDT': as_frame(flat)}
    _, _, w = rotation_momentum(dfs)
    t = {k: v.copy() for k, v in dfs.items()}
    t['BTCUSDT'].iloc[350:] *= 0.5  # chute le jour 350
    r1, r2 = rotation_momentum(dfs)[0], rotation_momentum(t)[0]
    pd.testing.assert_series_equal(r1.iloc[:350], r2.iloc[:350])
    assert r2.iloc[350] < r1.iloc[350]  # la chute du jour 350 frappe la position decidee la veille


def test_report_renders():
    rng = np.random.default_rng(0)
    def mk(start):
        idx = pd.date_range(start, '2026-09-30', freq='D', tz='UTC')
        return as_frame(pd.Series(100 * np.exp(np.cumsum(rng.normal(0.001, 0.04, len(idx)))), index=idx))
    text = build_report({'BTCUSDT': mk('2010-07-18'), 'ETHUSDT': mk('2015-08-08'), 'SOLUSDT': mk('2020-04-10')})
    assert 'Oct. 2015 -> mars 2018' in text and 'Gate revise' in text
