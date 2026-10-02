"""Avant le premier ordre : (1) rejeu des 12 derniers mois avec le code du bot, (2) bandes de normalite.

(1) Chaque jour, le bot ne voit que les donnees disponibles ce jour-la (`decide` sur l'historique tronque).
    Ses decisions doivent etre identiques a celles du backtest, et sa performance tres proche.
(2) Sur tout l'historique Coin Metrics (2015 -> aujourd'hui), distribution des resultats de chaque
    enveloppe sur 1, 3 et 6 mois glissants : sert a juger si le paper est "dans la normale".
"""
import json
import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from btc_forecast.data import fetch_btc
from bot.data import fetch_1h
from bot.g2_live import SLEEVES, decide
from bot.g_variants import btc_below_sma200, btc_below_sma200_daily
from bot.multi import rotation_momentum, rotation_weights
from bot.run_g2_long import ASSETS, as_frame, fetch_daily
from bot.strategies import COST

REPORTS = Path(__file__).parent / 'reports'
WINDOWS = {'1 mois': 30, '3 mois': 91, '6 mois': 182}


def daily_returns(daily, target_vol):
    """Rendement quotidien net d'une enveloppe : poids decide la veille x rendement du jour - frais."""
    w = rotation_weights(daily, risk_off=btc_below_sma200_daily(daily['BTCUSDT']), target_vol=target_vol)
    held = w.shift(1).fillna(0.0)
    ret = daily.pct_change(fill_method=None).fillna(0.0)
    turnover = held.diff().abs().fillna(held.abs()).sum(axis=1)
    return (held * ret).sum(axis=1) - turnover * COST


def replay(daily, hourly_dfs, days=365):
    start = daily.index[-1] - pd.Timedelta(days=days)
    rows, lines = [], []
    for name, cfg in SLEEVES.items():
        full = rotation_weights(daily, risk_off=btc_below_sma200_daily(daily['BTCUSDT']), target_vol=cfg['target_vol'])
        mism = 0
        for d in daily.index[daily.index >= start]:
            live = decide(daily.loc[:d], cfg['target_vol'])
            if not np.allclose(live.to_numpy(), full.loc[d].to_numpy(), atol=1e-12):
                mism += 1
        r_bot = daily_returns(daily, cfg['target_vol'])
        r_bot = r_bot[r_bot.index > start]
        r_bt = rotation_momentum(hourly_dfs, risk_off=btc_below_sma200(hourly_dfs), target_vol=cfg['target_vol'])[0]
        r_bt = r_bt[r_bt.index > start + pd.Timedelta(days=1)]
        eq_bot, eq_bt = (1 + r_bot).cumprod(), (1 + r_bt).cumprod()
        rows.append({'enveloppe': name, 'jours': int((daily.index >= start).sum()), 'decisions_differentes': mism,
                     'perf_bot': eq_bot.iloc[-1] - 1, 'perf_backtest_1h': eq_bt.iloc[-1] - 1,
                     'dd_bot': (eq_bot / eq_bot.cummax() - 1).min(), 'dd_backtest_1h': (eq_bt / eq_bt.cummax() - 1).min()})
    return pd.DataFrame(rows), start


def bands(cm_daily):
    out = {}
    for name, cfg in SLEEVES.items():
        r = daily_returns(cm_daily, cfg['target_vol']).loc['2015-10-01':]
        eq = (1 + r).cumprod()
        out[name] = {}
        for label, n in WINDOWS.items():
            ret = eq / eq.shift(n) - 1
            dd = eq.rolling(n).apply(lambda x: (x / np.maximum.accumulate(x) - 1).min(), raw=True)
            q = lambda s: {f'p{int(p * 100)}': float(s.quantile(p)) for p in (0.05, 0.25, 0.5, 0.75, 0.95)}
            out[name][label] = {'rendement': q(ret.dropna()), 'drawdown': q(dd.dropna()),
                                'part_negative': float((ret.dropna() < 0).mean())}
    return out


def report(rep, start, bnd):
    lines = ['# G2 : verifications avant le premier ordre', '',
             f'## 1. Rejeu des 12 derniers mois avec le code du bot (depuis le {start:%Y-%m-%d})', '',
             'Chaque jour, le bot ne voit que les donnees disponibles ce jour-la. Attendu : 0 decision differente, '
             'performance proche du backtest en bougies 1h (ecart du aux prix quotidiens et a l\'heure d\'execution).', '',
             '| Enveloppe | Jours | Decisions differentes du backtest | Perf. bot | Perf. backtest 1h | Max DD bot | Max DD backtest 1h |',
             '|---|---|---|---|---|---|---|']
    for x in rep.itertuples():
        lines.append(f'| {x.enveloppe} | {x.jours} | {x.decisions_differentes} | {x.perf_bot:+.1%} | {x.perf_backtest_1h:+.1%} '
                     f'| {x.dd_bot:.1%} | {x.dd_backtest_1h:.1%} |')
    ok = int(rep['decisions_differentes'].sum()) == 0
    lines += ['', f"**{'OK : le bot reproduit exactement les decisions du backtest' if ok else 'ECART : a corriger avant tout ordre'}**", '',
              '## 2. Bandes de normalite (historique oct. 2015 -> aujourd\'hui, fenetres glissantes)', '',
              'Lecture : 90 % des periodes de cette duree ont un resultat entre p5 et p95.', '']
    for name, per in bnd.items():
        lines += [f'### {name}', '', '| Duree | Rendement p5 | p25 | mediane | p75 | p95 | Periodes negatives | Pire DD p5 | DD median |',
                  '|---|---|---|---|---|---|---|---|---|']
        for label, v in per.items():
            r, d = v['rendement'], v['drawdown']
            lines.append(f"| {label} | {r['p5']:+.1%} | {r['p25']:+.1%} | {r['p50']:+.1%} | {r['p75']:+.1%} | {r['p95']:+.1%} "
                         f"| {v['part_negative']:.0%} | {d['p5']:.1%} | {d['p50']:.1%} |")
        lines.append('')
    return '\n'.join(lines), ok


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    daily = pd.DataFrame({s: fetch_btc('1d', bars=800, symbol=s)['close'] for s in ASSETS})
    hourly = {s: fetch_1h(s, bars=24 * 800) for s in ASSETS}
    rep, start = replay(daily, hourly)
    cm = pd.DataFrame({sym: fetch_daily(a) for sym, a in ASSETS.items()})
    bnd = bands(cm)
    text, ok = report(rep, start, bnd)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / 'g2_verifications.md').write_text(text)
    (REPORTS / 'g2_bandes.json').write_text(json.dumps(bnd, indent=1))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
