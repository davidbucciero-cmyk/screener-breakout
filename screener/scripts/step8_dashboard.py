import sqlite3
import os
import pandas as pd
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/dashboard.html')

def load_data():
    conn = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    scores = pd.read_sql('SELECT * FROM final_scores ORDER BY final_score DESC', conn)
    short = pd.read_sql('SELECT * FROM short_signals', conn) if 'short_signals' in tables else pd.DataFrame(columns=['ticker','short_float','short_ratio'])
    reddit = pd.read_sql('SELECT * FROM reddit_signals', conn) if 'reddit_signals' in tables else pd.DataFrame(columns=['ticker','reddit_mentions','reddit_zscore','reddit_signal'])
    congress = pd.read_sql('SELECT * FROM congress_signals', conn) if 'congress_signals' in tables else pd.DataFrame(columns=['ticker','congress_net_score','congress_recent_flag'])
    conn.close()
    df = scores.merge(short[['ticker','short_float','short_ratio']], on='ticker', how='left')
    df = df.merge(reddit[['ticker','reddit_mentions','reddit_zscore']], on='ticker', how='left')
    df = df.merge(congress[['ticker','congress_net_score','congress_recent_flag']], on='ticker', how='left')
    df = df.fillna(0)
    return df

def dot(v):
    if v:
        return '<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:#1D9E75"></span>'
    return '<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:#D3D1C7"></span>'

def score_class(s):
    if s >= 8: return 'six'
    if s >= 6: return 'five'
    if s >= 5: return 'four'
    return 'low'

