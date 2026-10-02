"""G2 a differentes tailles de position (cible de volatilite), meme signal. Information, pas un nouvel essai.

Sans levier : le poids d'une crypto est plafonne a 100 % du capital, donc au-dela d'une certaine cible
la taille n'augmente plus (le plafond bloque quand la vol de la crypto est inferieure a la cible).
Prix quotidiens Coin Metrics, comme la confirmation 2015-2018.
"""
import logging
import os
from pathlib import Path

import pandas as pd

from bot.g_variants import btc_below_sma200
from bot.multi import rotation_momentum
from bot.run_g import UNSEEN
from bot.run_g2 import evaluate
from bot.run_g2_long import ASSETS, EARLY, as_frame, fetch_daily

REPORT = Path(__file__).parent / 'reports' / 'g2_tailles.md'
TARGETS = (0.19, 0.25, 0.30, 0.40, 0.60, 0.80)
PERIODS = {'Oct. 2015 -> mars 2018': EARLY, 'Avr. 2018 -> sept. 2022': UNSEEN,
           'Oct. 2022 -> aujourd\'hui': (UNSEEN[1], None), 'Total 2015 -> aujourd\'hui': (EARLY[0], None)}


def build_report(dfs):
    risk_off = btc_below_sma200(dfs)
    runs = {tv: rotation_momentum(dfs, risk_off=risk_off, target_vol=tv) for tv in TARGETS}
    lines = ['# G2 : effet de la taille de position', '',
             'Meme signal (top 1 sur 30 j, cash si BTC sous sa moyenne 200 j), seule la cible de volatilite change. '
             'Sans levier : poids plafonne a 100 %. Information seulement : 19 % est la version validee.', '']
    for pname, (start, end) in PERIODS.items():
        lines += [f'## {pname}', '',
                  '| Cible de vol | Expo moyenne | Rdt annuel | Sharpe | Max DD | Profit factor | DD > -20 % ? |',
                  '|---|---|---|---|---|---|---|']
        for tv, (r, trades, w) in runs.items():
            m = evaluate(r, trades, start, end)
            ws = w.sum(axis=1)
            ws = ws[(ws.index >= start) & ((ws.index < end) if end is not None else True)]
            lines.append(f"| {tv:.0%}{' (validee)' if tv == 0.19 else ''} | {ws.mean():.0%} | {m['rendement_annuel']:+.1%} "
                         f"| {m['sharpe']:.2f} | {m['max_drawdown']:.1%} | {m['profit_factor']:.2f} "
                         f"| {'oui' if m['max_drawdown'] > -0.20 else 'non'} |")
        lines.append('')
    lines += ['## Par annee (rendement)', '', '| Annee | ' + ' | '.join(f'{tv:.0%}' for tv in TARGETS) + ' |',
              '|' + '---|' * (len(TARGETS) + 1)]
    yearly = pd.DataFrame({tv: (1 + r).groupby(r.index.year).prod() - 1 for tv, (r, _, _) in runs.items()})
    lines += [f'| {y} | ' + ' | '.join(f'{v:+.1%}' for v in row) + ' |' for y, row in yearly.iterrows() if y >= 2015]
    return '\n'.join(lines) + '\n'


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    dfs = {sym: as_frame(fetch_daily(a)) for sym, a in ASSETS.items()}
    text = build_report(dfs)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
