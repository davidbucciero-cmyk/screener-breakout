"""Audit des donnees de prix : l'action moyenne de l'univers est-elle credible ? Ou sont les aberrations ?

Mesure uniquement : rien ici ne modifie le panel ni le modele.
"""
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from bot.equities.features import build_panel, month_ends
from bot.equities.run import CACHE, load

log = logging.getLogger(__name__)
REPORT = Path(__file__).parent.parent / 'reports' / 'equities_audit.md'
EXTREME_UP, EXTREME_DOWN = 2.0, -0.9


def etf_yearly(symbol):
    path = CACHE / f'{symbol.lower()}.parquet'
    if path.exists():
        close = pd.read_parquet(path)['close']
    else:
        import yfinance as yf
        close = yf.download(symbol, start='2008-06-01', auto_adjust=True, progress=False)['Close'].squeeze()
        close.index = pd.DatetimeIndex(close.index).tz_localize(None)
        close.to_frame('close').to_parquet(path)
    y = close.groupby(close.index.year).last()
    return y / y.shift(1) - 1


def yearly_from_monthly(m):
    """m : rendement mensuel indexe par la fin de mois de DEPART -> annee civile du mois de rendement."""
    end = m.index + pd.offsets.MonthEnd(1)
    return (1 + m).groupby(end.year).prod() - 1


def audit(panel, close, tickers):
    p = panel.dropna(subset=['fwd_ret'])
    ew = p.groupby('date')['fwd_ret'].mean()
    med = p.groupby('date')['fwd_ret'].median()
    clean = p[(p['fwd_ret'] < EXTREME_UP) & (p['fwd_ret'] > EXTREME_DOWN)].groupby('date')['fwd_ret'].mean()
    rsp, spy = etf_yearly('RSP'), etf_yearly('SPY')
    years = pd.DataFrame({'univers_moyenne': yearly_from_monthly(ew), 'univers_sans_extremes': yearly_from_monthly(clean),
                          'univers_mediane': yearly_from_monthly(med), 'RSP': rsp, 'SPY': spy}).dropna(how='all')
    ext = p[(p['fwd_ret'] >= EXTREME_UP) | (p['fwd_ret'] <= EXTREME_DOWN)].copy()
    ext['annee'] = (ext['date'] + pd.offsets.MonthEnd(1)).dt.year
    names = tickers.drop_duplicates('ticker').set_index('ticker')['name']
    ext['nom_sec'] = ext['ticker'].map(names)
    # Sauts quotidiens suspects (> +300 % ou < -80 % en un jour) : souvent split mal ajuste ou ticker reutilise.
    daily = close.pct_change(fill_method=None)
    jumps = ((daily > 3.0) | (daily < -0.8)).sum()
    jumps = jumps[jumps > 0].sort_values(ascending=False)
    in_univ = set(p['ticker'])
    jumps_univ = jumps[jumps.index.isin(in_univ)]
    return years, ext, jumps_univ, p


def report(years, ext, jumps, p):
    lines = ['# Audit des donnees de prix (actions US > 2 Md$)', '',
             'Mesure uniquement. Reference attendue : l\'action moyenne de l\'univers a poids egal doit suivre de pres '
             'l\'ETF RSP (S&P 500 a poids egal), a quelques points pres.', '',
             '## Action moyenne de l\'univers vs ETF de reference, par annee', '',
             '| Annee | Univers (moyenne) | Univers sans extremes | Univers (mediane) | RSP | SPY | Ecart moyenne - RSP |',
             '|---|---|---|---|---|---|---|']
    for y, r in years.iterrows():
        f = lambda v: '' if pd.isna(v) else f'{v:+.1%}'
        gap = r['univers_moyenne'] - r['RSP'] if pd.notna(r['RSP']) else np.nan
        lines.append(f"| {y} | {f(r['univers_moyenne'])} | {f(r['univers_sans_extremes'])} | {f(r['univers_mediane'])} "
                     f"| {f(r['RSP'])} | {f(r['SPY'])} | {f(gap)} |")
    n_obs = len(p)
    lines += ['', f'## Rendements mensuels extremes (>= +{EXTREME_UP:.0%} ou <= {EXTREME_DOWN:.0%})', '',
              f'{len(ext)} observations sur {n_obs} ({len(ext) / n_obs:.3%}).', '',
              '| Annee | Nombre | Somme des rendements extremes |', '|---|---|---|']
    for y, g in ext.groupby('annee'):
        lines.append(f"| {y} | {len(g)} | {g['fwd_ret'].sum():+.0%} |")
    lines += ['', '### Les 40 plus gros', '', '| Mois | Ticker | Nom SEC (aujourd\'hui) | Rendement du mois | Cap. estimee |',
              '|---|---|---|---|---|']
    for r in ext.reindex(ext['fwd_ret'].abs().sort_values(ascending=False).index).head(40).itertuples():
        lines.append(f"| {r.date:%Y-%m} | {r.ticker} | {r.nom_sec} | {r.fwd_ret:+.0%} | {r.mcap / 1e9:.1f} Md$ |")
    lines += ['', '## Sauts quotidiens suspects (> +300 % ou < -80 % en un jour), actions passees par l\'univers', '',
              f'{len(jumps)} tickers concernes.', '', '| Ticker | Nombre de sauts |', '|---|---|']
    lines += [f'| {t} | {n} |' for t, n in jumps.head(40).items()]
    return '\n'.join(lines) + '\n'


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    tickers, shares, fund, purch, close, _ = load()
    panel = build_panel(close, tickers, shares, fund, purch)
    text = report(*audit(panel, close, tickers))
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
