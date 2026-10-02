import numpy as np
import pandas as pd
import pytest

from bot.equities.model import RETAINED, backtest, yearly_weights


def _panel(n_months=120, n=200, seed=0, signal=0.0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range('2010-01-31', periods=n_months, freq='ME')
    rows = []
    for d in dates:
        f = rng.normal(size=(n, len(RETAINED)))
        fwd = signal * f[:, 0] * 0.01 + rng.normal(0, 0.05, n)
        for i in range(n):
            rows.append({'date': d, 'ticker': f'T{i}', 'fwd_ret': fwd[i], 'mcap': 5e9,
                         **{k: f[i, j] for j, k in enumerate(RETAINED)}})
    return pd.DataFrame(rows), pd.Series(rng.normal(0.0, 0.04, n_months), index=dates)  # SPY sans tendance, comme les actions synthetiques


def test_weights_for_a_year_only_use_returns_known_before_it():
    panel, _ = _panel(n_months=60)
    w1 = yearly_weights(panel)
    tampered = panel.copy()
    late = tampered['date'] >= '2013-01-01'
    tampered.loc[late, 'fwd_ret'] = tampered.loc[late, RETAINED[0]]  # signal parfait a partir de 2013
    w2 = yearly_weights(tampered)
    pd.testing.assert_frame_equal(w1.loc[:2013], w2.loc[:2013])  # les poids 2013 ignorent 2013
    assert w2.loc[2014, RETAINED[0]] > w1.loc[2014, RETAINED[0]]


def test_planted_signal_is_profitable_and_noise_is_not():
    p_sig, spy = _panel(signal=3.0)
    res = backtest(p_sig, spy)
    assert res['hedged'].loc['2013':].mean() > 0.005
    p_noise, spy = _panel(signal=0.0, seed=1)
    noise = backtest(p_noise, spy)['hedged'].loc['2013':]
    assert abs(noise.mean()) < 0.006


def test_turnover_costs_are_charged():
    p, spy = _panel(signal=0.0, seed=2)
    a = backtest(p, spy, cost_bps=0.0)['hedged']
    b = backtest(p, spy, cost_bps=50.0)['hedged']
    assert (a - b).loc['2013':].mean() > 0
