"""Blocs de donnees quotidiennes pour la recherche d'edge (toutes sources publiques, sans cle).

Chaque fetcher renvoie une Series ou un DataFrame quotidien indexe en UTC (minuit). Une valeur datee
du jour d est consideree connue a la cloture de d ; les features les decaleront d'un jour de plus
quand la source publie avec retard (macro US, on-chain).
"""
import io
import logging
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)
UA = {'User-Agent': 'screener-breakout-research/1.0'}


def _get(url, params=None, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=60)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.warning(f'{url} : {e} - retry')
            time.sleep(2 ** attempt)


def _daily_index(ts, unit=None):
    return pd.DatetimeIndex(pd.to_datetime(ts, unit=unit, utc=True)).normalize()


def parse_fear_greed(js):
    d = js['data']
    return pd.Series([float(x['value']) for x in d], index=_daily_index([int(x['timestamp']) for x in d], 's'),
                     name='fear_greed').sort_index()


def fear_greed():
    return parse_fear_greed(_get('https://api.alternative.me/fng/', {'limit': 0, 'format': 'json'}).json())


def parse_stablecoins(js):
    return pd.Series([float(x['totalCirculatingUSD']['peggedUSD']) for x in js],
                     index=_daily_index([int(x['date']) for x in js], 's'), name='stablecoins_usd').sort_index()


def stablecoins():
    return parse_stablecoins(_get('https://stablecoins.llama.fi/stablecoincharts/all').json())


def parse_tvl(js):
    return pd.Series([float(x['tvl']) for x in js], index=_daily_index([int(x['date']) for x in js], 's'),
                     name='defi_tvl').sort_index()


def defi_tvl():
    return parse_tvl(_get('https://api.llama.fi/v2/historicalChainTvl').json())


def dvol(start='2021-03-24'):
    """Indice de volatilite implicite BTC de Deribit (cloture quotidienne)."""
    url = 'https://www.deribit.com/api/v2/public/get_volatility_index_data'
    end = int(time.time() * 1000)
    cursor = int(pd.Timestamp(start, tz='UTC').timestamp() * 1000)
    rows = []
    while cursor < end:
        chunk_end = min(cursor + 900 * 86_400_000, end)
        res = _get(url, {'currency': 'BTC', 'start_timestamp': cursor, 'end_timestamp': chunk_end,
                         'resolution': '1D'}).json()['result']
        rows += res['data']
        cursor = chunk_end + 1
        time.sleep(0.5)
    s = pd.Series({_daily_index([r[0]], 'ms')[0]: float(r[4]) for r in rows}, name='dvol').sort_index()
    return s[~s.index.duplicated()]


ONCHAIN_METRICS = ['AdrActCnt', 'TxCnt', 'HashRate', 'CapMVRVCur', 'FlowInExUSD', 'FlowOutExUSD']


def onchain(start='2017-01-01'):
    """Coin Metrics Community : les metriques non gratuites sont ignorees une par une."""
    url = 'https://community-api.coinmetrics.io/v4/timeseries/asset-metrics'
    out = {}
    for m in ONCHAIN_METRICS:
        try:
            rows, params = [], {'assets': 'btc', 'metrics': m, 'frequency': '1d', 'start_time': start,
                                'page_size': 10000}
            js = _get(url, params).json()
            rows += js['data']
            while js.get('next_page_url'):
                js = _get(js['next_page_url']).json()
                rows += js['data']
            out[m] = pd.Series({pd.Timestamp(r['time']).normalize(): float(r[m]) for r in rows if r.get(m)})
        except Exception as e:
            log.warning(f'Coin Metrics {m} indisponible : {e}')
    return pd.DataFrame(out).sort_index()


FRED = {'nasdaq': 'NASDAQCOM', 'dollar': 'DTWEXBGS', 'taux_10a': 'DGS10', 'or': 'GOLDAMGBD228NLBM'}


def parse_fred_csv(text, name):
    df = pd.read_csv(io.StringIO(text))
    df.columns = ['date', name]
    s = pd.to_numeric(df[name], errors='coerce')
    return pd.Series(s.to_numpy(), index=_daily_index(df['date']), name=name).dropna()


def macro():
    out = {}
    for name, sid in FRED.items():
        try:
            text = _get('https://fred.stlouisfed.org/graph/fredgraph.csv', {'id': sid}).text
            out[name] = parse_fred_csv(text, name)
        except Exception as e:
            log.warning(f'FRED {sid} indisponible : {e}')
    return pd.DataFrame(out).sort_index()


def funding_daily():
    from bot.funding import fetch_funding
    return fetch_funding('2017-01-01').resample('1D').mean().rename('funding')


BLOCKS = {
    '5 - Funding perpetuel BTC (BitMEX)': funding_daily,
    '7 - Volatilite implicite DVOL (Deribit)': dvol,
    '8 - On-chain BTC (Coin Metrics)': onchain,
    '9 - Offre de stablecoins (DefiLlama)': stablecoins,
    '10 - TVL DeFi (DefiLlama)': defi_tvl,
    '12 - Fear & Greed (alternative.me)': fear_greed,
    '16 - Macro US (FRED)': macro,
}
