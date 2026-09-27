import os
import logging
import pandas as pd
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

LOOKBACK_PERIOD = '3y'
MIN_HISTORY_DAYS = 500


def all_tickers():
    seen = []
    for tickers in SECTOR_UNIVERSE.values():
        for t in tickers:
            if t not in seen:
                seen.append(t)
    return seen


def fetch_prices(tickers=None, period=LOOKBACK_PERIOD):
    tickers = tickers or all_tickers()
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
            log.warning(f'{t} exclu : seulement {len(close)} jours d\'historique')
            continue
        prices[t] = close

    if not prices:
        log.error('Aucun ticker avec historique suffisant')
        return pd.DataFrame()

    df = pd.DataFrame(prices).sort_index()
    df = df.ffill(limit=3).dropna()
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
