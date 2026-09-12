import pandas as pd
import sqlite3
import logging
import os
from datetime import datetime
from openbb import obb

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/institutional.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

QOQ_TARGET_DAYS = 90
QOQ_TOLERANCE_DAYS = 20

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('''
        SELECT u.ticker FROM universe u
        JOIN fundamental_signals f ON f.ticker = u.ticker
        WHERE f.fundamental_pass = 1
    ''', conn)
    conn.close()
    return df['ticker'].tolist()

def ensure_raw_table(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS institutional_raw (
            ticker TEXT,
            institution_ownership REAL,
            captured_at TEXT
        )
    ''')
    conn.commit()

def get_institutional_ownership(ticker):
    try:
        df = obb.equity.ownership.share_statistics(symbol=ticker, provider='yfinance').to_df()
        if df.empty or 'institution_ownership' not in df.columns:
            return None
        val = df['institution_ownership'].iloc[0]
        return float(val) if pd.notna(val) else None
    except Exception as e:
        log.debug(f'Erreur share_statistics {ticker} : {e}')
        return None

def run():
    log.info('=' * 60)
    log.info('STEP 11 - INSTITUTIONNELS (13F / detention, snapshot quotidien)')
    log.info('=' * 60)
    tickers = load_universe()
    if not tickers:
        log.warning('Aucun ticker fondamentalement valide - rien a calculer')
        return

    conn = sqlite3.connect(DB_PATH)
    ensure_raw_table(conn)
    now_str = datetime.now().isoformat()

    snapshot = []
    for idx, ticker in enumerate(tickers):
        log.info(f'[{idx+1}/{len(tickers)}] {ticker}')
        ownership = get_institutional_ownership(ticker)
        if ownership is not None:
            conn.execute(
                'INSERT INTO institutional_raw (ticker, institution_ownership, captured_at) VALUES (?, ?, ?)',
                (ticker, ownership, now_str)
            )
            snapshot.append({'ticker': ticker, 'institution_ownership': ownership})
    conn.commit()

    hist = pd.read_sql('SELECT * FROM institutional_raw', conn)
    hist['captured_at'] = pd.to_datetime(hist['captured_at'], errors='coerce')
    hist = hist.dropna(subset=['captured_at'])
    now = pd.Timestamp(datetime.now())

    results = []
    has_enough_history = False
    for row in snapshot:
        ticker = row['ticker']
        current = row['institution_ownership']
        sub = hist[hist['ticker'] == ticker].copy()
        sub['age_days'] = (now - sub['captured_at']).dt.days
        candidates = sub[(sub['age_days'] >= QOQ_TARGET_DAYS - QOQ_TOLERANCE_DAYS) & (sub['age_days'] <= QOQ_TARGET_DAYS + QOQ_TOLERANCE_DAYS)]
        institutional_trend = 0
        past_value = None
        if not candidates.empty:
            has_enough_history = True
            closest = candidates.iloc[(candidates['age_days'] - QOQ_TARGET_DAYS).abs().argsort()[:1]]
            past_value = float(closest['institution_ownership'].iloc[0])
            institutional_trend = 1 if current > past_value else 0
        results.append({
            'ticker': ticker,
            'institution_ownership': current,
            'institution_ownership_90d_ago': past_value,
            'institutional_trend': institutional_trend,
        })

    result_df = pd.DataFrame(results)
    result_df['updated_at'] = now_str
    result_df.to_sql('institutional_signals', conn, if_exists='replace', index=False)
    conn.close()

    if not has_enough_history:
        log.info("Pas encore ~90 jours d'historique accumule - institutional_trend a 0 par defaut (normal les premieres semaines)")
    n_trend = int(result_df['institutional_trend'].sum())
    log.info(f'Institutionnels sauvegardes : {len(result_df)} tickers - {n_trend} en hausse QoQ')
    return result_df

if __name__ == '__main__':
    run()
