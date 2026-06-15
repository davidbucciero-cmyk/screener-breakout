import pandas as pd
import numpy as np
import sqlite3
import logging
import os
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/ic_scoring.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

FORWARD_DAYS = 20

def load_signals():
    conn = sqlite3.connect(DB_PATH)
    scores = pd.read_sql('SELECT * FROM final_scores', conn)
    technical = pd.read_sql('SELECT * FROM technical_signals', conn)
    fundamental = pd.read_sql('SELECT * FROM fundamental_signals', conn)
    short = pd.read_sql('SELECT * FROM short_signals', conn)
    conn.close()
    df = scores.merge(technical[['ticker','obv_trend','vol_ratio','vol_dryup','bb_squeeze','atr_declining','flat_base','higher_lows','ad_trend','rs_line']], on='ticker', how='left')
    df = df.merge(fundamental[['ticker','revenue_growth','fcf_positive','gross_margin_trend']], on='ticker', how='left')
    df = df.merge(short[['ticker','short_float','short_ratio']], on='ticker', how='left')
    df = df.fillna(0)
    return df

def get_forward_returns(tickers, days=20):
    log.info(f'Calcul rendements forward {days}j...')
    results = {}
    batch_size = 50
    end = datetime.now()
    start = end - timedelta(days=days + 10)
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        try:
            data = yf.download(batch, start=start, end=end, interval='1d', group_by='ticker', auto_adjust=True, threads=True, progress=False)
            for ticker in batch:
                try:
                    if len(batch) == 1:
                        closes = data['Close'].dropna()
                    else:
                        closes = data[ticker]['Close'].dropna() if ticker in data.columns.get_level_values(0) else pd.Series()
                    if len(closes) >= 2:
                        ret = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        results[ticker] = ret
                except Exception:
                    pass
        except Exception as e:
            log.error(f'Erreur batch : {e}')
    return results

def compute_ic(df, signal_col, returns):
    df2 = df[df['ticker'].isin(returns.keys())].copy()
    df2['forward_return'] = df2['ticker'].map(returns)
    df2 = df2.dropna(subset=[signal_col, 'forward_return'])
    if len(df2) < 10:
        return None, None, None
    ic, pvalue = stats.spearmanr(df2[signal_col], df2['forward_return'])
    return round(ic, 4), round(pvalue, 4), len(df2)

def run():
    log.info('=' * 60)
    log.info('STEP 9 - IC SCORING')
    log.info('=' * 60)
    df = load_signals()
    tickers = df['ticker'].tolist()
    returns = get_forward_returns(tickers, FORWARD_DAYS)
    log.info(f'Rendements calcules : {len(returns)} tickers')

    signals = [
        'obv_trend', 'vol_ratio', 'vol_dryup', 'bb_squeeze',
        'atr_declining', 'flat_base', 'higher_lows', 'ad_trend', 'rs_line',
        'technical_score', 'revenue_growth', 'fcf_positive',
        'gross_margin_trend', 'short_float', 'short_ratio',
        'insider_score', 'final_score'
    ]

    results = []
    for sig in signals:
        if sig not in df.columns:
            continue
        ic, pv, n = compute_ic(df, sig, returns)
        if ic is None:
            continue
        significant = pv < 0.05
        results.append({
            'signal': sig,
            'IC': ic,
            'p_value': pv,
            'n': n,
            'significant': significant,
            'interpretation': 'Fort' if abs(ic) >= 0.1 and significant else ('Faible' if significant else 'Non significatif')
        })
        log.info(f'{sig:25s} IC={ic:+.4f}  p={pv:.4f}  {"✅" if significant else "❌"}  {results[-1]["interpretation"]}')

    result_df = pd.DataFrame(results).sort_values('IC', ascending=False)
    conn = sqlite3.connect(DB_PATH)
    result_df.to_sql('ic_scores', conn, if_exists='replace', index=False)
    conn.close()

    log.info('\n=== SIGNAUX SIGNIFICATIFS ===')
    sig_df = result_df[result_df['significant']]
    if not sig_df.empty:
        log.info(f'\n{sig_df[["signal","IC","p_value","interpretation"]].to_string()}')
    else:
        log.info('Aucun signal significatif — historique trop court (normal au premier run)')

    log.info('\n=== RECOMMANDATIONS ===')
    for _, r in result_df.iterrows():
        if r['significant'] and abs(r['IC']) >= 0.1:
            log.info(f"GARDER et surponderer : {r['signal']} (IC={r['IC']:+.4f})")
        elif r['significant']:
            log.info(f"GARDER : {r['signal']} (IC={r['IC']:+.4f})")
        else:
            log.info(f"A surveiller : {r['signal']} (non significatif pour l instant)")

    return result_df

if __name__ == '__main__':
    run()