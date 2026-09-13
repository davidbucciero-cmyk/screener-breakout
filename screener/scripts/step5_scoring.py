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

EMAIL_FROM = 'david.bucciero.ide@gmail.com'
EMAIL_TO = 'david.bucciero@outlook.fr'
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')

def load_all_signals():
    conn = sqlite3.connect(DB_PATH)
    universe = pd.read_sql('SELECT ticker, price, mktcap, cap_bucket, sector FROM universe', conn)
    fundamental = pd.read_sql('SELECT * FROM fundamental_signals', conn)
    try:
        technical = pd.read_sql('SELECT * FROM technical_signals', conn)
    except Exception:
        technical = pd.DataFrame(columns=['ticker', 'pattern_daily', 'pattern_weekly', 'mast_rally_pct_d', 'retracement_pct_d', 'technical_score'])
    try:
        insider = pd.read_sql('SELECT * FROM insider_signals', conn)
    except Exception:
        insider = pd.DataFrame(columns=['ticker', 'insider_score', 'insider_net_90d', 'insider_net_positive', 'cluster_buy', 'senior_buy'])
    try:
        institutional = pd.read_sql('SELECT * FROM institutional_signals', conn)
    except Exception:
        institutional = pd.DataFrame(columns=['ticker', 'institutional_trend', 'insider_ownership'])
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

    df = universe.merge(fundamental[['ticker', 'fundamental_pass', 'fundamental_score', 'revenue_cagr', 'eps_cagr', 'peg_ratio', 'pe_ratio', 'ev_to_ebitda', 'price_to_book', 'return_on_equity', 'return_on_assets', 'profit_margin', 'net_debt_to_ebitda', 'current_ratio']], on='ticker', how='left')
    df = df.merge(technical[['ticker', 'pattern_daily', 'pattern_weekly', 'mast_rally_pct_d', 'retracement_pct_d', 'technical_score']], on='ticker', how='left')
    df = df.merge(insider[['ticker', 'insider_score', 'insider_net_90d', 'insider_net_positive', 'cluster_buy', 'senior_buy']], on='ticker', how='left')
    df = df.merge(institutional[['ticker', 'institutional_trend', 'insider_ownership']], on='ticker', how='left')
    df = df.merge(short[['ticker', 'short_float', 'short_ratio', 'short_score']], on='ticker', how='left')
    df = df.merge(reddit[['ticker', 'reddit_mentions', 'reddit_zscore', 'reddit_signal']], on='ticker', how='left')
    df = df.merge(congress[['ticker', 'congress_net_score', 'congress_recent_flag']], on='ticker', how='left')
    for col in ['fundamental_pass', 'pattern_daily', 'pattern_weekly', 'insider_net_positive', 'institutional_trend', 'cluster_buy', 'senior_buy', 'congress_recent_flag', 'reddit_signal']:
        if col in df.columns:
            df[col] = df[col].fillna(0)
    return df

def compute_final_score(df):
    def score_row(r):
        if not (r.get('fundamental_pass') and (r.get('pattern_daily') or r.get('pattern_weekly'))):
            return 0.0
        score = 5.0
        retr = r.get('retracement_pct_d')
        if retr is not None and pd.notna(retr):
            score += max(0.0, 1 - abs(retr - 0.40) / 0.10)
        rev_cagr = r.get('revenue_cagr')
        eps_cagr = r.get('eps_cagr')
        if pd.notna(rev_cagr) and rev_cagr and rev_cagr >= 0.16:
            score += 0.5
        if pd.notna(eps_cagr) and eps_cagr and eps_cagr >= 0.20:
            score += 0.5
        if r.get('insider_net_positive'):
            score += 1
        if r.get('institutional_trend'):
            score += 1
        return round(min(score, 10), 1)
    df['final_score'] = df.apply(score_row, axis=1)
    return df

