"""Strategies actions US a partir d'un score par themes (regles fixees AVANT de voir les resultats).

Score (chaque fin de mois, actions de l'univers > 2 Md$) :
  - chaque critere est converti en rang de 0 a 1 parmi les actions du mois (1 = le meilleur) ;
  - les criteres d'un meme theme sont moyennes ; un theme sans donnee vaut 0,5 (neutre) ;
  - score = moyenne des themes, poids egaux.
  Themes : Qualite (marge brute / actifs), Rachats (baisse du nombre d'actions),
           Tendance (momentum 12-1, proximite du plus haut 52 s, SMA50 > SMA200), Calme (faible volatilite 12 m).
  C6 (accruals) est exclu : son signe mesure contredit la litterature, non explique.

Strategies (frais 10 bps par cote sur la rotation) :
  S1 Top 50       : 50 meilleurs scores, poids egal, revu chaque mois.
  S2 Long-short   : 10 % meilleurs achetes, 10 % pires vendus, meme montant ; emprunt 1 %/an sur la jambe vendeuse.
  S4 Solides      : 30 meilleurs sur Qualite + Rachats + Calme, liste revue chaque trimestre.
  S1/S4 + vol     : exposition = min(1, vol mediane passee du SPY / vol du SPY sur 21 j) ; le reste en cash a 0 %.
References : SPY (S&P 500) et RSP (S&P 500 a poids egal).
Une action sans prix le mois suivant compte pour 0 % (comme dans le modele de BOT 2) ; leur nombre est publie.
"""
import logging
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

from bot.equities.features import build_panel, month_ends
from bot.equities.run import CACHE, load

log = logging.getLogger(__name__)
REPORT = Path(__file__).parent.parent / 'reports' / 'equities_strategies.md'

THEMES = {
    'Qualite': [('C1_marge_brute_sur_actifs', 1)],
    'Rachats': [('C2_variation_actions_1an', -1)],
    'Tendance': [('B1_momentum_12_1', 1), ('B2_proximite_plus_haut_52s', 1), ('A6_sma50_sup_sma200', 1)],
    'Calme': [('B3_volatilite_12m', -1)],
}
DEFENSIVE = ['Qualite', 'Rachats', 'Calme']
COST = 10e-4        # par cote
BORROW = 0.01       # par an, jambe vendeuse
EXPO_COST = 2e-4    # par unite d'exposition changee (overlay de vol)
DEV_END, OOS_START = '2018-12-31', '2019-01-01'
EXAMPLES = ['NVDA', 'AAPL', 'TSLA']


def theme_scores(panel):
    """Note de 0 a 1 par theme, et scores combines, pour chaque (date, action)."""
    g = panel.groupby('date')
    out = pd.DataFrame(index=panel.index)
    for theme, crits in THEMES.items():
        notes = []
        for col, sign in crits:
            r = g[col].rank(pct=True)
            notes.append(r if sign > 0 else 1 - r + 1 / g[col].transform('count'))
        out[theme] = pd.concat(notes, axis=1).mean(axis=1).fillna(0.5)
    out['score'] = out[list(THEMES)].mean(axis=1)
    out['score_def'] = out[DEFENSIVE].mean(axis=1)
    return out


def forward_returns(close, dates):
    """Rendement du mois suivant pour TOUTES les actions (y compris sorties de l'univers)."""
    m = close.loc[dates]
    return m.shift(-1) / m - 1


def _turnover(new, old):
    if not old:
        return 1.0
    return len(set(new) - set(old)) / len(new)


def ticker_history(panel, sc, close, ticker):
    """Notes d'une action chaque fin d'annee (et au dernier mois), rang et selection, rendement 12 mois suivant."""
    p = panel[['date', 'ticker']].join(sc)
    p['rang'] = p.groupby('date')['score'].rank(ascending=False)
    p['rang_def'] = p.groupby('date')['score_def'].rank(ascending=False)
    p['n'] = p.groupby('date')['ticker'].transform('size')
    h = p[p['ticker'] == ticker].set_index('date').sort_index()
    if h.empty:
        return h
    keep = h.groupby(h.index.year).tail(1)
    if ticker in close.columns:
        c = close[ticker]
        c = c.dropna()
        keep['rdt_12m_suivants'] = [c.asof(d + pd.DateOffset(years=1)) / c.asof(d) - 1
                                    if d + pd.DateOffset(years=1) <= c.index[-1] else np.nan for d in keep.index]
    return keep


