"""Ameliorations de G : gate jugee UNIQUEMENT sur avril 2018 -> septembre 2022, jamais utilisee jusqu'ici."""
import logging
import os
from pathlib import Path

import pandas as pd

from bot.backtest import GATE, gate, metrics, regimes, split, t_threshold
from bot.data import fetch_1h
from bot.g_variants import VARIANTS
from bot.multi import SYMBOLS, equal_weight_hold
from bot.strategies import FEE_BPS, SLIPPAGE_BPS, position_returns, position_trades

REPORT = Path(__file__).parent / 'reports' / 'g_ameliorations.md'
UNSEEN = (pd.Timestamp('2018-04-01', tz='UTC'), pd.Timestamp('2022-10-03', tz='UTC'))
N_TESTS = 15  # 12 strategies deja testees + G1, G2, G3


def _fmt(m):
    return (f"| {m['rendement_annuel']:+.1%} | {m['sharpe']:.2f} | {m['t_stat']:.2f} | {m['max_drawdown']:.1%} "
            f"| {m['hit_rate']:.1%} | {m['nb_trades']} | {m['expo_moyenne_pct_heures']:.0%} |")


def build_report(dfs):
    btc = dfs['BTCUSDT']
    results = {name: fn(dfs)[:2] for name, fn in VARIANTS.items()}
    bh = pd.Series(1.0, index=btc.index)
    r_bh = position_returns(btc, bh)
    results['Reference - BTC achete et garde'] = (r_bh, position_trades(btc, bh, r_bh))
    results['Reference - BTC/ETH/SOL a parts egales'] = equal_weight_hold(dfs)[:2]
    t_req = t_threshold(N_TESTS)
    head = '| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |\n|---|---|---|---|---|---|---|---|'
    lines = ['# Ameliorations de G', '',
             f"Donnees Binance du {btc.index[0]:%Y-%m-%d} au {btc.index[-1]:%Y-%m-%d}. Couts : {FEE_BPS:.0f} bps + "
             f"{SLIPPAGE_BPS:.0f} bps de slippage par cote. SOL n'existe qu'a partir d'aout 2020 : avant, rotation BTC/ETH.",
             f"Gate jugee uniquement sur la periode jamais utilisee ({UNSEEN[0]:%Y-%m-%d} -> {UNSEEN[1]:%Y-%m-%d}) : "
             f"Sharpe > {GATE['sharpe']}, max DD > {GATE['max_drawdown']:.0%}, taux de reussite > {GATE['hit_rate']:.0%}, "
             f"t-stat > {t_req:.2f} ({N_TESTS} strategies testees au total).", '',
             '## Periode jamais utilisee (avril 2018 -> septembre 2022) : le seul juge', '', head]
    verdicts, seen_rows, regime_parts = [], [], []
    for name, (r, trades) in results.items():
        r_u, t_u = split(r, trades, *UNSEEN)
        m = metrics(r_u, t_u)
        lines.append(f'| {name} ' + _fmt(m))
        r_s, t_s = split(r, trades, UNSEEN[1])
        seen_rows.append(f'| {name} ' + _fmt(metrics(r_s, t_s)))
        if not name.startswith('Reference'):
            g = gate(m, N_TESTS)
            failed = [k for k in GATE if not g[k]]
            verdicts.append(f"- **{name}** : {'PASSE' if g['passed'] else 'ECHOUE'}"
                            + (f" (echoue sur : {', '.join(failed)})" if failed else ''))
            reg = regimes(r_u, btc['close'])
            regime_parts += [f'### {name}', '', '| Regime | Jours | Rdt annualise | Sharpe |', '|---|---|---|---|']
            regime_parts += [f"| {x.regime} | {x.jours} | {x.rendement_annualise:+.1%} | {x.sharpe:.2f} |"
                             for x in reg.itertuples()] + ['']
    lines += ['', '## Verdict du gate (periode jamais utilisee)', ''] + verdicts
    lines += ['', '## Periode deja vue (octobre 2022 -> aujourd\'hui), info seulement', '', head] + seen_rows
    lines += ['', '## Periode jamais utilisee, par regime', ''] + regime_parts
    yearly = pd.DataFrame({n: (1 + r).groupby(r.index.year).prod() - 1 for n, (r, _) in results.items()})
    lines += ['## Rendement par annee', '', '| Annee | ' + ' | '.join(yearly.columns) + ' |',
              '|' + '---|' * (len(yearly.columns) + 1)]
    lines += [f'| {y} | ' + ' | '.join(f'{v:+.1%}' for v in row) + ' |' for y, row in yearly.iterrows()]
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
