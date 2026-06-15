import pandas as pd
import sqlite3
import logging
import os
import requests
import time
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/reddit.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

HEADERS = {'User-Agent': 'screener-bot/1.0 by david.bucciero@outlook.fr'}
SUBREDDITS = ['smallcaps', 'investing', 'stocks', 'wallstreetbets']

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT ticker FROM universe', conn)
    conn.close()
    return df['ticker'].tolist()

def search_ticker_reddit(ticker):
    total_mentions = 0
    total_score = 0
    for sub in SUBREDDITS:
        try:
            url = f'https://www.reddit.com/r/{sub}/search.json?q={ticker}&sort=new&limit=25&t=week'
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            posts = data.get('data', {}).get('children', [])
            for post in posts:
                post_data = post.get('data', {})
                title = post_data.get('title', '').upper()
                text = post_data.get('selftext', '').upper()
                if f' {ticker} ' in f' {title} ' or f' {ticker} ' in f' {text} ':
                    total_mentions += 1
                    total_score += post_data.get('score', 0)
            time.sleep(0.5)
        except Exception as e:
            log.debug(f'Erreur Reddit {sub}/{ticker} : {e}')
    return total_mentions, total_score

def compute_zscore(value, mean, std):
    if std == 0:
        return 0
    return (value - mean) / std

def run():
    log.info('=' * 60)
    log.info('STEP 7 - REDDIT SENTIMENT')
    log.info('=' * 60)
    tickers = load_universe()
    results = []
    mentions_list = []
    for idx, ticker in enumerate(tickers):
        log.info(f'[{idx+1}/{len(tickers)}] {ticker}')
        mentions, score = search_ticker_reddit(ticker)
        mentions_list.append(mentions)
        results.append({'ticker': ticker, 'reddit_mentions': mentions, 'reddit_score': score})
        time.sleep(0.3)
    mentions_series = pd.Series(mentions_list)
    mean = mentions_series.mean()
    std = mentions_series.std()
    for r in results:
        zscore = compute_zscore(r['reddit_mentions'], mean, std)
        r['reddit_zscore'] = round(zscore, 2)
        r['reddit_signal'] = 1 if zscore >= 2 else 0
        r['updated_at'] = datetime.now().isoformat()
    df = pd.DataFrame(results)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('reddit_signals', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f'Reddit signals sauvegardes : {len(df)} tickers')
    top = df[df['reddit_mentions'] > 0].nlargest(10, 'reddit_mentions')[['ticker', 'reddit_mentions', 'reddit_zscore', 'reddit_signal']]
    if not top.empty:
        log.info(f'Top mentions Reddit :\n{top.to_string()}')
    return df

if __name__ == '__main__':
    run()