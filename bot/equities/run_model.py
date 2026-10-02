"""Etape 4 du plan actions : modele combine, evaluation unique hors echantillon 2019 -> aujourd'hui."""
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from bot.backtest import GATE
from bot.equities.features import build_panel, information_coefficients, month_ends
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


def build_report(res, weights, block_ics=None):
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
    lines += ['', '## Diagnostic (mesure, pas un nouvel essai) : nos actions contre l\'action moyenne de l\'univers', '',
              'Les IC des blocs mesuraient la capacite a battre l\'action moyenne (poids egal), pas le SPY.', '',
              '| Periode | Mois | Ecart annuel vs action moyenne | Sharpe de l\'ecart | t-stat | Mois gagnants | IC moyen du score | t-stat IC |',
              '|---|---|---|---|---|---|---|---|']
    for name, part in (('Dev 2010-2018', dev), ('Hors echantillon 2019-2026', oos)):
        ex, ic = part['vs_univ'].dropna(), part['score_ic'].dropna()
        lines.append(f"| {name} | {len(ex)} | {(1 + ex).prod() ** (12 / len(ex)) - 1:+.1%} | "
                     f"{ex.mean() / ex.std() * 12 ** 0.5:.2f} | {ex.mean() / ex.std() * len(ex) ** 0.5:.2f} | "
                     f"{(ex > 0).mean():.0%} | {ic.mean():+.4f} | {ic.mean() / ic.std() * len(ic) ** 0.5:.2f} |")
    lines += ['', '| Annee | Nos actions | Action moyenne | SPY | Ecart vs action moyenne | Ecart action moyenne vs SPY |',
              '|---|---|---|---|---|---|']
    for y, g in res.groupby(res.index.year):
        lo, un, sp = ((1 + g[c]).prod() - 1 for c in ('long', 'univ', 'spy'))
        lines.append(f'| {y} | {lo:+.1%} | {un:+.1%} | {sp:+.1%} | {lo - un:+.1%} | {un - sp:+.1%} |')
    if block_ics is not None:
        lines += ['', '### IC de chaque bloc : dev 2010-2018 vs hors echantillon 2019-2026', '',
                  '| Bloc | IC dev | t dev | IC 2019-2026 | t 2019-2026 |', '|---|---|---|---|---|']
        for feat, r in block_ics.iterrows():
            lines.append(f"| {feat} | {r['ic_dev']:+.4f} | {r['t_dev']:+.2f} | {r['ic_oos']:+.4f} | {r['t_oos']:+.2f} |")
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
    dev_ic = information_coefficients(panel, '2018-12-31', RETAINED).set_index('feature')
    oos_ic = information_coefficients(panel, '2100-01-01', RETAINED, start=OOS_START).set_index('feature')
    block_ics = pd.DataFrame({'ic_dev': dev_ic['ic_moyen'], 't_dev': dev_ic['t_stat'],
                              'ic_oos': oos_ic['ic_moyen'], 't_oos': oos_ic['t_stat']}).loc[RETAINED]
    text = build_report(res, yearly_weights(panel), block_ics)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
