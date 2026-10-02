import numpy as np
import pandas as pd

from bot.equities import score_strategies as ss


def _panel(n_dates=24, n=200, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range('2015-01-31', periods=n_dates, freq='ME')
    tick = [f'T{i}' for i in range(n)]
    rows = []
    for d in dates:
        for t in tick:
            rows.append({'date': d, 'ticker': t, **{c: rng.normal() for c, _ in sum(ss.THEMES.values(), [])}})
    return pd.DataFrame(rows), dates, tick


def test_notes_follow_direction():
    p, _, _ = _panel(n_dates=1, n=100)
    sc = ss.theme_scores(p)
    # faible volatilite = bonne note ; forte marge = bonne note
    assert sc['Calme'].corr(-p['B3_volatilite_12m'], method='spearman') > 0.999
    assert sc['Qualite'].corr(p['C1_marge_brute_sur_actifs'], method='spearman') > 0.999
    assert sc[list(ss.THEMES)].min().min() > 0 and sc[list(ss.THEMES)].max().max() <= 1


def test_missing_theme_is_neutral():
    p, _, _ = _panel(n_dates=1, n=50)
    p['C1_marge_brute_sur_actifs'] = np.nan
    assert (ss.theme_scores(p)['Qualite'] == 0.5).all()


def test_signal_is_captured_and_no_lookahead():
    p, dates, tick = _panel()
    # le mois suivant rapporte plus aux actions a forte marge : S1 et S2 doivent gagner
    fwd = pd.DataFrame(0.0, index=dates, columns=tick)
    for d, g in p.groupby('date'):
        fwd.loc[d, g['ticker']] = 0.02 * g['C1_marge_brute_sur_actifs'].to_numpy()
    res = ss.run_strategies(p, fwd)
    assert res['S1'].mean() > res['univ'].mean()
    assert res['S2'].mean() > 0
    # S4 ne change de liste qu'en fin de trimestre
    assert (res.loc[res.index.month % 3 != 0, 'to_S4'].iloc[1:] == 0).all()
