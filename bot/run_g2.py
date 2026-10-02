"""G2 dimensionnee pour le gate revise, jugee uniquement sur la periode jamais utilisee (avril 2018 - sept. 2022).

Gate revise par l'utilisateur le 2026-10-02, AVANT ce test :
- drawdown max -20 % (au lieu de -15 %) ;
- profit factor > 1,5 (somme des gains / somme des pertes) au lieu du taux de reussite > 55 %,
  inadapte a une strategie de momentum (beaucoup de petites pertes, quelques gros gains) ;
- Sharpe > 1,5 et t-stat corrigee du nombre d'essais, inchanges.
Cible de volatilite fixee par une regle annoncee avant le test, calibree sur la periode DEJA vue :
  40 % x (20 % / 33 % de drawdown de G2 sur 2022-2026) x 0,8 de marge = 19 %.
"""
import logging
import os
from pathlib import Path

import pandas as pd

from bot.backtest import metrics, split, t_threshold
from bot.data import fetch_1h
from bot.g_variants import btc_below_sma200
from bot.multi import SYMBOLS, rotation_momentum
from bot.run_g import UNSEEN

REPORT = Path(__file__).parent / 'reports' / 'g2_final.md'
SEEN_DD_G2 = 0.33
TARGET_VOL = round(0.40 * (0.20 / SEEN_DD_G2) * 0.8, 2)  # 0.19
N_TESTS = 16  # 15 deja testees + cette version dimensionnee
GATE_V2 = {'sharpe': 1.5, 'max_drawdown': -0.20, 'profit_factor': 1.5}


def profit_factor(trades):
    gains = trades.loc[trades['pnl'] > 0, 'pnl'].sum()
    losses = -trades.loc[trades['pnl'] < 0, 'pnl'].sum()
    return float(gains / losses) if losses > 0 else float('inf')


def evaluate(r, trades, start, end=None):
    rr, tt = split(r, trades, start, end)
    m = metrics(rr, tt)
    m['profit_factor'] = profit_factor(tt)
    return m


def gate_v2(m, n_tests=N_TESTS):
    t_req = t_threshold(n_tests)
    checks = {'Sharpe > 1,5': m['sharpe'] > GATE_V2['sharpe'],
              'Drawdown max > -20 %': m['max_drawdown'] > GATE_V2['max_drawdown'],
              'Profit factor > 1,5': m['profit_factor'] > GATE_V2['profit_factor'],
              f't-stat > {t_req:.2f}': m['t_stat'] > t_req}
    return checks, all(checks.values())


def _row(name, m):
    return (f"| {name} | {m['rendement_annuel']:+.1%} | {m['sharpe']:.2f} | {m['t_stat']:.2f} | {m['max_drawdown']:.1%} "
            f"| {m['profit_factor']:.2f} | {m['hit_rate']:.0%} | {m['nb_trades']} | {m['expo_moyenne_pct_heures']:.0%} |")


def build_report(dfs):
    risk_off = btc_below_sma200(dfs)
    runs = {f'G2 a {TARGET_VOL:.0%} de vol (candidate)': rotation_momentum(dfs, risk_off=risk_off, target_vol=TARGET_VOL)[:2],
            'G2 a 40 % de vol (version precedente)': rotation_momentum(dfs, risk_off=risk_off)[:2]}
    head = ('| Version | Rdt annuel | Sharpe | t-stat | Max DD | Profit factor | Trades gagnants | Trades | Expo |\n'
            '|---|---|---|---|---|---|---|---|---|')
    lines = ['# G2 dimensionnee : verdict final', '',
             f'Regle de dimensionnement annoncee avant le test : cible de vol = 40 % x (20 % / {SEEN_DD_G2:.0%}) x 0,8 '
             f'= {TARGET_VOL:.0%}.',
             'Gate revise par l\'utilisateur avant ce test : Sharpe > 1,5, drawdown max > -20 %, profit factor > 1,5, '
             f't-stat > {t_threshold(N_TESTS):.2f} ({N_TESTS} strategies testees au total).', '',
             f'## Periode jamais utilisee ({UNSEEN[0]:%Y-%m-%d} -> {UNSEEN[1]:%Y-%m-%d}) : le seul juge', '', head]
    cand = None
    for name, (r, t) in runs.items():
        m = evaluate(r, t, *UNSEEN)
        cand = cand or m
        lines.append(_row(name, m))
    checks, ok = gate_v2(cand)
    lines += ['', '## Verdict (version candidate)', ''] + [f"- {k} : {'OK' if v else 'ECHEC'}" for k, v in checks.items()]
    lines += ['', f"**{'PASSE' if ok else 'ECHOUE'}**", '',
              '## Periode deja vue (octobre 2022 -> aujourd\'hui), info seulement', '', head]
    for name, (r, t) in runs.items():
        lines.append(_row(name, evaluate(r, t, UNSEEN[1])))
    r, _ = list(runs.values())[0]
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    eq = (1 + r).cumprod()
    dd_year = (eq / eq.cummax() - 1).groupby(r.index.year).min()
    lines += ['', '## Version candidate par annee', '', '| Annee | Rendement | Pire drawdown dans l\'annee |', '|---|---|---|']
    lines += [f'| {y} | {v:+.1%} | {dd_year[y]:.1%} |' for y, v in yearly.items()]
    return '\n'.join(lines) + '\n'


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    bars = int((pd.Timestamp.now(tz='UTC') - pd.Timestamp('2017-08-17', tz='UTC')).total_seconds() // 3600)
    dfs = {s: fetch_1h(s, bars=bars) for s in SYMBOLS}
    text = build_report(dfs)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
