import pandas as pd
import sqlite3
import logging
import os
import requests
import time
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/insiders.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

HEADERS = {'User-Agent': 'david.bucciero@outlook.fr', 'Accept-Encoding': 'gzip, deflate'}

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def make_session():
    session = requests.Session()
    retry = Retry(total=4, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    return session

SESSION = make_session()
MIN_AMOUNT = 50000
CLUSTER_DAYS = 30
SENIOR_ROLES = ['CEO', 'CFO', 'COO', 'President', 'Chief', 'Director', 'Chairman']

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('''
        SELECT u.ticker FROM universe u
        JOIN fundamental_signals f ON f.ticker = u.ticker
        WHERE f.fundamental_pass = 1
    ''', conn)
    conn.close()
    return df['ticker'].tolist()

NET_BUY_DAYS = 90

def get_cik(ticker):
    try:
        r = SESSION.get(f'https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={ticker}&type=4&dateb=&owner=include&count=1&search_text=&action=getcompany&output=atom', headers=HEADERS, timeout=10)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        cik_el = root.find('.//{http://www.w3.org/2005/Atom}cik')
        if cik_el is not None and cik_el.text:
            return cik_el.text.strip().zfill(10)
    except Exception:
        pass
    return None

def get_form4_filings(cik, days_back=90):
    try:
        url = f'https://data.sec.gov/submissions/CIK{cik}.json'
        r = SESSION.get(url, headers=HEADERS, timeout=15)
        data = r.json()
        filings = data.get('filings', {}).get('recent', {})
        forms = filings.get('form', [])
        dates = filings.get('filingDate', [])
        accessions = filings.get('accessionNumber', [])
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
        form4s = []
        for i, form in enumerate(forms):
            if form == '4' and dates[i] >= cutoff:
                form4s.append({'date': dates[i], 'accession': accessions[i].replace('-', '')})
        return form4s
    except Exception as e:
        log.debug(f'Erreur filings CIK {cik} : {e}')
        return []

def parse_form4(cik, accession):
    try:
        url = f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/form4.xml'
        r = SESSION.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        transactions = []
        reporter_name = ''
        reporter_title = ''
        name_el = root.find('.//rptOwnerName')
        if name_el is not None:
            reporter_name = name_el.text or ''
        title_el = root.find('.//officerTitle')
        if title_el is not None:
            reporter_title = title_el.text or ''
        is_director = root.find('.//isDirector')
        is_officer = root.find('.//isOfficer')
        is_dir = is_director is not None and is_director.text == '1'
        is_off = is_officer is not None and is_officer.text == '1'
        for trans in root.findall('.//nonDerivativeTransaction'):
            code_el = trans.find('.//transactionCode')
            shares_el = trans.find('.//transactionShares/value')
            price_el = trans.find('.//transactionPricePerShare/value')
            date_el = trans.find('.//transactionDate/value')
            code = code_el.text if code_el is not None else None
            if code not in ('P', 'S'):
                continue
            try:
                shares = float(shares_el.text) if shares_el is not None else 0
                price = float(price_el.text) if price_el is not None else 0
                amount = shares * price
                date = date_el.text if date_el is not None else ''
                if amount >= MIN_AMOUNT:
                    signed_amount = amount if code == 'P' else -amount
                    transactions.append({'name': reporter_name, 'title': reporter_title, 'is_director': is_dir, 'is_officer': is_off, 'shares': shares, 'price': price, 'amount': amount, 'signed_amount': signed_amount, 'code': code, 'date': date})
            except Exception:
                continue
        return transactions
    except Exception as e:
        log.debug(f'Erreur parse form4 : {e}')
        return None

def is_senior(title):
    return any(role.lower() in title.lower() for role in SENIOR_ROLES)

def analyze_insider(ticker, all_transactions):
    if not all_transactions:
        return {'ticker': ticker, 'insider_buys': 0, 'insider_amount': 0, 'cluster_buy': 0, 'senior_buy': 0, 'insider_net_90d': 0, 'insider_net_positive': 0, 'insider_score': 0, 'updated_at': datetime.now().isoformat()}
    full_df = pd.DataFrame(all_transactions)
    full_df['date'] = pd.to_datetime(full_df['date'])
    net_cutoff = datetime.now() - timedelta(days=NET_BUY_DAYS)
    net_recent = full_df[full_df['date'] >= net_cutoff]
    insider_net_90d = net_recent['signed_amount'].sum() if not net_recent.empty else 0
    insider_net_positive = 1 if insider_net_90d > 0 else 0

    df = full_df[full_df['code'] == 'P']
    if df.empty:
        return {'ticker': ticker, 'insider_buys': 0, 'insider_amount': 0, 'cluster_buy': 0, 'senior_buy': 0, 'insider_net_90d': round(insider_net_90d, 0), 'insider_net_positive': insider_net_positive, 'insider_score': 0, 'updated_at': datetime.now().isoformat()}
    cutoff = datetime.now() - timedelta(days=CLUSTER_DAYS)
    recent = df[df['date'] >= cutoff]
    insider_buys = len(df)
    insider_amount = df['amount'].sum()
    senior_buy = 1 if any(is_senior(t) for t in df['title'].tolist()) else 0
    cluster_buy = 0
    if len(recent) >= 2:
        unique_buyers = recent['name'].nunique()
        if unique_buyers >= 2:
            cluster_buy = 1
    score = 0
    if insider_buys >= 1:
        score += 1
    if insider_buys >= 3:
        score += 1
    if insider_amount >= 100000:
        score += 1
    if insider_amount >= 500000:
        score += 1
    if senior_buy:
        score += 2
    if cluster_buy:
        score += 3
    return {'ticker': ticker, 'insider_buys': insider_buys, 'insider_amount': round(insider_amount, 0), 'cluster_buy': cluster_buy, 'senior_buy': senior_buy, 'insider_net_90d': round(insider_net_90d, 0), 'insider_net_positive': insider_net_positive, 'insider_score': min(score, 10), 'updated_at': datetime.now().isoformat()}

def run():
    log.info('=' * 60)
    log.info('STEP 3 - INSIDER BUYING (EDGAR Form 4)')
    log.info('=' * 60)
    tickers = load_universe()
    results = []
    for idx, ticker in enumerate(tickers):
        log.info(f'[{idx+1}/{len(tickers)}] {ticker}')
        try:
            cik = get_cik(ticker)
            if not cik:
                results.append(analyze_insider(ticker, []))
                continue
            time.sleep(0.3)
            filings = get_form4_filings(cik, days_back=90)
            all_transactions = []
            for filing in filings[:10]:
                time.sleep(0.2)
                txns = parse_form4(cik, filing['accession'])
                if txns:
                    all_transactions.extend(txns)
            results.append(analyze_insider(ticker, all_transactions))
        except Exception as e:
            log.error(f'Erreur {ticker} : {e}')
            results.append(analyze_insider(ticker, []))
    df = pd.DataFrame(results)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('insider_signals', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f'Insider signals sauvegardes : {len(df)} tickers')
    top = df[df['insider_score'] > 0].nlargest(10, 'insider_score')[['ticker', 'insider_score', 'insider_buys', 'cluster_buy', 'senior_buy']]
    if not top.empty:
        log.info(f'Top insiders :\n{top.to_string()}')
    return df

if __name__ == '__main__':
    run()



