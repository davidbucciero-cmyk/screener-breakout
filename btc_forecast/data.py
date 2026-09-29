import logging
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)

# data-api.binance.vision : miroir public des donnees de marche Binance.
# api.binance.com renvoie 451 depuis les IP US (runners GitHub Actions).
BINANCE_URLS = [
    'https://data-api.binance.vision/api/v3/klines',
    'https://api.binance.com/api/v3/klines',
]
COINBASE_URL = 'https://api.exchange.coinbase.com/products/{product}/candles'
INTERVAL_MS = {'1h': 3_600_000, '1d': 86_400_000}


def _get(url, params, retries=3):
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            log.warning(f'{url} : {e} - retry {attempt + 1}/{retries}')
            time.sleep(2 ** attempt)


def _fetch_binance(url, symbol, interval, bars):
    step = INTERVAL_MS[interval]
    end = int(time.time() * 1000)
    start = end - bars * step
    rows = []
    while start < end:
        batch = _get(url, {'symbol': symbol, 'interval': interval, 'startTime': start, 'limit': 1000})
        if not batch:
            break
        rows.extend(batch)
        start = batch[-1][0] + step
        if len(batch) < 1000:
            break
    df = pd.DataFrame(rows, columns=['open_time', 'open', 'high', 'low', 'close', 'volume',
                                     'close_time', 'qav', 'trades', 'tbbav', 'tbqav', 'ignore'])
    df = df[['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time']]
    # La derniere bougie renvoyee est encore ouverte : on ne garde que les bougies cloturees.
    df = df[df['close_time'] < int(time.time() * 1000)]
    df['time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    return df.drop(columns=['open_time', 'close_time'])


def _fetch_coinbase(interval, bars, symbol):
    product = symbol.replace('USDT', '') + '-USD'  # BTCUSDT -> BTC-USD
    step = pd.Timedelta(milliseconds=INTERVAL_MS[interval])
    end = pd.Timestamp.now(tz='UTC').floor(step)
    start = end - bars * step
    rows = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + 300 * step, end)
        batch = _get(COINBASE_URL.format(product=product), {'granularity': int(step.total_seconds()), 'start': cursor.isoformat(),
                                    'end': chunk_end.isoformat()})
        rows.extend(batch)
        cursor = chunk_end
        time.sleep(0.2)
    df = pd.DataFrame(rows, columns=['ts', 'low', 'high', 'open', 'close', 'volume'])
    df['time'] = pd.to_datetime(df['ts'], unit='s', utc=True)
    # Bougie en cours (ouverte a `end`) exclue.
    df = df[df['time'] < end]
    return df.drop(columns=['ts'])[['open', 'high', 'low', 'close', 'volume', 'time']]


def fetch_btc_1h(hours=24 * 365, symbol='BTCUSDT'):
    return fetch_btc('1h', hours, symbol)


def fetch_btc(interval='1h', bars=24 * 365, symbol='BTCUSDT'):
    """Bougies cloturees ('1h' ou '1d'), triees, dedoublonnees. Index = heure d'ouverture (UTC)."""
    df = None
    for url in BINANCE_URLS:
        try:
            df = _fetch_binance(url, symbol, interval, bars)
            log.info(f'{len(df)} bougies {interval} depuis {url}')
            break
        except requests.RequestException as e:
            log.warning(f'Binance indisponible ({url}) : {e}')
    if df is None or df.empty:
        df = _fetch_coinbase(interval, bars, symbol)
        log.info(f'{len(df)} bougies {interval} depuis Coinbase (fallback)')
    df = df.drop_duplicates('time').sort_values('time').set_index('time')
    df = df.astype(float)
    gaps = df.index.to_series().diff().dropna() != pd.Timedelta(milliseconds=INTERVAL_MS[interval])
    if gaps.any():
        log.warning(f'{int(gaps.sum())} trous dans la serie {interval}')
    return df


STOOQ_URL = 'https://stooq.com/q/d/l/'


def _fetch_etf_yahoo(symbol):
    import yfinance as yf
    df = yf.Ticker(symbol).history(period='max', interval='1d', auto_adjust=True)  # ajuste dividendes
    if df.empty:
        raise ValueError(f'yfinance : aucune donnee pour {symbol}')
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].rename(columns=str.lower)
    df.index = pd.to_datetime(df.index.date).tz_localize('UTC')
    return df


def _fetch_etf_stooq(symbol):
    import io
    r = requests.get(STOOQ_URL, params={'s': f'{symbol.lower()}.us', 'i': 'd'}, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    if 'Close' not in df:
        raise ValueError(f'Stooq : reponse inattendue pour {symbol}')
    df = df.rename(columns=str.lower).set_index('date')
    df.index = pd.to_datetime(df.index).tz_localize('UTC')
    return df[['open', 'high', 'low', 'close', 'volume']]


def fetch_daily(symbol, bars=4000):
    """Bougies journalieres cloturees sur calendrier continu (7 j/7), colonne `trading` en plus.

    Crypto (…USDT) : Binance, tous les jours sont tradables.
    ETF/actions : Yahoo (ajuste des dividendes), fallback Stooq ; les week-ends et jours feries sont
    remplis avec la derniere cloture (rendement nul) et marques trading=False. Ainsi toutes les series
    partagent le meme calendrier, et vol 30 j x sqrt(365) reste une vol annuelle correcte.
    """
    if symbol.upper().endswith('USDT'):
        df = fetch_btc('1d', bars=bars, symbol=symbol)
        df['trading'] = True
        return df
    try:
        df = _fetch_etf_yahoo(symbol)
        log.info(f'{len(df)} seances {symbol} depuis Yahoo Finance')
    except Exception as e:
        log.warning(f'Yahoo indisponible pour {symbol} ({e}), fallback Stooq (non ajuste des dividendes)')
        df = _fetch_etf_stooq(symbol)
        log.info(f'{len(df)} seances {symbol} depuis Stooq')
    return to_calendar(df, pd.Timestamp.now(tz='UTC').normalize()).iloc[-bars:]


def to_calendar(df, today):
    """Seances de bourse -> calendrier continu jusqu'a hier ; jours sans seance = derniere cloture."""
    df = df[~df.index.duplicated()].sort_index()
    df = df[df.index < today].astype(float)  # seance du jour eventuellement incomplete
    calendar = pd.date_range(df.index[0], today - pd.Timedelta(days=1), freq='D')
    out = df.reindex(calendar)
    out['trading'] = out['close'].notna()
    out['close'] = out['close'].ffill()
    for col in ('open', 'high', 'low'):
        out[col] = out[col].fillna(out['close'])
    if 'volume' in out:
        out['volume'] = out['volume'].fillna(0.0)
    return out
