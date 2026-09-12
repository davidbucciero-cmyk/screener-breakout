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

REVENUE_CAGR_MIN = 0.08
EPS_CAGR_MIN = 0.10
NET_MARGIN_MIN = 0.10
ROE_MIN = 0.15
ROA_MIN = 0.07
NET_DEBT_EBITDA_MAX = 3.0
CURRENT_RATIO_MIN = 1.0
PEG_MAX = 2.0
PE_VS_SECTOR_MEDIAN_MULT = 1.5
MAX_DECLINES = 1
MIN_PERIODS = 4  # >= 3 ans de span

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT ticker, sector FROM universe', conn)
    conn.close()
    return df

def get_metrics(ticker):
    try:
        df = obb.equity.fundamental.metrics(symbol=ticker, provider='yfinance').to_df()
        if df.empty:
            return None
        row = df.iloc[0]
        return {
            'peg_ratio': row.get('peg_ratio'),
            'pe_ratio': row.get('pe_ratio'),
            'current_ratio': row.get('current_ratio'),
            'profit_margin': row.get('profit_margin'),
            'return_on_assets': row.get('return_on_assets'),
            'return_on_equity': row.get('return_on_equity'),
            'enterprise_value': row.get('enterprise_value'),
            'market_cap': row.get('market_cap'),
        }
    except Exception as e:
        log.debug(f'Erreur metrics {ticker} : {e}')
        return None

def compute_cagr(values):
    clean = [v for v in values if pd.notna(v)]
    if len(clean) < MIN_PERIODS:
        return None, None
    first, last = clean[0], clean[-1]
    n_years = len(clean) - 1
    declines = sum(1 for i in range(1, len(clean)) if clean[i] < clean[i-1])
    if first is None or last is None or first <= 0 or last <= 0:
        return None, declines
    cagr = (last / first) ** (1 / n_years) - 1
    return cagr, declines

def get_income_series(ticker):
    try:
        df = obb.equity.fundamental.income(symbol=ticker, provider='yfinance', period='annual', limit=5).to_df()
        if df.empty:
            return None
        df = df.sort_values('period_ending')
        rev_col = next((c for c in df.columns if c in ['total_revenue', 'revenue', 'operating_revenue']), None)
        eps_col = 'diluted_earnings_per_share' if 'diluted_earnings_per_share' in df.columns else ('basic_earnings_per_share' if 'basic_earnings_per_share' in df.columns else None)
        ebitda_col = next((c for c in ['ebitda', 'normalized_ebitda'] if c in df.columns), None)
        revenues = df[rev_col].tolist() if rev_col else []
        eps_values = df[eps_col].tolist() if eps_col else []
        ebitda_last = None
        if ebitda_col:
            ebitda_series = df[ebitda_col].dropna()
            ebitda_last = ebitda_series.iloc[-1] if not ebitda_series.empty else None
        revenue_cagr, revenue_declines = compute_cagr(revenues)
        eps_cagr, eps_declines = compute_cagr(eps_values)
        return {
            'revenue_cagr': revenue_cagr,
            'revenue_declines': revenue_declines,
            'eps_cagr': eps_cagr,
            'eps_declines': eps_declines,
            'ebitda_last': ebitda_last,
        }
    except Exception as e:
        log.debug(f'Erreur income {ticker} : {e}')
        return None

def score_fundamentals(row):
    score = 0
    if row.get('revenue_cagr') and row['revenue_cagr'] >= REVENUE_CAGR_MIN:
        score += 2
    if row.get('eps_cagr') and row['eps_cagr'] >= EPS_CAGR_MIN:
        score += 2
    if row.get('return_on_equity') and row['return_on_equity'] >= ROE_MIN:
        score += 2
    if row.get('return_on_assets') and row['return_on_assets'] >= ROA_MIN:
        score += 1
    if row.get('profit_margin') and row['profit_margin'] >= NET_MARGIN_MIN:
        score += 1
    if row.get('peg_or_pe_ok'):
        score += 2
    return min(score, 10)

def run():
    log.info('=' * 60)
    log.info('STEP 4 - FONDAMENTAUX (CAGR / ratios)')
    log.info('=' * 60)
    universe = load_universe()
    rows = []
    for idx, u in universe.iterrows():
        ticker = u['ticker']
        log.info(f'[{idx+1}/{len(universe)}] {ticker}')
        metrics = get_metrics(ticker)
        income = get_income_series(ticker)
        row = {'ticker': ticker, 'sector': u.get('sector')}
        row.update(metrics or {})
        row.update(income or {})
        net_debt_to_ebitda = None
        ev = row.get('enterprise_value')
        mc = row.get('market_cap')
        ebitda = row.get('ebitda_last')
        if ev is not None and mc is not None and ebitda:
            try:
                net_debt_to_ebitda = (ev - mc) / ebitda
            except Exception:
                net_debt_to_ebitda = None
        row['net_debt_to_ebitda'] = net_debt_to_ebitda
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        log.warning('Aucun fondamental calcule')
        return

    sector_median_pe = df.groupby('sector')['pe_ratio'].median()

    def peg_or_pe_ok(r):
        peg = r.get('peg_ratio')
        if pd.notna(peg) and peg is not None and peg <= PEG_MAX and peg > 0:
            return True
        pe = r.get('pe_ratio')
        med = sector_median_pe.get(r.get('sector'))
        if pd.notna(pe) and pd.notna(med) and med and pe <= PE_VS_SECTOR_MEDIAN_MULT * med:
            return True
        return False

    df['peg_or_pe_ok'] = df.apply(peg_or_pe_ok, axis=1)

    def passes(r):
        checks = [
            r.get('revenue_cagr') is not None and r['revenue_cagr'] >= REVENUE_CAGR_MIN and (r.get('revenue_declines') or 0) <= MAX_DECLINES,
            r.get('eps_cagr') is not None and r['eps_cagr'] >= EPS_CAGR_MIN and (r.get('eps_declines') or 0) <= MAX_DECLINES,
            r.get('profit_margin') is not None and r['profit_margin'] >= NET_MARGIN_MIN,
            r.get('return_on_equity') is not None and r['return_on_equity'] >= ROE_MIN,
            r.get('return_on_assets') is not None and r['return_on_assets'] >= ROA_MIN,
            r.get('net_debt_to_ebitda') is not None and r['net_debt_to_ebitda'] <= NET_DEBT_EBITDA_MAX,
            r.get('current_ratio') is not None and r['current_ratio'] >= CURRENT_RATIO_MIN,
            bool(r.get('peg_or_pe_ok')),
        ]
        return all(checks)

    df['fundamental_pass'] = df.apply(passes, axis=1)
    df['fundamental_score'] = df.apply(score_fundamentals, axis=1)
    df['updated_at'] = datetime.now().isoformat()

    conn = sqlite3.connect(DB_PATH)
    df.to_sql('fundamental_signals', conn, if_exists='replace', index=False)
    conn.close()

    n_pass = int(df['fundamental_pass'].sum())
    log.info(f'Fondamentaux sauvegardes : {len(df)} tickers, {n_pass} passent le filtre')
    top = df[df['fundamental_pass']].nlargest(10, 'fundamental_score')[['ticker', 'fundamental_score', 'revenue_cagr', 'eps_cagr', 'return_on_equity', 'peg_ratio']]
    if not top.empty:
        log.info(f'Top 10 :\n{top.to_string()}')
    return df

if __name__ == '__main__':
    run()
