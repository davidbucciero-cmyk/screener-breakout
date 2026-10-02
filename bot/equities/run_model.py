"""Etape 4 du plan actions : modele combine, evaluation unique hors echantillon 2019 -> aujourd'hui."""
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from bot.backtest import GATE
from bot.equities.features import build_panel, month_ends
from bot.equities.model import RETAINED, backtest, stats, yearly_weights
from bot.equities.run import CACHE, load
from bot.research import _bonferroni

log = logging.getLogger(__name__)
REPORT = Path(__file__).parent.parent / 'reports' / 'equities_model.md'
OOS_START = '2019-01-01'
N_TESTS = 12  # 11 strategies crypto deja testees + ce modele


def spy_monthly():
    path = CACHE / 'spy.parquet'
    if path.exists():
        close = pd.read_parquet(path)['close']
    else:
        import yfinance as yf
        close = yf.download('SPY', start='2008-06-01', auto_adjust=True, progress=False)['Close'].squeeze()
        close.index = pd.DatetimeIndex(close.index).tz_localize(None)
        close.to_frame('close').to_parquet(path)
    m = close.loc[month_ends(close.index)]
    # Rendement du mois qui suit chaque fin de mois, indexe par la fin de mois de depart (comme fwd_ret).
    fwd = m.shift(-1) / m - 1
    return pd.Series(fwd.to_numpy(), index=m.index + pd.offsets.MonthEnd(0))


def _row(name, s):
    hit = '' if np.isnan(s['hit_rate']) else f"{s['hit_rate']:.0%}"
    return (f"| {name} | {s['mois']} | {s['rendement_annuel']:+.1%} | {s['sharpe']:.2f} | {s['t_stat']:.2f} | "
            f"{s['max_drawdown']:.1%} | {s['mois_positifs']:.0%} | {hit} |")


def build_report(res, weights):
    oos = res.loc[OOS_START:]
    dev = res.loc[:'2018-12-31']
    s_h = stats(oos['hedged'], oos['hit_positions'])
    t_req = _bonferroni(N_TESTS)
    checks = {'Sharpe > 1.5': s_h['sharpe'] > GATE['sharpe'],
              'Max DD > -15 %': s_h['max_drawdown'] > GATE['max_drawdown'],
              'Taux de reussite > 55 %': s_h['hit_rate'] > GATE['hit_rate'],
              f't-stat > {t_req:.2f}': s_h['t_stat'] > t_req}
    beta = np.cov(oos['long'], oos['spy'])[0, 1] / oos['spy'].var()
    head = ['| Serie | Mois | Rdt annuel | Sharpe | t-stat | Max DD | Mois positifs | Taux de reussite (positions) |',
            '|---|---|---|---|---|---|---|---|']
    lines = ['# Actions US : modele combine (7 blocs), evaluation unique hors echantillon', '',
             f'Hors echantillon : {oos.index[0]:%Y-%m} a {oos.index[-1]:%Y-%m}. Top 10 % du score, poids egal, '
             'couvert par une vente de SPY. Frais 10 bps par cote (actions), 2 bps (SPY), emprunt SPY 0,5 %/an.',
             'Taux de reussite = part des positions qui battent SPY sur leur mois.', '',
             '## Hors echantillon (le seul resultat qui compte)', ''] + head + [
        _row('Couvert (long - SPY)', s_h),
        _row('Long seul', stats(oos['long'], oos['hit_positions'])),
        _row('SPY', stats(oos['spy'])), '',
        '## Verdict du gate', ''] + [f"- {k} : {'OK' if v else 'ECHEC'}" for k, v in checks.items()] + [
        '', f"**{'PASSE' if all(checks.values()) else 'ECHOUE'}**", '',
        f'Beta de la jambe longue vs SPY (hors echantillon) : {beta:.2f}. La couverture 1:1 '
        + ('sur-couvre' if beta < 0.95 else 'sous-couvre' if beta > 1.05 else 'couvre correctement') + ' le marche.',
        f"Positions par mois : {res['positions'].mean():.0f}. Rotation mensuelle moyenne : {res['turnover'].mean():.0%}. "
        f"Positions sans prix le mois suivant (comptees a 0 %) : {int(res['sans_prix'].sum())}.", '',
        '## Periode de dev 2010-2018 (info, poids appris en fenetre croissante)', ''] + head + [
        _row('Couvert (long - SPY)', stats(dev['hedged'], dev['hit_positions'])),
        _row('Long seul', stats(dev['long'], dev['hit_positions'])), _row('SPY', stats(dev['spy'])), '',
        '## Rendement par annee', '', '| Annee | Couvert | Long seul | SPY |', '|---|---|---|---|']
    for y, g in res.groupby(res.index.year):
        lines.append(f"| {y} | {(1 + g['hedged']).prod() - 1:+.1%} | {(1 + g['long']).prod() - 1:+.1%} | "
                     f"{(1 + g['spy']).prod() - 1:+.1%} |")
    lines += ['', '## Poids appris par annee (IC moyen passe ; signe negatif = moins c\'est mieux)', '',
              '| Annee | ' + ' | '.join(RETAINED) + ' |', '|' + '---|' * (len(RETAINED) + 1)]
    for y, w in weights.dropna(how='all').iterrows():
        lines.append(f'| {y} | ' + ' | '.join(f'{v:+.3f}' for v in w) + ' |')
    lines += ['', '## Limites', '',
              '- Biais du survivant : entreprises radiees absentes (ni ticker SEC ni prix Yahoo). Resultats flattes.',
              '- Donnees XBRL frames : derniere valeur deposee, une correction posterieure peut fuiter (decalage 90 j).',
              '']
    return '\n'.join(lines)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    tickers, shares, fund, purch, close, _ = load()
    panel = build_panel(close, tickers, shares, fund, purch)
    res = backtest(panel, spy_monthly())
    text = build_report(res, yearly_weights(panel))
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
