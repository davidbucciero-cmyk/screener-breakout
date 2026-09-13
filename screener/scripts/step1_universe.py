import pandas as pd
import sqlite3
import logging
import os
from datetime import datetime
from openbb import obb
import yfinance as yf

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/universe.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

MKTCAP_MIN = 2_000_000_000
LARGE_CAP_THRESHOLD = 10_000_000_000
SLOPE_LOOKBACK_DAYS = 126  # ~6 mois de bourse

SECTOR_ETF = {
    'Technology': 'XLK',
    'Healthcare': 'XLV',
    'Financial Services': 'XLF',
    'Financials': 'XLF',
    'Consumer Cyclical': 'XLY',
    'Consumer Defensive': 'XLP',
    'Industrials': 'XLI',
    'Energy': 'XLE',
    'Basic Materials': 'XLB',
    'Materials': 'XLB',
    'Real Estate': 'XLRE',
    'Utilities': 'XLU',
    'Communication Services': 'XLC',
}

def get_tickers():
    log.info('Screener OpenBB (mid/large cap)...')
    df1 = obb.equity.screener(provider='yfinance', mktcap_min=MKTCAP_MIN, price_min=5.0, volume_min=300000, country='us', exchange='nms', limit=1000).to_df()
    log.info(f'NASDAQ : {len(df1)} tickers')
    df2 = obb.equity.screener(provider='yfinance', mktcap_min=MKTCAP_MIN, price_min=5.0, volume_min=300000, country='us', exchange='nyq', limit=1000).to_df()
    log.info(f'NYSE : {len(df2)} tickers')
    df = pd.concat([df1, df2]).drop_duplicates(subset='symbol')
    df['cap_bucket'] = df['market_cap'].apply(lambda m: 'large' if m and m > LARGE_CAP_THRESHOLD else 'mid')
    log.info(f'Total : {len(df)} tickers')
    return df

def get_sector_returns():
    log.info('Calcul performance sectorielle vs S&P500...')
    etfs = sorted(set(SECTOR_ETF.values())) + ['SPY']
    data = yf.download(etfs, period='1y', interval='1d', group_by='ticker', auto_adjust=True, threads=True, progress=False)
    returns = {}
    for etf in etfs:
        try:
            close = data[etf]['Close'].dropna() if etf in data.columns.get_level_values(0) else pd.Series()
            if len(close) < 130:
                continue
            ret_6m = close.iloc[-1] / close.iloc[-126] - 1
            ret_12m = close.iloc[-1] / close.iloc[0] - 1
            returns[etf] = {'ret_6m': ret_6m, 'ret_12m': ret_12m}
        except Exception as e:
            log.debug(f'Erreur ETF {etf} : {e}')
    return returns

def sector_passes(sector, sector_returns, spy):
    etf = SECTOR_ETF.get(sector)
    if not etf or etf not in sector_returns or spy is None:
        return False
    r = sector_returns[etf]
    positive_both = r['ret_6m'] > 0 and r['ret_12m'] > 0
    outperforms = r['ret_6m'] > spy['ret_6m'] or r['ret_12m'] > spy['ret_12m']
    return positive_both and outperforms

def get_sector(ticker):
    try:
        profile = obb.equity.profile(symbol=ticker, provider='yfinance').to_df()
        if profile.empty or 'sector' not in profile.columns:
            return None
        sector = profile['sector'].iloc[0]
        return sector if isinstance(sector, str) and sector else None
    except Exception as e:
        log.debug(f'Erreur profile {ticker} : {e}')
        return None

def filter_price_sector(df, sector_returns, spy):
    log.info(f'Filtre prix/MM200/secteur sur {len(df)} tickers...')
    tickers = df['symbol'].tolist()
    results = []
    unknown_sector = 0
    batch_size = 50
    total_batches = (len(tickers) + batch_size - 1) // batch_size
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        log.info(f'Batch {i//batch_size+1}/{total_batches}')
        try:
            data = yf.download(batch, period='2y', interval='1d', group_by='ticker', auto_adjust=True, threads=True, progress=False)
            for ticker in batch:
                try:
                    hist = data[ticker]['Close'].dropna() if ticker in data.columns.get_level_values(0) else pd.Series()
                    if len(hist) < 200 + SLOPE_LOOKBACK_DAYS:
                        continue
                    sma200 = hist.rolling(200).mean()
                    sma200_now = sma200.iloc[-1]
                    sma200_6m_ago = sma200.iloc[-1 - SLOPE_LOOKBACK_DAYS]
                    price = hist.iloc[-1]
                    if not (price > sma200_now and sma200_now > sma200_6m_ago):
                        continue
                    sector = get_sector(ticker)
                    if sector is None:
                        unknown_sector += 1
                        continue
                    if not sector_passes(sector, sector_returns, spy):
                        continue
                    row = df[df['symbol'] == ticker].iloc[0]
                    results.append({
                        'ticker': ticker,
                        'price': round(price, 2),
                        'volume': row.get('volume', 0),
                        'mktcap': row.get('market_cap', 0),
                        'cap_bucket': row.get('cap_bucket', 'mid'),
                        'sector': sector,
                        'sma200': round(sma200_now, 2),
                        'sma200_slope_pos': True,
                    })
                except Exception as e:
                    log.debug(f'Erreur {ticker} : {e}')
        except Exception as e:
            log.error(f'Erreur batch : {e}')
    if unknown_sector:
        log.info(f'{unknown_sector} tickers exclus (secteur non reconnu)')
    result_df = pd.DataFrame(results)
    log.info(f'Apres filtre prix/MM200/secteur : {len(result_df)} tickers')
    return result_df

def save_universe(df):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    df['updated_at'] = datetime.now().isoformat()
    df.to_sql('universe', conn, if_exists='replace', index=False)
    try:
        df.to_sql('universe_history', conn, if_exists='append', index=False)
    except Exception as e:
        log.warning(f'universe_history append echoue (schema change probable) : {e}')
    conn.close()
    log.info(f'Sauvegarde OK : {len(df)} tickers')

def run():
    log.info('=' * 60)
    log.info('STEP 1 - UNIVERS MID/LARGE CAP FILTRE')
    log.info('=' * 60)
    df = get_tickers()
    if df.empty:
        log.error('Aucun ticker recupere')
        return
    sector_returns = get_sector_returns()
    spy = sector_returns.pop('SPY', None)
    df = filter_price_sector(df, sector_returns, spy)
    if df.empty:
        log.warning('Aucun ticker retenu')
        return
    save_universe(df)
    log.info(f'RESULTAT FINAL : {len(df)} tickers')
    return df

if __name__ == '__main__':
    run()
