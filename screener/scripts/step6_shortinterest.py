import pandas as pd
import sqlite3
import logging
import os
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/shortinterest.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('''
        SELECT u.ticker FROM universe u
        JOIN fundamental_signals f ON f.ticker = u.ticker
        WHERE f.fundamental_pass = 1
    ''', conn)
    conn.close()
    return df['ticker'].tolist()

def get_short_interest(ticker):
    try:
        url = f'https://finviz.com/quote.ashx?t={ticker}'
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', class_='snapshot-table2')
        if not table:
            table = soup.find('table', {'class': lambda x: x and 'snapshot' in x})
        if not table:
            return None
        cells = table.find_all('td')
        data = {}
        for i in range(0, len(cells)-1, 2):
            key = cells[i].text.strip()
            val = cells[i+1].text.strip()
            data[key] = val
        short_float = data.get('Short Float', '0%').replace('%', '').replace(',', '')
        short_ratio = data.get('Short Ratio', '0').replace(',', '')
        try:
            short_float = float(short_float)
        except Exception:
            short_float = 0
        try:
            short_ratio = float(short_ratio)
        except Exception:
            short_ratio = 0
        score = 0
        if short_float >= 10:
            score += 2
        if short_float >= 20:
            score += 1
        if short_ratio >= 5:
            score += 2
        return {'ticker': ticker, 'short_float': short_float, 'short_ratio': short_ratio, 'short_score': min(score, 5), 'updated_at': datetime.now().isoformat()}
    except Exception as e:
        log.debug(f'Erreur {ticker} : {e}')
        return None

def run():
    log.info('=' * 60)
    log.info('STEP 6 - SHORT INTEREST (Finviz)')
    log.info('=' * 60)
    tickers = load_universe()
    results = []
    for idx, ticker in enumerate(tickers):
        log.info(f'[{idx+1}/{len(tickers)}] {ticker}')
        result = get_short_interest(ticker)
        if result:
            results.append(result)
        else:
            results.append({'ticker': ticker, 'short_float': 0, 'short_ratio': 0, 'short_score': 0, 'updated_at': datetime.now().isoformat()})
        time.sleep(0.5)
    df = pd.DataFrame(results)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('short_signals', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f'Short interest sauvegarde : {len(df)} tickers')
    top = df[df['short_float'] >= 10].nlargest(10, 'short_float')[['ticker', 'short_float', 'short_ratio', 'short_score']]
    if not top.empty:
        log.info(f'Top short interest :\n{top.to_string()}')
    return df

if __name__ == '__main__':
    run()