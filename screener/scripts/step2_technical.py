import pandas as pd
import numpy as np
import sqlite3
import logging
import os
from datetime import datetime
import yfinance as yf

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/technical.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

MAST_RALLY_MIN = 1.0        # +100%
RETRACE_MIN = 0.30
RETRACE_MAX = 0.50
TIGHT_RANGE_MAX = 0.20

DAILY_CONSOL_MIN = 63        # ~3 mois de bourse
DAILY_CONSOL_MAX = 126       # ~6 mois de bourse
WEEKLY_CONSOL_MIN = 13       # ~3 mois
WEEKLY_CONSOL_MAX = 26       # ~6 mois

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('''
        SELECT u.ticker FROM universe u
        JOIN fundamental_signals f ON f.ticker = u.ticker
        WHERE f.fundamental_pass = 1
    ''', conn)
    conn.close()
    log.info(f'Univers filtre (fundamental_pass=1) : {len(df)} tickers')
    return df['ticker'].tolist()

def detect_mast_flame(close, min_consol, max_consol):
    close = close.dropna()
    if len(close) < min_consol + 20:
        return None
    peak_idx = int(np.argmax(close.values))
    peak = close.iloc[peak_idx]
    if peak_idx < 5:
        return None
    mast_low = close.iloc[:peak_idx].min()
    if mast_low <= 0:
        return None
    mast_rally_pct = peak / mast_low - 1
    if mast_rally_pct < MAST_RALLY_MIN:
        return {'pattern': False, 'mast_rally_pct': round(mast_rally_pct, 3), 'retracement_pct': None, 'consolidation_periods': None}

    post_peak = close.iloc[peak_idx:]
    if len(post_peak) < min_consol:
        return {'pattern': False, 'mast_rally_pct': round(mast_rally_pct, 3), 'retracement_pct': None, 'consolidation_periods': None}

    retracement_pct = (peak - post_peak.iloc[-1]) / peak
    drawdown = (peak - post_peak) / peak
    flag_entries = drawdown[drawdown >= RETRACE_MIN]
    if flag_entries.empty:
        return {'pattern': False, 'mast_rally_pct': round(mast_rally_pct, 3), 'retracement_pct': round(retracement_pct, 3), 'consolidation_periods': None}

    flag_start_pos = post_peak.index.get_loc(flag_entries.index[0])
    consolidation_periods = len(post_peak) - 1 - flag_start_pos
    flag_window = post_peak.iloc[flag_start_pos:]
    # La tightness se mesure sur la partie recente de la zone de consolidation :
    # les premieres periodes juste apres le franchissement des -30% font encore
    # partie de la descente et gonfleraient artificiellement le range.
    tight_window = flag_window.tail(min(len(flag_window), min_consol))
    tight_range = (tight_window.max() - tight_window.min()) / tight_window.min() if tight_window.min() > 0 else np.inf

    pattern = (
        RETRACE_MIN <= retracement_pct <= RETRACE_MAX
        and min_consol <= consolidation_periods <= max_consol
        and tight_range <= TIGHT_RANGE_MAX
    )
    return {
        'pattern': bool(pattern),
        'mast_rally_pct': round(mast_rally_pct, 3),
        'retracement_pct': round(retracement_pct, 3),
        'consolidation_periods': int(consolidation_periods),
    }

def compute_signals(ticker, data):
    try:
        close = data['Close'].dropna()
        if len(close) < 100:
            return None
        daily = detect_mast_flame(close, DAILY_CONSOL_MIN, DAILY_CONSOL_MAX)
        weekly_close = close.resample('W').last().dropna()
        weekly = detect_mast_flame(weekly_close, WEEKLY_CONSOL_MIN, WEEKLY_CONSOL_MAX)
        if daily is None and weekly is None:
            return None
        daily = daily or {'pattern': False, 'mast_rally_pct': None, 'retracement_pct': None, 'consolidation_periods': None}
        weekly = weekly or {'pattern': False, 'mast_rally_pct': None, 'retracement_pct': None, 'consolidation_periods': None}

        score = 0
        if daily['pattern']:
            score += 5
        if weekly['pattern']:
            score += 3
        for d in (daily, weekly):
            if d['retracement_pct'] is not None and RETRACE_MIN <= d['retracement_pct'] <= RETRACE_MAX:
                closeness = 1 - abs(d['retracement_pct'] - 0.40) / 0.10
                score += max(0, closeness)

        return {
            'ticker': ticker,
            'mast_rally_pct_d': daily['mast_rally_pct'],
            'retracement_pct_d': daily['retracement_pct'],
            'consolidation_days_d': daily['consolidation_periods'],
            'pattern_daily': daily['pattern'],
            'mast_rally_pct_w': weekly['mast_rally_pct'],
            'retracement_pct_w': weekly['retracement_pct'],
            'consolidation_weeks_w': weekly['consolidation_periods'],
            'pattern_weekly': weekly['pattern'],
            'technical_score': round(min(score, 10), 1),
            'updated_at': datetime.now().isoformat(),
        }
    except Exception as e:
        log.debug(f'Erreur {ticker} : {e}')
        return None

def run():
    log.info('=' * 60)
    log.info('STEP 2 - PATTERN MAT-FANION (daily + weekly)')
    log.info('=' * 60)
    tickers = load_universe()
    if not tickers:
        log.warning('Aucun ticker fondamentalement valide - rien a scanner')
        return
    results = []
    batch_size = 50
    total_batches = (len(tickers) + batch_size - 1) // batch_size
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        log.info(f'Batch {i//batch_size+1}/{total_batches}')
        try:
            data = yf.download(batch, period='5y', interval='1d', group_by='ticker', auto_adjust=True, threads=True, progress=False)
            for ticker in batch:
                try:
                    t_data = data[ticker] if ticker in data.columns.get_level_values(0) else None
                    if t_data is None or t_data.empty:
                        continue
                    signals = compute_signals(ticker, t_data)
                    if signals:
                        results.append(signals)
                except Exception as e:
                    log.debug(f'Erreur {ticker} : {e}')
        except Exception as e:
            log.error(f'Erreur batch : {e}')
    df = pd.DataFrame(results)
    if df.empty:
        log.warning('Aucun signal technique calcule')
        return
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('technical_signals', conn, if_exists='replace', index=False)
    conn.close()
    n_daily = int(df['pattern_daily'].sum())
    n_weekly = int(df['pattern_weekly'].sum())
    log.info(f'Signaux sauvegardes : {len(df)} tickers - pattern_daily: {n_daily} - pattern_weekly: {n_weekly}')
    top10 = df.nlargest(10, 'technical_score')[['ticker', 'technical_score', 'pattern_daily', 'pattern_weekly', 'retracement_pct_d', 'mast_rally_pct_d']]
    log.info(f'Top 10 :\n{top10.to_string()}')
    return df

if __name__ == '__main__':
    run()
