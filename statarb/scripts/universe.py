import os
import logging
from io import StringIO
import pandas as pd
import requests
import yfinance as yf

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/universe.log')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

PRICES_PATH = os.path.join(DATA_DIR, 'prices.csv')

# Univers restreint par secteur : les paires ne sont testees qu'a l'interieur
# d'un meme secteur (les series ont plus de chances de partager un facteur
# commun, condition necessaire a une relation de cointegration stable).
SECTOR_UNIVERSE = {
    'Energy': ['XOM', 'CVX', 'COP', 'SLB', 'OXY'],
    'Banks': ['JPM', 'BAC', 'WFC', 'C', 'USB'],
    'Payments': ['V', 'MA', 'AXP'],
    'ConsumerStaples': ['KO', 'PEP', 'PG', 'CL', 'KMB'],
    'Retail': ['HD', 'LOW', 'TGT', 'WMT'],
    'Pharma': ['JNJ', 'PFE', 'MRK', 'ABBV', 'LLY'],
    'Semis': ['NVDA', 'AMD', 'INTC', 'TXN', 'QCOM'],
    'MegaTech': ['MSFT', 'GOOGL', 'META', 'AAPL'],
    'Industrials': ['HON', 'MMM', 'GE', 'CAT', 'DE'],
    'Telecom': ['VZ', 'T', 'TMUS'],
}

LOOKBACK_PERIOD = '10y'
MIN_HISTORY_DAYS = 500

SP500_WIKI_URL = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'


def all_tickers():
    seen = []
    for tickers in SECTOR_UNIVERSE.values():
        for t in tickers:
            if t not in seen:
                seen.append(t)
    return seen


def sp500_tickers():
    """Liste des ~500 tickers du S&P 500, recuperee depuis Wikipedia (symboles
    normalises pour yfinance, ex. BRK.B -> BRK-B). Retombe sur `all_tickers()`
    (univers restreint sectoriel) si la page n'est pas accessible."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; screener-breakout/1.0)'}
        resp = requests.get(SP500_WIKI_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        table = pd.read_html(StringIO(resp.text))[0]
        tickers = table['Symbol'].str.replace('.', '-', regex=False).tolist()
        log.info(f'{len(tickers)} tickers S&P 500 recuperes depuis Wikipedia')
        return tickers
    except Exception as e:
        log.warning(f'Echec recuperation S&P 500 ({e}), repli sur l\'univers sectoriel restreint')
        return all_tickers()


def fetch_prices(tickers=None, period=LOOKBACK_PERIOD):
    tickers = tickers or sp500_tickers()
    log.info(f'Telechargement prix ajustes ({period}) pour {len(tickers)} tickers...')
    raw = yf.download(tickers, period=period, interval='1d', group_by='ticker',
                       auto_adjust=True, threads=True, progress=False)

    prices = {}
    for t in tickers:
        try:
            close = raw[t]['Close'].dropna() if t in raw.columns.get_level_values(0) else pd.Series(dtype=float)
        except KeyError:
            close = pd.Series(dtype=float)
        if len(close) < MIN_HISTORY_DAYS:
            continue
        prices[t] = close

    if not prices:
        log.error('Aucun ticker avec historique suffisant')
        return pd.DataFrame()

    df = pd.DataFrame(prices).sort_index()
    # Comble les trous ponctuels (jours feries locaux, etc.), puis ecarte les
    # tickers dont l'historique reste incomplet plutot que de supprimer des
    # journees entieres pour tout l'univers a cause d'un seul titre lacunaire.
    df = df.ffill(limit=3)
    n_before = df.shape[1]
    df = df.dropna(axis=1)
    if df.shape[1] < n_before:
        log.warning(f'{n_before - df.shape[1]} tickers exclus (historique lacunaire apres ffill)')
    df = df.dropna(axis=0)
    log.info(f'Prix retenus : {df.shape[1]} tickers x {df.shape[0]} jours ({df.index.min().date()} -> {df.index.max().date()})')
    return df


def save_prices(df):
    df.to_csv(PRICES_PATH)
    log.info(f'Sauvegarde : {PRICES_PATH}')


def load_prices():
    if not os.path.exists(PRICES_PATH):
        return pd.DataFrame()
    return pd.read_csv(PRICES_PATH, index_col=0, parse_dates=True)


def run():
    log.info('=' * 60)
    log.info('UNIVERS STAT-ARB - TELECHARGEMENT PRIX')
    log.info('=' * 60)
    df = fetch_prices()
    if df.empty:
        return df
    save_prices(df)
    return df


if __name__ == '__main__':
    run()
