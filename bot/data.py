"""Bougies 1h BTC/USDT cloturees depuis Binance, avec le volume acheteur taker (flux d'ordres)."""
import logging
import time

import pandas as pd
import requests

from btc_forecast.data import BINANCE_URLS, _get

log = logging.getLogger(__name__)
STEP_MS = 3_600_000


def fetch_1h(symbol='BTCUSDT', bars=24 * 365 * 4):
    end = int(time.time() * 1000)
    for url in BINANCE_URLS:
        try:
            rows, start = [], end - bars * STEP_MS
            while start < end:
                batch = _get(url, {'symbol': symbol, 'interval': '1h', 'startTime': start, 'limit': 1000})
                if not batch:
                    break
                rows.extend(batch)
                start = batch[-1][0] + STEP_MS
            break
        except requests.RequestException as e:
            log.warning(f'{url} indisponible : {e}')
    else:
        raise RuntimeError('Binance indisponible')
    df = pd.DataFrame(rows, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
                                     'qav', 'trades', 'taker_buy_volume', 'tbqav', 'ignore'])
    df = df[df['close_time'] < int(time.time() * 1000)]  # bougie en cours exclue
    df['time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df = df.drop_duplicates('time').set_index('time').sort_index()
    df = df[['open', 'high', 'low', 'close', 'volume', 'taker_buy_volume']].astype(float)
    full = pd.date_range(df.index[0], df.index[-1], freq='h')
    missing = len(full) - len(df)
    if missing:
        log.warning(f'{missing} bougies manquantes, remplies a plat (volume 0)')
        df = df.reindex(full)
        df['close'] = df['close'].ffill()
        for c in ('open', 'high', 'low'):
            df[c] = df[c].fillna(df['close'])
        df[['volume', 'taker_buy_volume']] = df[['volume', 'taker_buy_volume']].fillna(0.0)
    log.info(f'{len(df)} bougies 1h {symbol} du {df.index[0]} au {df.index[-1]}')
    return df
