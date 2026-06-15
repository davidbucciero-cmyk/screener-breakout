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
MIN_AMOUNT = 50000
CLUSTER_DAYS = 30
SENIOR_ROLES = ['CEO', 'CFO', 'COO', 'President', 'Chief', 'Director', 'Chairman']

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT ticker FROM universe', conn)
    conn.close()
    return df['ticker'].tolist()

def get_cik(ticker):
    try:
        r = requests.get(f'https://www.sec.gov/cgi-bin/browse-edgar?company=&CIK={ticker}&type=4&dateb=&owner=include&count=1&search_text=&action=getcompany&output=atom', headers=HEADERS, timeout=10)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('atom:entry', ns):
            link = entry.find('atom:link', ns)
            if link is not None:
                href = link.get('href', '')
                if '/cgi-bin/browse-edgar?action=getcompany&CIK=' in href:
                    cik = href.split('CIK=')[1].split('&')[0]
                    return cik.zfill(10)
    except Exception:
        pass
    return None

def get_form4_filings(cik, days_back=90):
    try:
        url = f'https://data.sec.gov/submissions/CIK{cik}.json'
        r = requests.get(url, headers=HEADERS, timeout=15)
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
        r = requests.get(url, headers=HEADERS, timeout=10)
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
            if code_el is None or code_el.text != 'P':
                continue
            try:
                shares = float(shares_el.text) if shares_el is not None else 0
                price = float(price_el.text) if price_el is not None else 0
                amount = shares * price
                date = date_el.text if date_el is not None else ''
                if amount >= MIN_AMOUNT:
                    transactions.append({'name': reporter_name, 'title': reporter_title, 'is_director': is_dir, 'is_officer': is_off, 'shares': shares, 'price': price, 'amount': amount, 'date': date})
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
        return {'ticker': ticker, 'insider_buys': 0, 'insider_amount': 0, 'cluster_buy': 0, 'senior_buy': 0, 'insider_score': 0, 'updated_at': datetime.now().isoformat()}
    df = pd.DataFrame(all_transactions)
    df['date'] = pd.to_datetime(df['date'])
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
    return {'ticker': ticker, 'insider_buys': insider_buys, 'insider_amount': round(insider_amount, 0), 'cluster_buy': cluster_buy, 'senior_buy': senior_buy, 'insider_score': min(score, 10), 'updated_at': datetime.now().isoformat()}

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
            time.sleep(0.15)
            filings = get_form4_filings(cik, days_back=90)
            all_transactions = []
            for filing in filings[:10]:
                time.sleep(0.1)
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