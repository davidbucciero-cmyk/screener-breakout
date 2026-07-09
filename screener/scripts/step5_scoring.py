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

SCORE_THRESHOLD = 6
EMAIL_FROM = 'david.bucciero.ide@gmail.com'
EMAIL_TO = 'david.bucciero@outlook.fr'
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
WEIGHTS = {'technical': 0.40, 'insider': 0.20, 'fundamental': 0.20, 'short': 0.15, 'reddit': 0.05}

def load_all_signals():
    conn = sqlite3.connect(DB_PATH)
    universe = pd.read_sql('SELECT ticker, price, volume, mktcap, sma50, sma200 FROM universe', conn)
    technical = pd.read_sql('SELECT * FROM technical_signals', conn)
    insider = pd.read_sql('SELECT * FROM insider_signals', conn)
    fundamental = pd.read_sql('SELECT * FROM fundamental_signals', conn)
    try:
        short = pd.read_sql('SELECT * FROM short_signals', conn)
    except Exception:
        short = pd.DataFrame(columns=['ticker', 'short_float', 'short_ratio', 'short_score'])
    try:
        reddit = pd.read_sql('SELECT * FROM reddit_signals', conn)
    except Exception:
        reddit = pd.DataFrame(columns=['ticker', 'reddit_mentions', 'reddit_zscore', 'reddit_signal'])
    try:
        congress = pd.read_sql('SELECT * FROM congress_signals', conn)
    except Exception:
        congress = pd.DataFrame(columns=['ticker', 'congress_net_score', 'congress_recent_flag'])
    conn.close()
    df = universe.merge(technical[['ticker', 'technical_score', 'flat_base', 'bb_squeeze', 'obv_trend', 'vol_ratio', 'rs_line']], on='ticker', how='left')
    df = df.merge(insider[['ticker', 'insider_score', 'insider_buys', 'cluster_buy', 'senior_buy']], on='ticker', how='left')
    df = df.merge(fundamental[['ticker', 'fundamental_score', 'revenue_growth', 'fcf_positive', 'gross_margin_last']], on='ticker', how='left')
    df = df.merge(short[['ticker', 'short_float', 'short_ratio', 'short_score']], on='ticker', how='left')
    df = df.merge(reddit[['ticker', 'reddit_mentions', 'reddit_zscore', 'reddit_signal']], on='ticker', how='left')
    df = df.merge(congress[['ticker', 'congress_net_score', 'congress_recent_flag']], on='ticker', how='left')
    df = df.fillna(0)
    return df

def compute_final_score(df):
    tech_norm = df['technical_score'] / 9
    insider_norm = df['insider_score'] / 10
    fund_norm = df['fundamental_score'] / 8
    short_norm = df['short_score'] / 5
    reddit_norm = df['reddit_signal']
    df['final_score'] = (tech_norm * WEIGHTS['technical'] * 10 + insider_norm * WEIGHTS['insider'] * 10 + fund_norm * WEIGHTS['fundamental'] * 10 + short_norm * WEIGHTS['short'] * 10 + reddit_norm * WEIGHTS['reddit'] * 10).round(1)
    df['final_score'] = df['final_score'].clip(0, 10)
    return df

def save_scores(df):
    conn = sqlite3.connect(DB_PATH)
    cols = ['ticker', 'price', 'mktcap', 'final_score', 'technical_score', 'insider_score', 'fundamental_score', 'short_score', 'short_float', 'flat_base', 'bb_squeeze', 'obv_trend', 'cluster_buy', 'senior_buy', 'revenue_growth', 'fcf_positive', 'gross_margin_last', 'reddit_mentions', 'reddit_zscore', 'reddit_signal', 'congress_net_score', 'congress_recent_flag']
    df['updated_at'] = datetime.now().isoformat()
    df[cols + ['updated_at']].to_sql('final_scores', conn, if_exists='replace', index=False)
    conn.close()

def send_alert(candidates, above_threshold=True):
    if not EMAIL_PASSWORD:
        log.warning('EMAIL_PASSWORD non defini - alerte email ignoree')
        return
    try:
        msg = MIMEMultipart('alternative')
        subject_label = f'{len(candidates)} candidats' if above_threshold else 'Top 10 (aucun seuil atteint)'
        msg['Subject'] = f'Screener Breakout - {subject_label} ({datetime.now().strftime("%d/%m/%Y")})'
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        html = '<html><body>'
        html += f'<h2>Screener Pre-Breakout — {datetime.now().strftime("%d/%m/%Y")}</h2>'
        if above_threshold:
            html += f'<p>{len(candidates)} tickers avec score >= {SCORE_THRESHOLD}/10</p>'
        else:
            html += f"<p>Aucun ticker au-dessus du seuil {SCORE_THRESHOLD}/10 aujourd'hui. Top 10 ci-dessous a titre indicatif.</p>"
        html += '<table border="1" cellpadding="5" style="border-collapse:collapse">'
        html += '<tr><th>Ticker</th><th>Score</th><th>Prix</th><th>Tech</th><th>Insider</th><th>Fond</th><th>Short%</th><th>Reddit</th><th>Rev%</th><th>Flat Base</th><th>Cluster</th><th>Congress</th></tr>'
        for _, row in candidates.iterrows():
            html += f'<tr><td><b>{row["ticker"]}</b></td><td><b>{row["final_score"]}</b></td><td>${row["price"]:.2f}</td><td>{row["technical_score"]:.0f}/9</td><td>{row["insider_score"]:.0f}/10</td><td>{row["fundamental_score"]:.0f}/8</td><td>{row["short_float"]:.1f}%</td><td>{row["reddit_mentions"]:.0f}</td><td>{row["revenue_growth"]:.1f}%</td><td>{"✅" if row["flat_base"] else "❌"}</td><td>{"✅" if row["cluster_buy"] else "❌"}</td><td>{row["congress_net_score"]:+.0f}</td></tr>'
        html += '</table></body></html>'
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
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
    top20 = df.nlargest(20, 'final_score')[['ticker', 'final_score', 'technical_score', 'insider_score', 'fundamental_score', 'short_score', 'short_float', 'revenue_growth', 'flat_base']]
    log.info(f'TOP 20 CANDIDATS :\n{top20.to_string()}')
    candidates = df[df['final_score'] >= SCORE_THRESHOLD]
    log.info(f'Candidats score >= {SCORE_THRESHOLD} : {len(candidates)}')
    above_threshold = not candidates.empty
    if candidates.empty:
        log.info('Aucun candidat au-dessus du seuil - envoi du top 10 a la place')
        candidates = df.nlargest(10, 'final_score')
    send_alert(candidates, above_threshold)
    return df

if __name__ == '__main__':
    run()