def generate_html(df):
    date_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    candidates = df[(df.get('fundamental_pass', 0) == 1) & ((df.get('pattern_daily', 0) == 1) | (df.get('pattern_weekly', 0) == 1))]
    avg = df['final_score'].mean() if not df.empty else 0
    max_score = df['final_score'].max() if not df.empty else 0
    total = len(df)
    n_fund_pass = int(df.get('fundamental_pass', pd.Series(dtype=int)).sum())
    n_candidates = len(candidates)

    rows = ''
    for _, r in df.sort_values('final_score', ascending=False).iterrows():
        rev = r.get('revenue_cagr', 0) or 0
        eps = r.get('eps_cagr', 0) or 0
        peg = r.get('peg_ratio', 0) or 0
        roe = r.get('return_on_equity', 0) or 0
        roa = r.get('return_on_assets', 0) or 0
        ndebt = r.get('net_debt_to_ebitda', 0) or 0
        ev_ebitda = r.get('ev_to_ebitda', 0) or 0
        pb = r.get('price_to_book', 0) or 0
        insider_own = r.get('insider_ownership', 0) or 0
        mast = r.get('mast_rally_pct_d', 0) or 0
        retr = r.get('retracement_pct_d', 0) or 0
        si = r.get('short_float', 0)
        dtc = r.get('short_ratio', 0)
        si_color = '#854F0B' if si >= 10 else '#888'
        dtc_color = '#854F0B' if dtc >= 5 else '#888'
        reddit_m = int(r.get('reddit_mentions', 0))
        reddit_z = r.get('reddit_zscore', 0)
        reddit_color = '#854F0B' if reddit_z >= 2 else '#888'
        rows += f'''<tr>
            <td class="left tick">{r['ticker']}</td>
            <td class="left" style="font-size:10px;color:#888">{r.get('sector','')}<br>{r.get('cap_bucket','')}</td>
            <td class="left"><span class="pill {score_class(r['final_score'])}">{r['final_score']:.1f}</span></td>
            <td class="sep-fund" style="font-weight:500">{rev*100:.1f}%</td>
            <td>{eps*100:.1f}%</td>
            <td>{roe*100:.0f}%</td>
            <td>{roa*100:.0f}%</td>
            <td>{ndebt:.1f}x</td>
            <td>{peg:.2f}</td>
            <td>{ev_ebitda:.1f}x</td>
            <td>{pb:.1f}</td>
            <td class="sep-tech" style="font-weight:500">{mast*100:.0f}%</td>
            <td>{retr*100:.0f}%</td>
            <td>{dot(r.get('pattern_daily',0))}</td>
            <td>{dot(r.get('pattern_weekly',0))}</td>
            <td class="sep-insider">{dot(r.get('insider_net_positive',0))}</td>
            <td>{dot(r.get('institutional_trend',0))}</td>
            <td>{insider_own*100:.1f}%</td>
            <td class="sep-short" style="color:{si_color};font-weight:500">{si:.1f}%</td>
            <td style="color:{dtc_color}">{dtc:.1f}</td>
            <td class="sep-reddit" style="color:{reddit_color}">{reddit_m}</td>
            <td style="color:{reddit_color}">{reddit_z:.2f}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Screener Mat-Fanion</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f8f8f6; color: #1a1a1a; padding: 2rem; }}
h1 {{ font-size: 20px; font-weight: 500; margin-bottom: 4px; }}
.sub {{ font-size: 13px; color: #888; margin-bottom: 1.5rem; }}
.metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 1.5rem; }}
.m1 {{ background: #E6F1FB; border-radius: 10px; padding: 1rem; }}
.m2 {{ background: #E1F5EE; border-radius: 10px; padding: 1rem; }}
.m3 {{ background: #FAEEDA; border-radius: 10px; padding: 1rem; }}
.m4 {{ background: #FAECE7; border-radius: 10px; padding: 1rem; }}
.metric-label {{ font-size: 11px; font-weight: 500; margin-bottom: 4px; }}
.m1 .metric-label {{ color: #185FA5; }} .m1 .metric-value {{ color: #0C447C; }}
.m2 .metric-label {{ color: #0F6E56; }} .m2 .metric-value {{ color: #085041; }}
.m3 .metric-label {{ color: #854F0B; }} .m3 .metric-value {{ color: #633806; }}
.m4 .metric-label {{ color: #993C1D; }} .m4 .metric-value {{ color: #712B13; }}
.metric-value {{ font-size: 24px; font-weight: 500; }}
.table-wrap {{ overflow-x: auto; border-radius: 12px; border: 0.5px solid #e0e0d8; margin-bottom: 1.5rem; }}
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 1350px; background: #fff; }}
thead tr.group th {{ font-size: 9px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; padding: 5px 8px; border-bottom: 0.5px solid #e0e0d8; text-align: center; }}
.gh-ticker {{ background: #EEEDFE; color: #3C3489; text-align: left !important; padding-left: 12px !important; }}
.gh-fund {{ background: #E1F5EE; color: #0F6E56; border-left: 2px solid #1D9E75; }}
.gh-tech {{ background: #E6F1FB; color: #185FA5; border-left: 2px solid #378ADD; }}
.gh-insider {{ background: #FAECE7; color: #993C1D; border-left: 2px solid #D85A30; }}
.gh-short {{ background: #FAEEDA; color: #854F0B; border-left: 2px solid #EF9F27; }}
.gh-reddit {{ background: #EEEDFE; color: #3C3489; border-left: 2px solid #7F77DD; }}
thead tr.sub th {{ font-size: 10px; font-weight: 500; color: #888; padding: 5px 6px; border-bottom: 2px solid #e0e0d8; text-align: center; background: #fafaf8; }}
thead tr.sub th.left {{ text-align: left; padding-left: 12px; }}
tbody tr {{ border-bottom: 0.5px solid #f0f0ec; }}
tbody tr:last-child {{ border-bottom: none; }}
tbody tr:hover {{ background: #fafaf8; }}
tbody td {{ padding: 9px 6px; text-align: center; vertical-align: middle; }}
tbody td.left {{ text-align: left; padding-left: 12px; }}
.tick {{ font-weight: 500; font-size: 13px; }}
.pill {{ display: inline-block; padding: 3px 11px; border-radius: 999px; font-size: 12px; font-weight: 500; }}
.six  {{ background: #5DCAA5; color: #04342C; }}
.five {{ background: #C0DD97; color: #173404; }}
.four {{ background: #FAC775; color: #412402; }}
.low  {{ background: #D3D1C7; color: #2C2C2A; }}
.sep-fund    {{ border-left: 2px solid #1D9E75; }}
.sep-tech    {{ border-left: 2px solid #378ADD; }}
.sep-insider {{ border-left: 2px solid #D85A30; }}
.sep-short   {{ border-left: 2px solid #EF9F27; }}
.sep-reddit  {{ border-left: 2px solid #7F77DD; }}
.glossary {{ border: 0.5px solid #e0e0d8; border-radius: 12px; overflow: hidden; }}
.glossary-header {{ background: #EEEDFE; color: #3C3489; padding: 0.75rem 1rem; font-size: 13px; font-weight: 500; }}
.glossary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); background: #fff; }}
.glossary-item {{ padding: 0.6rem 0.875rem; border-right: 0.5px solid #e0e0d8; border-bottom: 0.5px solid #e0e0d8; }}
.glossary-item:nth-child(4n) {{ border-right: none; }}
.glossary-key {{ font-size: 11px; font-weight: 500; }}
.glossary-desc {{ font-size: 10px; color: #888; margin-top: 1px; }}
.glossary-score {{ font-size: 10px; color: #185FA5; margin-top: 1px; font-style: italic; }}
</style>
</head>
<body>
<h1>Screener mat-fanion (mid/large cap)</h1>
<p class="sub">Mis a jour le {date_str} — {total} tickers scannes</p>
<div class="metrics">
    <div class="m1"><div class="metric-label">Tickers scannes</div><div class="metric-value">{total}</div></div>
    <div class="m2"><div class="metric-label">Filtre fondamental OK</div><div class="metric-value">{n_fund_pass}</div></div>
    <div class="m3"><div class="metric-label">Candidats (fond.+pattern)</div><div class="metric-value">{n_candidates}</div></div>
    <div class="m4"><div class="metric-label">Score max</div><div class="metric-value">{max_score:.1f}</div></div>
</div>
<div class="table-wrap">
<table>
<thead>
<tr class="group">
    <th colspan="3" class="gh-ticker">Ticker</th>
    <th colspan="8" class="gh-fund">Fondamental — CAGR / ratios</th>
    <th colspan="4" class="gh-tech">Pattern mat-fanion</th>
    <th colspan="3" class="gh-insider">Bonus</th>
    <th colspan="2" class="gh-short">Short interest</th>
    <th colspan="2" class="gh-reddit">Reddit</th>
</tr>
<tr class="sub">
    <th class="left">Ticker</th><th class="left">Secteur/Cap</th><th class="left">Score</th>
    <th class="sep-fund">Rev CAGR</th><th>EPS CAGR</th><th>ROE</th><th>ROA</th><th>NetDebt/EBITDA</th><th>PEG</th><th>EV/EBITDA</th><th>P/B</th>
    <th class="sep-tech">Mat %</th><th>Retrace %</th><th>Daily</th><th>Weekly</th>
    <th class="sep-insider">Insider 90j</th><th>Instit. QoQ</th><th>Insider %</th>
    <th class="sep-short">SI%</th><th>DTC</th>
    <th class="sep-reddit">Mentions</th><th>Z-score</th>
</tr>
</thead>
<tbody>{rows}</tbody>
</table>
</div>
<div class="glossary">
<div class="glossary-header">Glossaire des criteres</div>
<div class="glossary-grid">
<div class="glossary-item"><div class="glossary-key">Rev CAGR</div><div class="glossary-desc">Croissance revenus 3-5 ans</div><div class="glossary-score">Seuil >= 8%, max 1 an de repli</div></div>
<div class="glossary-item"><div class="glossary-key">EPS CAGR</div><div class="glossary-desc">Croissance BPA 3-5 ans</div><div class="glossary-score">Seuil >= 10%, max 1 an de repli</div></div>
<div class="glossary-item"><div class="glossary-key">ROE / ROA</div><div class="glossary-desc">Rentabilite capitaux/actifs</div><div class="glossary-score">Seuils >= 15% / >= 7%</div></div>
<div class="glossary-item"><div class="glossary-key">NetDebt/EBITDA</div><div class="glossary-desc">Levier financier</div><div class="glossary-score">Seuil <= 3x</div></div>
<div class="glossary-item"><div class="glossary-key">PEG</div><div class="glossary-desc">PEG ou PE vs mediane secteur</div><div class="glossary-score">PEG <= 2 ou PE <= 1.5x mediane</div></div>
<div class="glossary-item"><div class="glossary-key">EV/EBITDA</div><div class="glossary-desc">Valorisation vs cash-flow op.</div><div class="glossary-score">Informatif, pas un filtre</div></div>
<div class="glossary-item"><div class="glossary-key">P/B</div><div class="glossary-desc">Price-to-Book</div><div class="glossary-score">Informatif, pas un filtre</div></div>
<div class="glossary-item"><div class="glossary-key">Mat %</div><div class="glossary-desc">Rally avant le plus haut</div><div class="glossary-score">Seuil >= +100%</div></div>
<div class="glossary-item"><div class="glossary-key">Retrace %</div><div class="glossary-desc">Retracement depuis le plus haut</div><div class="glossary-score">Zone ideale -30% a -50%</div></div>
<div class="glossary-item"><div class="glossary-key">Daily/Weekly</div><div class="glossary-desc">Pattern confirme sur l'unite de temps</div><div class="glossary-score">Consolidation 3-6 mois, range serre</div></div>
<div class="glossary-item"><div class="glossary-key">Insider 90j</div><div class="glossary-desc">Achats nets Form 4</div><div class="glossary-score">Bonus si net > 0 sur 90 jours</div></div>
<div class="glossary-item"><div class="glossary-key">Instit. QoQ</div><div class="glossary-desc">Detention institutionnelle</div><div class="glossary-score">Bonus si en hausse vs ~90j</div></div>
<div class="glossary-item"><div class="glossary-key">Insider %</div><div class="glossary-desc">Detention des dirigeants</div><div class="glossary-score">Gouvernance : PDG actionnaire = bon signe</div></div>
<div class="glossary-item"><div class="glossary-key">SI%</div><div class="glossary-desc">Short Interest % du float</div><div class="glossary-score">Signal fort si >= 10%</div></div>
<div class="glossary-item"><div class="glossary-key">DTC</div><div class="glossary-desc">Days to Cover</div><div class="glossary-score">Signal fort si >= 5 jours</div></div>
<div class="glossary-item"><div class="glossary-key">Mentions</div><div class="glossary-desc">Mentions Reddit sur 7 jours</div><div class="glossary-score">r/smallcaps r/stocks r/wsb r/investing</div></div>
<div class="glossary-item"><div class="glossary-key">Z-score</div><div class="glossary-desc">Anomalie de mentions Reddit</div><div class="glossary-score">Signal si z-score >= 2</div></div>
</div>
</div>
</body>
</html>'''
    return html

def run():
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    log = logging.getLogger(__name__)
    log.info('STEP 8 - DASHBOARD HTML')
    df = load_data()
    html = generate_html(df)
    with open(DASHBOARD_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    log.info(f'Dashboard genere : {DASHBOARD_PATH}')

if __name__ == '__main__':
    run()
