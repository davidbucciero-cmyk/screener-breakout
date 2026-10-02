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
from bot.funding import crowded_longs, fetch_funding
from bot.multi import (MULTI, SYMBOLS, UNIVERSE, blend, cross_sectional_momentum, equal_weight_hold,
                       rotation_with_funding)
from bot.strategies import FEE_BPS, SLIPPAGE_BPS, run_strategies

REPORT = Path(__file__).parent / 'reports' / 'backtest.md'


def _fmt(m):
    return (f"| {m['rendement_annuel']:+.1%} | {m['sharpe']:.2f} | {m['t_stat']:.2f} | {m['max_drawdown']:.1%} "
            f"| {m['hit_rate']:.1%} | {m['nb_trades']} | {m['expo_moyenne_pct_heures']:.0%} |")


def _regime_table(reg):
    rows = ['| Regime | Jours | Rdt annualise | Sharpe |', '|---|---|---|---|']
    rows += [f"| {x.regime} | {x.jours} | {x.rendement_annualise:+.1%} | {x.sharpe:.2f} |" for x in reg.itertuples()]
    return '\n'.join(rows)


def build_report(df, oos_years=2, others=None, funding=None):
    oos_start = df.index[-1] - pd.Timedelta(days=365 * oos_years)
    results = run_strategies(df)
    if others:
        dfs = {'BTCUSDT': df, **others}
        for name, fn in MULTI.items():
            results[name] = fn(dfs)[:2]
        results['Reference - Buy & hold equipondere BTC/ETH/SOL'] = equal_weight_hold(dfs)[:2]
        three = {k: dfs[k] for k in SYMBOLS}
        if all(k in dfs for k in UNIVERSE):
            results['I - Momentum top 3 sur 11 cryptos'] = cross_sectional_momentum(
                {k: dfs[k] for k in UNIVERSE})[:2]
        if funding is not None:
            results['J - Rotation G + filtre de financement'] = rotation_with_funding(
                three, crowded_longs(funding))[:2]
        results['K - Panier G + H + E'] = blend(results['G - Rotation momentum BTC/ETH/SOL'],
                                                results['H - Trend diversifie BTC/ETH/SOL'],
                                                results['E - Cassure Donchian 20/10 j'])
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
    bars = 24 * 365 * args.years
    others = {s: fetch_1h(s, bars=bars) for s in UNIVERSE if s != 'BTCUSDT'}
    btc = fetch_1h(bars=bars)
    try:
        funding = fetch_funding(btc.index[0] - pd.Timedelta(days=400))
    except Exception as e:  # source externe : on le signale au lieu de planter
        logging.warning(f'Funding indisponible, strategie J non testee : {e}')
        funding = None
    report = build_report(btc, others=others, funding=funding)
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(report)
    print(report)


if __name__ == '__main__':
    main()
