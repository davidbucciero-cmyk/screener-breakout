import pandas as pd
import sqlite3
import logging
import os
from datetime import datetime
from openbb import obb

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/fundamentals.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT ticker FROM universe', conn)
    conn.close()
    return df['ticker'].tolist()

def get_fundamentals(ticker):
    try:
        result = obb.equity.fundamental.income(symbol=ticker, provider='yfinance', period='annual', limit=3)
        df = result.to_df()
        if df.empty or len(df) < 2:
            return None
        df = df.sort_values('period_ending')
        rev_col = next((c for c in df.columns if c in ['total_revenue', 'revenue', 'operating_revenue']), None)
        revenues = df[rev_col].dropna().tolist() if rev_col else []
        gross_profits = df['gross_profit'].dropna().tolist() if 'gross_profit' in df.columns else []
        rev_growth = 0
        if len(revenues) >= 2 and revenues[-2] and revenues[-2] != 0:
            rev_growth = (revenues[-1] - revenues[-2]) / abs(revenues[-2]) * 100
        gross_margins = []
        for i in range(min(len(revenues), len(gross_profits))):
            if revenues[i] and revenues[i] != 0:
                gross_margins.append(gross_profits[i] / revenues[i] * 100)
        gross_margin_trend = 0
        if len(gross_margins) >= 2:
            gross_margin_trend = 1 if gross_margins[-1] > gross_margins[-2] else 0
        return {'revenue_growth': round(rev_growth, 1), 'gross_margin_trend': gross_margin_trend, 'gross_margin_last': round(gross_margins[-1], 1) if gross_margins else 0}
    except Exception as e:
        log.debug(f'Erreur income {ticker} : {e}')
        return None

def get_cashflow(ticker):
    try:
        result = obb.equity.fundamental.cash(symbol=ticker, provider='yfinance', period='annual', limit=3)
        df = result.to_df()
        if df.empty:
            return None
        df = df.sort_values('period_ending') if 'period_ending' in df.columns else df
        fcf_col = next((c for c in df.columns if 'free_cash' in c.lower()), None)
        if not fcf_col:
            ocf_col = next((c for c in df.columns if 'operating' in c.lower() and 'cash' in c.lower()), None)
            capex_col = next((c for c in df.columns if 'capex' in c.lower() or 'capital_expenditure' in c.lower()), None)
            if ocf_col and capex_col:
                df['fcf_calc'] = df[ocf_col] + df[capex_col]
                fcf_col = 'fcf_calc'
        if not fcf_col:
            return None
        fcf_values = df[fcf_col].dropna().tolist()
        fcf_positive = 1 if fcf_values and fcf_values[-1] > 0 else 0
        fcf_improving = 1 if len(fcf_values) >= 2 and fcf_values[-1] > fcf_values[-2] else 0
        return {'fcf_positive': fcf_positive, 'fcf_improving': fcf_improving, 'fcf_last': round(fcf_values[-1] / 1e6, 1) if fcf_values else 0}
    except Exception as e:
        log.debug(f'Erreur cashflow {ticker} : {e}')
        return None

def score_fundamentals(income, cashflow):
    score = 0
    if income:
        if income['revenue_growth'] >= 20:
            score += 3
        elif income['revenue_growth'] >= 10:
            score += 1
        if income['gross_margin_trend']:
            score += 1
        if income['gross_margin_last'] >= 40:
            score += 1
    if cashflow:
        if cashflow['fcf_positive']:
            score += 2
        if cashflow['fcf_improving']:
            score += 1
    return min(score, 10)

def run():
    log.info('=' * 60)
    log.info('STEP 4 - FONDAMENTAUX')
    log.info('=' * 60)
    tickers = load_universe()
    results = []
    for idx, ticker in enumerate(tickers):
        log.info(f'[{idx+1}/{len(tickers)}] {ticker}')
        try:
            income = get_fundamentals(ticker)
            cashflow = get_cashflow(ticker)
            score = score_fundamentals(income, cashflow)
            results.append({'ticker': ticker, 'revenue_growth': income['revenue_growth'] if income else 0, 'gross_margin_trend': income['gross_margin_trend'] if income else 0, 'gross_margin_last': income['gross_margin_last'] if income else 0, 'fcf_positive': cashflow['fcf_positive'] if cashflow else 0, 'fcf_improving': cashflow['fcf_improving'] if cashflow else 0, 'fcf_last_m': cashflow['fcf_last'] if cashflow else 0, 'fundamental_score': score, 'updated_at': datetime.now().isoformat()})
        except Exception as e:
            log.error(f'Erreur {ticker} : {e}')
            results.append({'ticker': ticker, 'revenue_growth': 0, 'gross_margin_trend': 0, 'gross_margin_last': 0, 'fcf_positive': 0, 'fcf_improving': 0, 'fcf_last_m': 0, 'fundamental_score': 0, 'updated_at': datetime.now().isoformat()})
    df = pd.DataFrame(results)
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('fundamental_signals', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f'Fondamentaux sauvegardes : {len(df)} tickers')
    top = df.nlargest(10, 'fundamental_score')[['ticker', 'fundamental_score', 'revenue_growth', 'fcf_positive', 'gross_margin_last']]
    log.info(f'Top 10 :\n{top.to_string()}')
    return df

if __name__ == '__main__':
    run()