def run_strategies(panel, fwd, rebal_every=None):
    rebal_every = rebal_every or {}
    sc = theme_scores(panel)
    p = panel[['date', 'ticker']].join(sc)
    rows, prev = [], {'S1': [], 'S2L': [], 'S2S': [], 'S4': []}
    for i, (d, g) in enumerate(p.groupby('date')):
        if d not in fwd.index:
            continue
        r = fwd.loc[d]
        k10 = max(1, int(len(g) * 0.10))
        picks = {
            'S1': g.nlargest(50, 'score')['ticker'].tolist(),
            'S2L': g.nlargest(k10, 'score')['ticker'].tolist(),
            'S2S': g.nsmallest(k10, 'score')['ticker'].tolist(),
            'S4': g.nlargest(30, 'score_def')['ticker'].tolist() if (d.month % 3 == 0 or not prev['S4'])
            else prev['S4'],
        }
        ret, miss = {}, 0
        for k, names in picks.items():
            x = r.reindex(names)
            miss += int(x.isna().sum())
            ret[k] = x.fillna(0.0).mean()
        to = {k: _turnover(picks[k], prev[k]) for k in picks}
        row = {
            'date': d,
            'S1': ret['S1'] - 2 * COST * to['S1'],
            'S2': ret['S2L'] - ret['S2S'] - 2 * COST * (to['S2L'] + to['S2S']) - BORROW / 12,
            'S4': ret['S4'] - 2 * COST * to['S4'],
            'univ': r.reindex(g['ticker']).mean(),
            'sans_prix': miss, 'n_univ': len(g),
            'to_S1': to['S1'], 'to_S2': (to['S2L'] + to['S2S']) / 2, 'to_S4': to['S4'],
        }
        rows.append(row)
        prev = picks
    res = pd.DataFrame(rows).set_index('date')
    res.index = res.index + pd.offsets.MonthEnd(0)
    return res


def etf(symbol):
    path = CACHE / f'{symbol.lower()}.parquet'
    if path.exists():
        return pd.read_parquet(path)['close']
    import yfinance as yf
    c = yf.download(symbol, start='2008-06-01', auto_adjust=True, progress=False)['Close'].squeeze()
    c.index = pd.DatetimeIndex(c.index).tz_localize(None)
    CACHE.mkdir(exist_ok=True)
    c.to_frame('close').to_parquet(path)
    return c


def etf_monthly(close):
    m = close.loc[month_ends(close.index)]
    fwd = m.shift(-1) / m - 1
    return pd.Series(fwd.to_numpy(), index=m.index + pd.offsets.MonthEnd(0))


def vol_exposure(spy_close):
    """Exposition a chaque fin de mois : vol mediane passee / vol 21 j, plafonnee a 1."""
    v = spy_close.pct_change().rolling(21).std() * math.sqrt(252)
    me = month_ends(v.index)
    vm = v.loc[me]
    target = vm.expanding(min_periods=12).median()
    expo = (target / vm).clip(upper=1.0)
    return pd.Series(expo.to_numpy(), index=me + pd.offsets.MonthEnd(0))


def add_overlay(res, expo):
    e = expo.reindex(res.index).fillna(1.0)
    chg = e.diff().abs().fillna(0.0)
    for k in ('S1', 'S4'):
        res[f'{k} + vol'] = e * res[k] - EXPO_COST * chg
    res['expo'] = e
    return res


def stats(r, spy, rsp):
    df = pd.concat({'r': r, 'spy': spy, 'rsp': rsp}, axis=1).dropna()
    r = df['r']
    if len(r) < 12:
        return None
    eq = (1 + r).cumprod()
    ex = df['r'] - df['rsp']
    return {
        'mois': len(r),
        'cagr': eq.iloc[-1] ** (12 / len(r)) - 1,
        'vol': r.std() * math.sqrt(12),
        'sharpe': r.mean() / r.std() * math.sqrt(12),
        'maxdd': (eq / eq.cummax() - 1).min(),
        'beta': np.cov(r, df['spy'])[0, 1] / df['spy'].var(),
        'ex_rsp': ex.mean() * 12,
        't_ex_rsp': ex.mean() / ex.std() * math.sqrt(len(ex)),
    }


SERIES = ['S1', 'S1 + vol', 'S2', 'S4', 'S4 + vol', 'SPY', 'RSP', 'Univers']


