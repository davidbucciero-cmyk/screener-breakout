import pandas as pd
import sqlite3
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/scoring.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

SCORE_THRESHOLD = 7
EMAIL_FROM = 'david.bucciero@outlook.fr'
EMAIL_TO = 'david.bucciero@outlook.fr'
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')

WEIGHTS = {'technical': 0.35, 'insider': 0.30, 'fundamental': 0.35}

def load_all_signals():
    conn = sqlite3.connect(DB_PATH)
    universe = pd.read_sql('SELECT ticker, price, volume, mktcap, sma50, sma200 FROM universe', conn)
    technical = pd.read_sql('SELECT * FROM technical_signals', conn)
    insider = pd.read_sql('SELECT * FROM insider_signals', conn)
    fundamental = pd.read_sql('SELECT * FROM fundamental_signals', conn)
    conn.close()
    df = universe.merge(technical[['ticker', 'technical_score', 'flat_base', 'bb_squeeze', 'obv_trend', 'vol_ratio', 'rs_line']], on='ticker', how='left')
    df = df.merge(insider[['ticker', 'insider_score', 'insider_buys', 'cluster_buy', 'senior_buy']], on='ticker', how='left')
    df = df.merge(fundamental[['ticker', 'fundamental_score', 'revenue_growth', 'fcf_positive', 'gross_margin_last']], on='ticker', how='left')
    df = df.fillna(0)
    return df

def compute_final_score(df):
    tech_normalized = df['technical_score'] / 9
    insider_normalized = df['insider_score'] / 10
    fund_normalized = df['fundamental_score'] / 8
    df['final_score'] = (
        tech_normalized * WEIGHTS['technical'] * 10 +
        insider_normalized * WEIGHTS['insider'] * 10 +
        fund_normalized * WEIGHTS['fundamental'] * 10
    ).round(1)
    df['final_score'] = df['final_score'].clip(0, 10)
    return df

def save_scores(df):
    conn = sqlite3.connect(DB_PATH)
    cols = ['ticker', 'price', 'mktcap', 'final_score', 'technical_score', 'insider_score', 'fundamental_score', 'flat_base', 'bb_squeeze', 'obv_trend', 'cluster_buy', 'senior_buy', 'revenue_growth', 'fcf_positive', 'gross_margin_last']
    df['updated_at'] = datetime.now().isoformat()
    df[cols + ['updated_at']].to_sql('final_scores', conn, if_exists='replace', index=False)
    conn.close()

def send_alert(candidates):
    if not EMAIL_PASSWORD:
        log.warning('EMAIL_PASSWORD non defini - alerte email ignoree')
        return
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Screener Breakout - {len(candidates)} candidats ({datetime.now().strftime("%d/%m/%Y")})'
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        html = '<html><body>'
        html += f'<h2>Screener Pre-Breakout — {datetime.now().strftime("%d/%m/%Y")}</h2>'
        html += f'<p>{len(candidates)} tickers avec score >= {SCORE_THRESHOLD}/10</p>'
        html += '<table border="1" cellpadding="5" style="border-collapse:collapse">'
        html += '<tr><th>Ticker</th><th>Score</th><th>Prix</th><th>Technique</th><th>Insider</th><th>Fondamental</th><th>Rev Growth</th><th>Flat Base</th><th>Cluster Buy</th></tr>'
        for _, row in candidates.iterrows():
            html += f'<tr><td><b>{row["ticker"]}</b></td><td><b>{row["final_score"]}</b></td><td>${row["price"]:.2f}</td><td>{row["technical_score"]:.0f}/9</td><td>{row["insider_score"]:.0f}/10</td><td>{row["fundamental_score"]:.0f}/8</td><td>{row["revenue_growth"]:.1f}%</td><td>{"✅" if row["flat_base"] else "❌"}</td><td>{"✅" if row["cluster_buy"] else "❌"}</td></tr>'
        html += '</table></body></html>'
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP('smtp.office365.com', 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f'Email envoye a {EMAIL_TO}')
    except Exception as e:
        log.error(f'Erreur email : {e}')

def run():
    log.info('=' * 60)
    log.info('STEP 5 - SCORING FINAL')
    log.info('=' * 60)
    df = load_all_signals()
    df = compute_final_score(df)
    save_scores(df)
    top20 = df.nlargest(20, 'final_score')[['ticker', 'final_score', 'technical_score', 'insider_score', 'fundamental_score', 'revenue_growth', 'flat_base', 'cluster_buy']]
    log.info(f'TOP 20 CANDIDATS :\n{top20.to_string()}')
    candidates = df[df['final_score'] >= SCORE_THRESHOLD]
    log.info(f'Candidats score >= {SCORE_THRESHOLD} : {len(candidates)}')
    if not candidates.empty:
        log.info('Envoi alerte email...')
        send_alert(candidates)
    return df

if __name__ == '__main__':
    run()