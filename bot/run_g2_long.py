"""Confirmation de G2 (figee : vol 19 %, memes regles) sur octobre 2015 - mars 2018, jamais utilisee.

Prix quotidiens Coin Metrics Community (PriceUSD) : BTC depuis 2010, ETH depuis aout 2015, SOL depuis 2020.
Une bougie datee d porte la cloture du jour d ; G2 decide a la cloture et applique au jour suivant,
comme avec les bougies 1h. Controle : la meme chose sur avril 2018 - sept. 2022 doit retrouver a peu
pres le resultat obtenu avec les bougies 1h de Binance.
"""
import logging
import os
from pathlib import Path

import pandas as pd
import requests

from bot.g_variants import btc_below_sma200
from bot.multi import rotation_momentum
from bot.run_g import UNSEEN
from bot.run_g2 import TARGET_VOL, _row, evaluate, gate_v2

log = logging.getLogger(__name__)
REPORT = Path(__file__).parent / 'reports' / 'g2_confirmation_2015.md'
URL = 'https://community-api.coinmetrics.io/v4/timeseries/asset-metrics'
EARLY = (pd.Timestamp('2015-10-01', tz='UTC'), UNSEEN[0])
ASSETS = {'BTCUSDT': 'btc', 'ETHUSDT': 'eth', 'SOLUSDT': 'sol'}


def parse_prices(rows, metric='PriceUSD'):
    s = pd.Series({pd.Timestamp(r['time']).tz_convert('UTC').normalize(): float(r[metric])
                   for r in rows if r.get(metric)})
    return s.sort_index()


def fetch_daily(asset, start='2010-07-01'):
    params = {'assets': asset, 'metrics': 'PriceUSD', 'frequency': '1d', 'start_time': start, 'page_size': 10000}
    js = requests.get(URL, params=params, timeout=60).json()
    rows = js['data']
    while js.get('next_page_url'):
        js = requests.get(js['next_page_url'], timeout=60).json()
        rows += js['data']
    s = parse_prices(rows)
    log.info(f'{asset} : {len(s)} jours du {s.index[0]:%Y-%m-%d} au {s.index[-1]:%Y-%m-%d}')
    return s


def as_frame(close):
    return pd.DataFrame({'open': close, 'high': close, 'low': close, 'close': close, 'volume': 0.0})


def build_report(dfs):
    r, trades = rotation_momentum(dfs, risk_off=btc_below_sma200(dfs), target_vol=TARGET_VOL)[:2]
    head = ('| Periode | Rdt annuel | Sharpe | t-stat | Max DD | Profit factor | Trades gagnants | Trades | Expo |\n'
            '|---|---|---|---|---|---|---|---|---|')
    early = evaluate(r, trades, *EARLY)
    checks, ok = gate_v2(early)
    control = evaluate(r, trades, *UNSEEN)
    full = evaluate(r, trades, EARLY[0], UNSEEN[1])
    lines = ['# G2 : confirmation sur octobre 2015 - mars 2018 (prix quotidiens Coin Metrics)', '',
             f'G2 figee : top 1 sur 30 j, cash si BTC sous sa moyenne 200 j, vol ciblee {TARGET_VOL:.0%}. '
             'Aucun parametre modifie. Avant aout 2020, rotation entre BTC et ETH seulement.',
             'Couts : 30 bps par cote (optimiste pour 2015-2017, marches bien moins liquides).', '',
             '## Resultats', '', head,
             _row(f'Oct. 2015 -> mars 2018 (jamais utilisee)', early),
             _row('Controle avr. 2018 -> sept. 2022 (prix quotidiens)', control),
             _row('Ensemble oct. 2015 -> sept. 2022 (7 ans hors echantillon)', full), '',
             'Controle attendu : proche du resultat en bougies 1h Binance sur la meme periode '
             '(Sharpe 2,03, max DD -15,5 %, profit factor 6,07).', '',
             '## Gate revise sur octobre 2015 - mars 2018', ''] + [f"- {k} : {'OK' if v else 'ECHEC'}" for k, v in checks.items()]
    lines += ['', f"**{'CONFIRME' if ok else 'NON CONFIRME'}**", '']
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).groupby(r.index.year).min()
    lines += ['## Par annee', '', '| Annee | Rendement G2 | Pire drawdown dans l\'annee |', '|---|---|---|']
    lines += [f'| {y} | {v:+.1%} | {dd[y]:.1%} |' for y, v in yearly.items() if y >= 2015]
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