def history_lines(h, ticker):
    if h.empty:
        return [f'## Exemple : {ticker}', '', "Absente de l'univers.", '']
    lines = [f'## Exemple : notation de {ticker} (fin de chaque annee, notes de 0 a 100)', '',
             '| Date | Qualite | Rachats | Tendance | Calme | Score | Rang | Achetee S1 (top 50) | Achetee S4 (top 30) '
             '| Rdt 12 mois suivants |', '|---|---|---|---|---|---|---|---|---|---|']
    for d, r in h.iterrows():
        nxt = r.get('rdt_12m_suivants', np.nan)
        lines.append(f"| {d:%Y-%m} | {r['Qualite']*100:.0f} | {r['Rachats']*100:.0f} | {r['Tendance']*100:.0f} | "
                     f"{r['Calme']*100:.0f} | **{r['score']*100:.0f}** | {r['rang']:.0f}/{r['n']:.0f} | "
                     f"{'oui' if r['rang'] <= 50 else 'non'} | {'oui' if r['rang_def'] <= 30 else 'non'} | "
                     f"{'' if pd.isna(nxt) else f'{nxt:+.0%}'} |")
    return lines + ['']


def build_report(res, examples=()):
    hdr = ('| Strategie | Mois | Rdt annuel | Vol | Sharpe | Max DD | Beta SPY | Ecart vs RSP /an | t ecart |\n'
           '|---|---|---|---|---|---|---|---|---|')
    lines = ['# Actions US : strategies par score de themes (regles fixees avant resultats)', '',
             __doc__.strip(), '']
    for name, part in (('2010-2018 (dev)', res.loc[:DEV_END]), ('2019-2026 (deja vue par BOT 2 pour un autre modele)',
                                                                 res.loc[OOS_START:]), ('Toute la periode', res)):
        lines += [f'## {name}', '', hdr]
        for s in SERIES:
            st = stats(part[s], part['SPY'], part['RSP'])
            if st is None:
                continue
            lines.append(f"| {s} | {st['mois']} | {st['cagr']:+.1%} | {st['vol']:.1%} | {st['sharpe']:.2f} | "
                         f"{st['maxdd']:.1%} | {st['beta']:.2f} | {st['ex_rsp']:+.1%} | {st['t_ex_rsp']:+.2f} |")
        lines.append('')
    lines += ['## Rendement par annee', '', '| Annee | ' + ' | '.join(SERIES) + ' |', '|' + '---|' * (len(SERIES) + 1)]
    for y, g in res.groupby(res.index.year):
        lines.append(f'| {y} | ' + ' | '.join(f'{(1 + g[s].dropna()).prod() - 1:+.1%}' for s in SERIES) + ' |')
    lines.append('')
    for ticker, h in examples:
        lines += history_lines(h, ticker)
    lines += ['## Fonctionnement', '',
              f"- Actions dans l'univers par mois : {res['n_univ'].mean():.0f}",
              f"- Rotation mensuelle : S1 {res['to_S1'].mean():.0%}, S2 {res['to_S2'].mean():.0%}, "
              f"S4 {res['to_S4'].mean():.0%}",
              f"- Exposition moyenne de l'overlay de vol : {res['expo'].mean():.0%} "
              f"(min {res['expo'].min():.0%})",
              f"- Positions sans prix le mois suivant (comptees a 0 %) : {int(res['sans_prix'].sum())}",
              '', '## Limites', '',
              "- Biais du survivant : les entreprises radiees n'ont plus de ticker SEC ni de prix Yahoo. "
              "Les achats (S1, S4, Univers) sont flattes. S2 est au contraire penalisee : les faillites, "
              "qu'elle aurait vendues a decouvert avec profit, manquent a sa jambe vendeuse.",
              '- Le cash de l\'overlay de vol est compte a 0 % (pas de taux monetaire) : prudent.',
              "- 2019-2026 a deja servi a BOT 2 pour un autre modele : ce n'est pas un hors-echantillon vierge.", '']
    return '\n'.join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    tickers, shares, fund, purch, close, _, splits = load()
    panel = build_panel(close, tickers, shares, fund, purch, splits)
    dates = pd.DatetimeIndex(sorted(panel['date'].unique()))
    res = run_strategies(panel, forward_returns(close, dates))
    spy, rsp = etf('SPY'), etf('RSP')
    res['SPY'] = etf_monthly(spy).reindex(res.index)
    res['RSP'] = etf_monthly(rsp).reindex(res.index)
    res['Univers'] = res['univ']
    res = add_overlay(res, vol_exposure(spy))
    res = res.dropna(subset=['SPY'])
    sc = theme_scores(panel)
    examples = [(t, ticker_history(panel, sc, close, t)) for t in EXAMPLES]
    text = build_report(res, examples)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    res.to_csv(REPORT.with_suffix('.csv'))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
