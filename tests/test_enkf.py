import numpy as np
import pandas as pd

from btc_forecast.backtest import evaluate, evaluate_volatility
from btc_forecast.enkf import EnKFConfig, enkf_positions, run_enkf


def synthetic_ohlc(n=2500, seed=3, substeps=12):
    """Bougies 1h a volatilite stochastique (regimes calmes / agites), high/low issus de sous-pas."""
    rng = np.random.default_rng(seed)
    h = np.empty(n)
    h[0] = np.log(0.006 ** 2)
    for i in range(1, n):
        h[i] = np.log(0.006 ** 2) + 0.98 * (h[i - 1] - np.log(0.006 ** 2)) + 0.12 * rng.normal()
    sub = rng.normal(0, 1, (n, substeps)) * np.exp(h / 2)[:, None] / np.sqrt(substeps)
    path = 30000 * np.exp(np.cumsum(sub.ravel())).reshape(n, substeps)
    close = path[:, -1]
    open_ = np.r_[30000, close[:-1]]
    high = np.maximum(path.max(axis=1), open_)
    low = np.minimum(path.min(axis=1), open_)
    idx = pd.date_range('2025-01-01', periods=n, freq='h', tz='UTC')
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close}, index=idx)


def test_enkf_no_lookahead():
    df = synthetic_ohlc(1200)
    cfg = EnKFConfig(n_members=50, calib_hours=240)
    base = run_enkf(df, cfg)
    altered = df.copy()
    altered.iloc[1000:, :] *= 1.3  # on modifie le futur
    alt = run_enkf(altered, cfg)
    cols = ['p_up', 'var_forecast', 'signal']
    # Previsions faites avant t=1000 (cible <= 999) : identiques.
    pd.testing.assert_frame_equal(base.loc[:df.index[998], cols], alt.loc[:df.index[998], cols])
    assert not np.allclose(base.loc[df.index[1000]:, 'var_forecast'], alt.loc[df.index[1000]:, 'var_forecast'])


def test_enkf_outputs_and_volatility_skill():
    df = synthetic_ohlc()
    preds = run_enkf(df, EnKFConfig(n_members=100))
    assert preds.index[-1] == df.index[-2]
    assert preds['p_up'].between(0, 1).all()
    pos = enkf_positions(preds)
    assert np.all(np.abs(pos) <= 1)
    flat = enkf_positions(preds, max_h_spread=preds['h_spread'].expanding(24).median())
    assert (flat == 0).sum() > (pos == 0).sum()

    vol = evaluate_volatility(preds, df['close'].pct_change() ** 2).set_index('prevision_variance')
    # Sur une vol a regimes persistants, l'EnKF doit battre la variance realisee 30 j.
    assert vol.loc['Modele', 'qlike'] < vol.loc['Variance realisee 720h', 'qlike']
    assert vol.loc['Modele', 'correlation_vol_prevue_vs_abs_rendement'] > 0.2

    calib, perf, _, curves = evaluate(preds, label='EnKF', extra_positions={'EnKF sizing': pos})
    assert 'EnKF sizing' in set(perf['strategie']) and 'EnKF sizing' in curves
