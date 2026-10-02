"""Etape 3 du plan actions : recupere les donnees, construit le panel, mesure chaque bloc seul (2010-2018).

Les donnees brutes sont mises en cache (bot/equities/cache, cache GitHub Actions) pour ne pas
re-telecharger la SEC et Yahoo a chaque execution.
"""
import logging
import os
from pathlib import Path

import pandas as pd

from bot.equities import insiders, prices, sec
from bot.equities.features import FEATURES, build_panel, information_coefficients, insider_cluster_spread
from bot.research import _bonferroni

log = logging.getLogger(__name__)
CACHE = Path(__file__).parent / 'cache'
REPORT = Path(__file__).parent.parent / 'reports' / 'equities_ic.md'
END_DEV = '2018-12-31'


def cached(name, fn):
    path = CACHE / f'{name}.parquet'
    if path.exists():
        log.info(f'{name} : cache')
        return pd.read_parquet(path)
    df = fn()
    CACHE.mkdir(exist_ok=True)
    df.to_parquet(path)
    return df


def load():
    tickers = cached('tickers', sec.company_tickers)
    shares = cached('shares', sec.shares_outstanding)
    fund = cached('fundamentals', sec.annual_fundamentals)
    purch = cached('insiders', insiders.purchases)
    path = CACHE / 'close.parquet'
    if path.exists():
        close = pd.read_parquet(path)
        missing = []
    else:
        close, _, missing = prices.download(tickers['ticker'].tolist())
        close.to_parquet(path)
    return tickers, shares, fund, purch, close, missing


def report(ic, spread, panel, coverage):
    years = sorted(c for c in ic.columns if c.isdigit())
    lines = ['# Actions US > 2 Md$ : pouvoir predictif de chaque bloc seul (dev 2010-2018 uniquement)', '',
             'IC = correlation de rang, chaque fin de mois, entre la feature et le rendement du mois suivant, '
             'sur toutes les actions de l\'univers. Moyenne des IC mensuels et t-stat.',
             f'Avec {len(ic)} features testees, un |t| > {_bonferroni(len(ic)):.2f} est requis pour ecarter le hasard.',
             '', '## Couverture des donnees', ''] + [f'- {k} : {v}' for k, v in coverage.items()]
    lines += ['', '## IC par bloc', '',
              '| Feature | Mois | IC moyen | t-stat | Mois IC > 0 | Annees meme signe | ' + ' | '.join(years) + ' |',
              '|' + '---|' * (6 + len(years))]
    for d in ic.to_dict('records'):
        if not d.get('mois'):
            lines.append(f"| {d['feature']} | 0 | - | - | - | - |" + ' |' * len(years))
            continue
        yrs = ' | '.join('' if pd.isna(d.get(y)) else f'{d[y]:+.3f}' for y in years)
        lines.append(f"| {d['feature']} | {d['mois']} | {d['ic_moyen']:+.4f} | {d['t_stat']:+.2f} | "
                     f"{d['mois_ic_positif']:.0%} | {d['annees_meme_signe']} | {yrs} |")
    lines += ['', '## Achats groupes d\'initiés (>= 2 initiés acheteurs sur 90 j)', '',
              f"- Mois mesures : {spread['mois']}",
              f"- Actions signalees par mois (moyenne) : {spread['actions_signalees_par_mois']:.1f}",
              f"- Surperformance moyenne le mois suivant vs l'univers : {spread['surperformance_mensuelle']:+.2%}",
              f"- t-stat : {spread['t_stat']:+.2f}", '']
    return '\n'.join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    tickers, shares, fund, purch, close, missing = load()
    panel = build_panel(close, tickers, shares, fund, purch)
    dev = panel[panel['date'] <= END_DEV]
    coverage = {
        'Tickers SEC (NYSE + Nasdaq, aujourd\'hui)': len(tickers),
        'Tickers avec prix Yahoo': close.shape[1],
        'Tickers sans prix (non telecharges ce run)': len(missing),
        'Actions dans l\'univers > 2 Md$ par mois (moyenne dev)': f"{dev.groupby('date').size().mean():.0f}",
        'Achats d\'initiés extraits (toutes entreprises)': len(purch),
        'Biais du survivant': 'les entreprises radiees n\'ont plus de ticker SEC ni de prix Yahoo : absentes du panel',
    }
    text = report(information_coefficients(panel, END_DEV), insider_cluster_spread(panel, END_DEV), panel, coverage)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
