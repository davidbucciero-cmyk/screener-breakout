import pandas as pd
import numpy as np
import sqlite3
import logging
import os
import requests
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/congress.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

FMP_API_KEY = os.environ.get('FMP_API_KEY', '')
BASE_URL = 'https://financialmodelingprep.com/stable'
RECENCY_DAYS = 45
PAGE_LIMIT = 10  # Tier gratuit FMP : page=0 uniquement, limit max fiable = 10

def get_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('''
        SELECT DISTINCT u.ticker FROM universe u
        JOIN fundamental_signals f ON f.ticker = u.ticker
        WHERE f.fundamental_pass = 1
    ''', conn)
    conn.close()
    return set(df['ticker'].astype(str).str.upper().str.strip().tolist())

def fetch_latest(endpoint):
    if not FMP_API_KEY:
        log.error('FMP_API_KEY manquante (variable environnement non definie)')
        return []
    url = f"{BASE_URL}/{endpoint}?page=0&limit={PAGE_LIMIT}&apikey={FMP_API_KEY}"
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        data = r.json()
        log.info(f'{endpoint} : {len(data)} lignes recuperees')
        return data
    except Exception as e:
        log.error(f'Erreur {endpoint} : {e}')
        return []

def classify_type(t):
    t = str(t).lower()
    if 'purchase' in t or t == 'buy':
        return 1
    if 'sale' in t or 'sell' in t:
        return -1
    return 0

def ensure_raw_table(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS congress_raw (
            uid TEXT PRIMARY KEY,
            ticker TEXT,
            transaction_date TEXT,
            type TEXT,
            chamber TEXT,
            captured_at TEXT
        )
    ''')
    conn.commit()

def run():
    log.info('=' * 60)
    log.info('STEP 10 - SIGNAL CONGRESSIONAL TRADING (source: FMP, snapshot quotidien)')
    log.info('=' * 60)

    universe = get_universe()
    log.info(f'Univers : {len(universe)} tickers')

    senate_raw = fetch_latest('senate-latest')
    house_raw = fetch_latest('house-latest')
    all_raw = [(r, 'Senate') for r in senate_raw] + [(r, 'House') for r in house_raw]

    conn = sqlite3.connect(DB_PATH)
    ensure_raw_table(conn)

    now_str = datetime.now().isoformat()
    n_inserted = 0
    for row, chamber in all_raw:
        ticker = str(row.get('symbol', '')).upper().strip()
        tx_date = row.get('transactionDate', '')
        link = row.get('link', '')
        uid = link if link else f"{ticker}_{tx_date}_{row.get('lastName','')}_{chamber}"
        try:
            conn.execute(
                'INSERT OR IGNORE INTO congress_raw (uid, ticker, transaction_date, type, chamber, captured_at) VALUES (?, ?, ?, ?, ?, ?)',
                (uid, ticker, tx_date, row.get('type', ''), chamber, now_str)
            )
            n_inserted += conn.total_changes
        except Exception as e:
            log.error(f'Erreur insertion : {e}')
    conn.commit()
    log.info(f'Snapshot du jour ajoute a la table congress_raw (nouveaux : verifie via total_changes)')

    cutoff = datetime.now() - timedelta(days=RECENCY_DAYS)
    hist = pd.read_sql('SELECT * FROM congress_raw', conn)
    hist['transaction_date'] = pd.to_datetime(hist['transaction_date'], errors='coerce')
    hist = hist.dropna(subset=['transaction_date'])
    hist = hist[hist['transaction_date'] >= cutoff]
    hist = hist[hist['ticker'].isin(universe)]
    hist['direction'] = hist['type'].apply(classify_type)
    log.info(f'Historique accumule dans la fenetre {RECENCY_DAYS}j : {len(hist)} transactions sur univers')

    results = []
    for ticker in universe:
        sub = hist[hist['ticker'] == ticker]
        n_buy = int((sub['direction'] == 1).sum())
        n_sell = int((sub['direction'] == -1).sum())
        net_score = n_buy - n_sell
        results.append({
            'ticker': ticker,
            'congress_n_buy': n_buy,
            'congress_n_sell': n_sell,
            'congress_net_score': net_score,
            'congress_recent_flag': 1 if net_score > 0 else 0
        })

    result_df = pd.DataFrame(results)
    result_df.to_sql('congress_signals', conn, if_exists='replace', index=False)
    conn.close()

    flagged = result_df[result_df['congress_net_score'] > 0].sort_values('congress_net_score', ascending=False)
    if not flagged.empty:
        log.info(f'\nTickers avec achat net Congress recent :\n{flagged.to_string()}')
    else:
        log.info('Aucun achat net Congress recent sur univers actuel (normal les premiers jours, l\'historique s\'accumule)')

    return result_df

if __name__ == '__main__':
    run()