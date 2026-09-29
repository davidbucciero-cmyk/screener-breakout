import numpy as np
import pytest
import pandas as pd

from btc_forecast.trend import apply_band, run_trend, trend_signals, vol_target


def synthetic_daily(n=1500, seed=5):
    """Prix journaliers avec regimes de tendance (drift +/-) et vol variable, OHLC coherents."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.choice([-1, 1], size=n // 100 + 1), 100)[:n]
    vol = 0.03 * np.exp(0.4 * np.sin(np.arange(n) / 90))
    r = regime * 0.004 + vol * rng.normal(size=n)
    close = 20000 * np.exp(np.cumsum(r))
    open_ = np.r_[20000, close[:-1]]
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, vol / 2)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, vol / 2)))
    idx = pd.date_range('2019-01-01', periods=n, freq='D', tz='UTC')
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close}, index=idx)


def test_signals_use_only_past():
    close = synthetic_daily()['close']
    sig = trend_signals(close)
    altered = close.copy()
    altered.iloc[1000:] *= 0.5
    sig2 = trend_signals(altered)
    pd.testing.assert_frame_equal(sig.iloc[:1000], sig2.iloc[:1000])
    assert set(sig['ensemble'].dropna().unique()) <= {0, 0.25, 0.5, 0.75, 1}


def test_vol_target_and_band():
    s = pd.Series([1.0, 1.0, 1.0, 0.0])
    v = pd.Series([0.2, 0.8, 0.4, 0.4])
    assert vol_target(s, v, target=0.4).tolist() == [1.0, 0.5, 1.0, 0.0]  # plafonne a 1
    pos = apply_band(pd.Series([0.5, 0.55, 0.7, 0.72, 0.0, np.nan]), band=0.1)
    assert pos.tolist() == [0.5, 0.5, 0.7, 0.7, 0.0, 0.0]


def test_run_trend_no_lookahead_and_sane():
    df = synthetic_daily()
    perf, curves, yearly, enkf, vols, positions = run_trend(df)
    altered = df.copy()
    altered.iloc[1200:] *= 1.5
    _, curves2, _, _, _, _ = run_trend(altered)
    # Rendements des strategies jusqu'a t=1198 (tenus de t a t+1 <= 1199) : identiques.
    cut = df.index[1198]
    pd.testing.assert_frame_equal(curves.loc[:cut], curves2.loc[:cut])

    p = perf.set_index('strategie')
    assert p.loc['Buy & hold', 'exposition_moyenne'] == 1.0
    assert (p['exposition_moyenne'] <= 1.0 + 1e-9).all()
    # Regimes de tendance persistants : le trend doit reduire la pire perte vs buy & hold.
    assert p.loc['Trend ensemble (sans ciblage)', 'max_drawdown'] > p.loc['Buy & hold', 'max_drawdown']
    assert list(yearly.columns) == list(curves.columns)


def test_portfolio_equal_sleeves():
    from btc_forecast.trend import run_portfolio
    dfs = {'AAA': synthetic_daily(1200, seed=1), 'BBB': synthetic_daily(1000, seed=2).iloc[:]}
    dfs['BBB'].index = dfs['AAA'].index[200:]  # BBB commence 200 jours plus tard
    perf, curves, yearly, corr = run_portfolio(dfs)
    p = perf.set_index('strategie')
    # Fenetre commune : demarre apres le warm-up de la crypto la plus recente.
    assert curves.index[0] > dfs['BBB'].index[0]
    # Portefeuille = moyenne des poches (sans re-equilibrage) : valeur finale = moyenne des valeurs finales.
    strat = 'Trend ensemble + ciblage vol 30j'
    port = (1 + curves[f'Portefeuille {strat}']).prod()
    alone = [(1 + curves[f'{s} seul - {strat}']).prod() for s in dfs]
    assert port == pytest.approx(sum(alone) / 2, rel=1e-9)
    assert set(corr) == {'Buy & hold', 'Trend ensemble (sans ciblage)', strat}
    assert (p['exposition_moyenne'] <= 1 + 1e-9).all()
