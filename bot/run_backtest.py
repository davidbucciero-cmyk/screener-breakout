"""Backtest des strategies candidates. Ecrit bot/reports/backtest.md (+ resume GitHub Actions).

Periode de dev = 2 premieres annees, hors echantillon = 2 dernieres. Les parametres sont fixes a
priori ; le gate ne porte que sur le hors echantillon.
"""
import argparse
import logging
import os
from pathlib import Path

import pandas as pd

from bot.backtest import GATE, gate, metrics, regimes, split, t_threshold
from bot.data import fetch_1h
from bot.strategies import FEE_BPS, SLIPPAGE_BPS, run_strategies

REPORT = Path(__file__).parent / 'reports' / 'backtest.md'


def _fmt(m):
    return (f"| {m['rendement_annuel']:+.1%} | {m['sharpe']:.2f} | {m['t_stat']:.2f} | {m['max_drawdown']:.1%} "
            f"| {m['hit_rate']:.1%} | {m['nb_trades']} | {m['expo_moyenne_pct_heures']:.0%} |")


def _regime_table(reg):
    rows = ['| Regime | Jours | Rdt annualise | Sharpe |', '|---|---|---|---|']
    rows += [f"| {x.regime} | {x.jours} | {x.rendement_annualise:+.1%} | {x.sharpe:.2f} |" for x in reg.itertuples()]
    return '\n'.join(rows)


def build_report(df, oos_years=2):
    oos_start = df.index[-1] - pd.Timedelta(days=365 * oos_years)
    results = run_strategies(df)
    n_tests = sum(not k.startswith('Reference') for k in results)
    head = '| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |\n|---|---|---|---|---|---|---|---|'
    lines = [
        '# Backtest BTC/USD 1h',
        '',
        f'Donnees Binance BTCUSDT du {df.index[0]:%Y-%m-%d} au {df.index[-1]:%Y-%m-%d %H:%M} UTC. '
        f'Couts : {FEE_BPS:.0f} bps de frais + {SLIPPAGE_BPS:.0f} bps de slippage par cote.',
        f'Hors echantillon (gate) : a partir du {oos_start:%Y-%m-%d}. '
        f"Gate : Sharpe > {GATE['sharpe']}, max DD > {GATE['max_drawdown']:.0%}, "
        f"taux de reussite > {GATE['hit_rate']:.0%}, t-stat > {t_threshold(n_tests):.2f} "
        f"({GATE['t_stat']} corrige de Bonferroni pour {n_tests} strategies testees).",
        '',
        '## Hors echantillon', '', head,
    ]
    verdicts, dev_rows, regime_parts = [], [], []
    for name, (r, trades) in results.items():
        r_oos, t_oos = split(r, trades, oos_start)
        r_dev, t_dev = split(r, trades, df.index[0], oos_start)
        m = metrics(r_oos, t_oos)
        lines.append(f'| {name} ' + _fmt(m))
        dev_rows.append(f'| {name} ' + _fmt(metrics(r_dev, t_dev)))
        if not name.startswith('Reference'):
            g = gate(m, n_tests)
            failed = [k for k in GATE if not g[k]]
            verdicts.append(f"- **{name}** : {'PASSE' if g['passed'] else 'ECHOUE'}"
                            + (f" (echoue sur : {', '.join(failed)})" if failed else ''))
        reg = regimes(r_oos, df['close'])
        regime_parts += [f'### {name}', '', _regime_table(reg), '']
    lines += ['', '## Verdict du gate', ''] + verdicts
    lines += ['', '## Periode de dev (info seulement, pas de gate)', '', head] + dev_rows
    lines += ['', '## Hors echantillon par regime', ''] + regime_parts
    return '\n'.join(lines) + '\n'


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    p = argparse.ArgumentParser()
    p.add_argument('--years', type=int, default=4)
    args = p.parse_args()
    report = build_report(fetch_1h(bars=24 * 365 * args.years))
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(report)
    print(report)


if __name__ == '__main__':
    main()