def save_scores(df):
    conn = sqlite3.connect(DB_PATH)
    cols = ['ticker', 'price', 'mktcap', 'cap_bucket', 'sector', 'final_score', 'fundamental_pass', 'fundamental_score',
            'revenue_cagr', 'eps_cagr', 'peg_ratio', 'ev_to_ebitda', 'price_to_book', 'return_on_equity', 'return_on_assets', 'net_debt_to_ebitda',
            'pattern_daily', 'pattern_weekly', 'mast_rally_pct_d', 'retracement_pct_d', 'technical_score',
            'insider_score', 'insider_net_90d', 'insider_net_positive', 'institutional_trend', 'insider_ownership',
            'short_score', 'short_float', 'reddit_mentions', 'reddit_zscore', 'reddit_signal',
            'congress_net_score', 'congress_recent_flag']
    df['updated_at'] = datetime.now().isoformat()
    df[cols + ['updated_at']].to_sql('final_scores', conn, if_exists='replace', index=False)
    conn.close()

def send_alert(candidates, above_threshold=True):
    if not EMAIL_PASSWORD:
        log.warning('EMAIL_PASSWORD non defini - alerte email ignoree')
        return
    try:
        msg = MIMEMultipart('alternative')
        subject_label = f'{len(candidates)} candidats' if above_threshold else 'Top 10 fondamental (aucun candidat pattern)'
        msg['Subject'] = f'Screener Breakout - {subject_label} ({datetime.now().strftime("%d/%m/%Y")})'
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        html = '<html><body>'
        html += f'<h2>Screener Breakout — {datetime.now().strftime("%d/%m/%Y")}</h2>'
        if above_threshold:
            html += f'<p>{len(candidates)} tickers passent le filtre fondamental ET le pattern mat-fanion</p>'
        else:
            html += "<p>Aucun ticker ne passe les deux filtres aujourd'hui. Top 10 fondamental ci-dessous a titre indicatif.</p>"
        html += '<table border="1" cellpadding="5" style="border-collapse:collapse">'
        html += '<tr><th>Ticker</th><th>Secteur</th><th>Cap</th><th>Score</th><th>Rev CAGR</th><th>EPS CAGR</th><th>PEG</th><th>Mat %</th><th>Retrace %</th><th>Daily</th><th>Weekly</th><th>Insider</th><th>Instit.</th></tr>'
        for _, row in candidates.iterrows():
            html += f'''<tr><td><b>{row["ticker"]}</b></td><td>{row.get("sector","")}</td><td>{row.get("cap_bucket","")}</td>
                <td><b>{row["final_score"]}</b></td>
                <td>{row.get("revenue_cagr",0)*100:.1f}%</td><td>{row.get("eps_cagr",0)*100:.1f}%</td><td>{row.get("peg_ratio",0):.2f}</td>
                <td>{row.get("mast_rally_pct_d",0)*100:.0f}%</td><td>{row.get("retracement_pct_d",0)*100:.0f}%</td>
                <td>{"✅" if row.get("pattern_daily") else "❌"}</td><td>{"✅" if row.get("pattern_weekly") else "❌"}</td>
                <td>{"✅" if row.get("insider_net_positive") else "❌"}</td><td>{"✅" if row.get("institutional_trend") else "❌"}</td></tr>'''
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
    log.info('STEP 5 - SCORING FINAL (filtre dur fondamental + pattern)')
    log.info('=' * 60)
    df = load_all_signals()
    df = compute_final_score(df)
    save_scores(df)
    candidates = df[(df['fundamental_pass'] == 1) & ((df['pattern_daily'] == 1) | (df['pattern_weekly'] == 1))].sort_values('final_score', ascending=False)
    log.info(f'Candidats fondamental+pattern : {len(candidates)} / {len(df)} tickers univers')
    above_threshold = not candidates.empty
    if candidates.empty:
        log.info('Aucun candidat ne passe les deux filtres - envoi du top 10 fondamental a la place')
        candidates = df[df['fundamental_pass'] == 1].nlargest(10, 'fundamental_score')
    top20 = df.nlargest(20, 'final_score')[['ticker', 'final_score', 'fundamental_pass', 'pattern_daily', 'pattern_weekly', 'revenue_cagr', 'eps_cagr']]
    log.info(f'TOP 20 (tout univers) :\n{top20.to_string()}')
    send_alert(candidates, above_threshold)
    return df

if __name__ == '__main__':
    run()
