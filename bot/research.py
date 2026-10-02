"""Etape 2 de la recherche : pouvoir predictif de chaque bloc, seul, sur la periode de DEV uniquement.

Cible : rendement log de BTC de la cloture du jour d a la cloture de d+7.
Mesure : correlation de rang (IC) entre la feature connue a la cloture de d et cette cible, calculee
sur des echantillons hebdomadaires non chevauchants (sinon la t-stat est gonflee), puis par annee
pour verifier la stabilite du signe. Les deux dernieres annees (hors echantillon) ne sont JAMAIS lues ici.
"""
import logging
import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / 'data'
REPORT = Path(__file__).parent / 'reports' / 'research_ic.md'
OOS_START = pd.Timestamp('2024-10-02', tz='UTC')  # meme coupure que le backtest
HORIZON = 7
PUBLICATION_LAG = {'8': 1, '16': 1}  # on-chain et macro US : publies le lendemain


def _load(block):
    path = DATA / f'{block}.csv'
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.DatetimeIndex(df.index).tz_convert('UTC') if df.index.tz else pd.DatetimeIndex(df.index).tz_localize('UTC')
    return df.shift(PUBLICATION_LAG.get(block, 0), freq='D')


def _growth(s, n):
    return s / s.shift(n) - 1


def build_features(btc_close):
    """Features quotidiennes, chacune connue a la cloture du jour d."""
    idx = btc_close.index
    f = pd.DataFrame(index=idx)
    r = np.log(btc_close).diff()
    f['prix_mom_30j'] = _growth(btc_close, 30)
    f['prix_mom_90j'] = _growth(btc_close, 90)
    f['prix_vol_30j'] = r.rolling(30).std() * math.sqrt(365)

    def daily(block, col=None):
        df = _load(block)
        if df is None or (col and col not in df):
            return None
        s = df[col] if col else df.iloc[:, 0]
        return s.reindex(idx, method='ffill', limit=5)

    fund = daily('5')
    if fund is not None:
        f['funding_7j'] = fund.rolling(7).mean()
        f['funding_z_365j'] = (f['funding_7j'] - f['funding_7j'].rolling(365, min_periods=180).mean()) \
            / f['funding_7j'].rolling(365, min_periods=180).std()
    dv = daily('7')
    if dv is not None:
        f['dvol'] = dv
        f['dvol_var_7j'] = dv - dv.shift(7)
        f['prime_vol_implicite'] = dv / 100 - f['prix_vol_30j']
    for col, name in [('AdrActCnt', 'adresses_actives'), ('TxCnt', 'transactions'), ('HashRate', 'hashrate')]:
        s = daily('8', col)
        if s is not None:
            f[f'{name}_croiss_30j'] = _growth(s.rolling(7).mean(), 30)
    mvrv = daily('8', 'CapMVRVCur')
    if mvrv is not None:
        f['mvrv'] = mvrv
    fin, fout = daily('8', 'FlowInExUSD'), daily('8', 'FlowOutExUSD')
    if fin is not None and fout is not None:
        f['flux_net_exchanges_7j'] = (fin - fout).rolling(7).sum() / (fin + fout).rolling(7).sum()
    st = daily('9')
    if st is not None:
        f['stablecoins_croiss_30j'] = _growth(st, 30)
    tvl = daily('10')
    if tvl is not None:
        f['tvl_croiss_30j'] = _growth(tvl, 30)
    fg = daily('12')
    if fg is not None:
        f['fear_greed'] = fg
        f['fear_greed_var_7j'] = fg - fg.shift(7)
    for col, name, fn in [('nasdaq', 'nasdaq_mom_20j', _growth), ('dollar', 'dollar_mom_20j', _growth),
                          ('or', 'or_mom_20j', _growth)]:
        s = daily('16', col)
        if s is not None:
            f[name] = fn(s, 20)
    ty = daily('16', 'taux_10a')
    if ty is not None:
        f['taux_10a_var_20j'] = ty - ty.shift(20)
    return f


def target(btc_close):
    return np.log(btc_close.shift(-HORIZON) / btc_close)


def _spearman(a, b):
    m = a.notna() & b.notna()
    if m.sum() < 20:
        return float('nan'), int(m.sum())
    return float(a[m].rank().corr(b[m].rank())), int(m.sum())


def information_coefficients(features, y):
    """IC sur echantillons hebdomadaires (dimanches), periode de dev uniquement."""
    dev = features.index < OOS_START - pd.Timedelta(days=HORIZON)  # la cible ne deborde pas dans le hors echantillon
    feats, yy = features[dev], y[dev]
    weekly = feats.index.dayofweek == 6
    rows = []
    for col in feats.columns:
        ic, n = _spearman(feats.loc[weekly, col], yy[weekly])
        t = ic * math.sqrt((n - 2) / (1 - ic ** 2)) if n > 2 and abs(ic) < 1 else float('nan')
        by_year = {}
        for year, g in feats.loc[weekly].groupby(feats.index[weekly].year):
            by_year[year] = _spearman(g[col], yy.loc[g.index])[0]
        signs = [np.sign(v) for v in by_year.values() if not np.isnan(v)]
        same = sum(s == np.sign(ic) for s in signs) if signs else 0
        first = feats[col].first_valid_index()
        rows.append({'feature': col, 'debut': f'{first:%Y-%m}' if first is not None else '-', 'semaines': n,
                     'ic': ic, 't_stat': t, 'annees_meme_signe': f'{same}/{len(signs)}',
                     **{str(y_): v for y_, v in by_year.items()}})
    return pd.DataFrame(rows).sort_values('t_stat', key=lambda s: s.abs(), ascending=False)


def report(table):
    years = [c for c in table.columns if c.isdigit()]
    head = '| Feature | Depuis | Semaines | IC | t-stat | Annees meme signe | ' + ' | '.join(years) + ' |'
    lines = ['# Pouvoir predictif de chaque bloc (periode de dev uniquement)', '',
             f'Cible : rendement BTC a {HORIZON} jours. IC = correlation de rang, echantillons hebdomadaires '
             f'non chevauchants, donnees avant le {OOS_START:%Y-%m-%d} uniquement.',
             f'Avec {len(table)} features testees, un |t| > {_bonferroni(len(table)):.2f} est requis pour ecarter le hasard.',
             '', head, '|' + '---|' * (6 + len(years))]
    for r in table.itertuples(index=False):
        d = r._asdict()
        yrs = ' | '.join('' if pd.isna(d[y]) else f'{d[y]:+.2f}' for y in years)
        lines.append(f"| {d['feature']} | {d['debut']} | {d['semaines']} | {d['ic']:+.3f} | {d['t_stat']:+.2f} "
                     f"| {d['annees_meme_signe']} | {yrs} |")
    return '\n'.join(lines) + '\n'


def _bonferroni(n, base=2.0):
    from statistics import NormalDist
    alpha = 2 * (1 - NormalDist().cdf(base))
    return NormalDist().inv_cdf(1 - alpha / (2 * n))


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    from btc_forecast.data import fetch_btc
    btc = fetch_btc('1d', bars=3300)['close']
    btc.index = btc.index.normalize()
    table = information_coefficients(build_features(btc), target(btc))
    text = report(table.rename(columns=lambda c: str(c)))
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
