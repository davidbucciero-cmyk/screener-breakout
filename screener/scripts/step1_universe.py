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

def get_tickers():
    log.info('Screener OpenBB...')
    df1 = obb.equity.screener(provider='yfinance', mktcap_min=300000000, mktcap_max=2000000000, price_min=5.0, volume_min=500000, country='us', exchange='nms', limit=500).to_df()
    log.info(f'NASDAQ : {len(df1)} tickers')
    df2 = obb.equity.screener(provider='yfinance', mktcap_min=300000000, mktcap_max=2000000000, price_min=5.0, volume_min=500000, country='us', exchange='nyq', limit=500).to_df()
    log.info(f'NYSE : {len(df2)} tickers')
    df = pd.concat([df1, df2]).drop_duplicates(subset='symbol')
    log.info(f'Total : {len(df)} tickers')
    return df

def prefilter_sma(df):
    log.info(f'Calcul SMA sur {len(df)} tickers...')
    tickers = df['symbol'].tolist()
    results = []
    batch_size = 50
    total_batches = (len(tickers) + batch_size - 1) // batch_size
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        log.info(f'Batch {i//batch_size+1}/{total_batches}')
        try:
            data = yf.download(batch, period='1y', interval='1d', group_by='ticker', auto_adjust=True, threads=True, progress=False)
            for ticker in batch:
                try:
                    hist = data[ticker]['Close'].dropna() if ticker in data.columns.get_level_values(0) else pd.Series()
                    if len(hist) < 50:
                        continue
                    sma50 = hist.tail(50).mean()
                    sma200 = hist.tail(200).mean() if len(hist) >= 200 else None
                    if sma200 and sma50 <= sma200:
                        continue
                    row = df[df['symbol'] == ticker].iloc[0]
                    results.append({'ticker': ticker, 'price': row.get('price', 0), 'volume': row.get('volume', 0), 'mktcap': row.get('market_cap', 0), 'sma50': round(sma50, 2), 'sma200': round(sma200, 2) if sma200 else None, 'golden_cross': True})
                except Exception as e:
                    log.debug(f'Erreur {ticker} : {e}')
        except Exception as e:
            log.error(f'Erreur batch : {e}')
    result_df = pd.DataFrame(results)
    log.info(f'Apres filtre SMA : {len(result_df)} tickers')
    return result_df

def save_universe(df):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    df['updated_at'] = datetime.now().isoformat()
    df.to_sql('universe', conn, if_exists='replace', index=False)
    df.to_sql('universe_history', conn, if_exists='append', index=False)
    conn.close()
    log.info(f'Sauvegarde OK : {len(df)} tickers')

def run():
    log.info('=' * 60)
    log.info('STEP 1 - UNIVERS SMALL CAPS FILTRE')
    log.info('=' * 60)
    df = get_tickers()
    if df.empty:
        log.error('Aucun ticker recupere')
        return
    df = prefilter_sma(df)
    if df.empty:
        log.warning('Aucun ticker retenu')
        return
    save_universe(df)
    log.info(f'RESULTAT FINAL : {len(df)} tickers')
    return df

if __name__ == '__main__':
    run()