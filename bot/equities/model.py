"""Modele combine actions US : score = somme ponderee des rangs des 7 blocs retenus en dev.

Poids d'une annee Y = IC mensuel moyen de chaque feature, mesure uniquement sur les mois dont le rendement
cible se termine avant le 1er janvier de Y (fenetre croissante). Les signes sont donc appris, pas imposes.
Portefeuille : chaque fin de mois, les 10 % d'actions au meilleur score, a poids egal, couvertes par une
vente de SPY du meme montant.
"""
import math

import numpy as np
import pandas as pd

RETAINED = ['C2_variation_actions_1an', 'C1_marge_brute_sur_actifs', 'B3_volatilite_12m',
            'B2_proximite_plus_haut_52s', 'B1_momentum_12_1', 'C6_accruals', 'A6_sma50_sup_sma200']
MIN_MONTHS = 24          # historique minimal avant d'utiliser des poids
TOP = 0.10
COST_BPS = 10.0          # par cote, actions
SPY_COST_BPS = 2.0       # par cote, SPY
BORROW = 0.005           # cout annuel de la vente a decouvert de SPY


def _ranks(panel):
    """Rang centre (-0.5..0.5) de chaque feature dans chaque mois ; manquant = neutre (0)."""
    r = panel.groupby('date')[RETAINED].rank(pct=True) - 0.5
    return r.fillna(0.0)


def monthly_ics(panel):
    p = panel.dropna(subset=['fwd_ret'])
    ranks = _ranks(p)
    fwd = p.groupby('date')['fwd_ret'].rank(pct=True) - 0.5
    df = ranks.assign(_fwd=fwd, date=p['date'])
    return df.groupby('date').apply(lambda g: g[RETAINED].corrwith(g['_fwd']), include_groups=False)


def yearly_weights(panel):
    ics = monthly_ics(panel)
    known = ics.index + pd.offsets.MonthEnd(1)  # date de fin du rendement mesure
    years = range(ics.index.year.min(), ics.index.year.max() + 2)
    rows = {}
    for y in years:
        past = ics[known < pd.Timestamp(f'{y}-01-01')]
        rows[y] = past.mean() if len(past) >= MIN_MONTHS else pd.Series(np.nan, index=RETAINED)
    return pd.DataFrame(rows).T


def backtest(panel, spy_monthly, cost_bps=COST_BPS):
    """Rendements mensuels : jambe longue, couverte (long - SPY), et SPY ; plus statistiques de detention."""
    w = yearly_weights(panel)
    ranks = _ranks(panel)
    p = panel[['date', 'ticker', 'fwd_ret']].copy()
    out, prev, hits, held = [], set(), [], []
    for d, g in p.groupby('date'):
        wy = w.loc[d.year] if d.year in w.index else None
        if wy is None or wy.isna().all():
            continue
        score = ranks.loc[g.index].mul(wy, axis=1).sum(axis=1)
        k = max(1, int(len(g) * TOP))
        top = g.loc[score.nlargest(k).index]
        r_long = top['fwd_ret'].fillna(0.0).mean()  # sans prix le mois suivant : compte a 0, signale a part
        names = set(top['ticker'])
        turnover = 1.0 if not prev else len(names - prev) / len(names)
        prev = names
        spy = spy_monthly.get(d + pd.offsets.MonthEnd(0), np.nan)
        cost = 2 * turnover * cost_bps / 1e4
        hedged = r_long - spy - cost - 2 * SPY_COST_BPS / 1e4 * turnover - BORROW / 12
        out.append({'date': d, 'long': r_long - cost, 'hedged': hedged, 'spy': spy,
                    'turnover': turnover, 'sans_prix': int(top['fwd_ret'].isna().sum())})
        hits.append(float((top['fwd_ret'] > spy).mean()))
        held.append(len(top))
    res = pd.DataFrame(out).set_index('date').dropna(subset=['spy'])
    res['hit_positions'] = pd.Series(hits, index=pd.DatetimeIndex([o['date'] for o in out])).reindex(res.index)
    res['positions'] = pd.Series(held, index=pd.DatetimeIndex([o['date'] for o in out])).reindex(res.index)
    return res


def stats(r, hit=None):
    r = r.dropna()
    eq = (1 + r).cumprod()
    sd = r.std()
    return {'mois': len(r), 'rendement_annuel': float(eq.iloc[-1] ** (12 / len(r)) - 1),
            'sharpe': float(r.mean() / sd * math.sqrt(12)) if sd > 0 else float('nan'),
            't_stat': float(r.mean() / sd * math.sqrt(len(r))) if sd > 0 else float('nan'),
            'max_drawdown': float((eq / eq.cummax() - 1).min()),
            'mois_positifs': float((r > 0).mean()),
            'hit_rate': float(hit.mean()) if hit is not None else float('nan')}
