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
    technical = pd.read_sql('SELECT * FROM technical_signals', conn)
    short = pd.read_sql('SELECT * FROM short_signals', conn) if 'short_signals' in tables else pd.DataFrame(columns=['ticker','short_float','short_ratio'])
    reddit = pd.read_sql('SELECT * FROM reddit_signals', conn) if 'reddit_signals' in tables else pd.DataFrame(columns=['ticker','reddit_mentions','reddit_zscore','reddit_signal'])
    conn.close()
    df = scores.merge(technical[['ticker','obv_trend','vol_ratio','vol_dryup','bb_squeeze','atr_declining','flat_base','higher_lows','ad_trend','rs_line']], on='ticker', how='left')
    df = df.merge(short[['ticker','short_float','short_ratio']], on='ticker', how='left')
    df = df.merge(reddit[['ticker','reddit_mentions','reddit_zscore']], on='ticker', how='left')
    df = df.fillna(0)
    return df

def dot(v):
    if v:
        return '<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:#1D9E75"></span>'
    return '<span style="display:inline-block;width:11px;height:11px;border-radius:50%;background:#D3D1C7"></span>'

def score_class(s):
    if s >= 6: return 'six'
    if s >= 5: return 'five'
    if s >= 4: return 'four'
    return 'low'

def generate_html(df):
    date_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    avg = df['final_score'].mean()
    max_score = df['final_score'].max()
    cand5 = len(df[df['final_score'] >= 5])
    total = len(df)

    rows = ''
    for _, r in df.iterrows():
        vol_signal = 1 if r.get('vol_ratio', 0) >= 1.5 else 0
        rev = r.get('revenue_growth', 0)
        rev_str = '>999%' if rev > 999 else f"{rev:.1f}%"
        rev_color = '#0F6E56' if rev >= 20 else '#888'
        si = r.get('short_float', 0)
        dtc = r.get('short_ratio', 0)
        si_color = '#854F0B' if si >= 10 else '#888'
        dtc_color = '#854F0B' if dtc >= 5 else '#888'
        fcf = 1 if r.get('fcf_positive', 0) else 0
        marge = 1 if r.get('gross_margin_trend', 0) else 0
        reddit_m = int(r.get('reddit_mentions', 0))
        reddit_z = r.get('reddit_zscore', 0)
        reddit_color = '#854F0B' if reddit_z >= 2 else '#888'
        rows += f'''<tr>
            <td class="left tick">{r['ticker']}</td>
            <td class="left"><span class="pill {score_class(r['final_score'])}">{r['final_score']:.1f}</span></td>
            <td class="sep-tech">{dot(r.get('obv_trend',0))}</td>
            <td>{dot(vol_signal)}</td>
            <td>{dot(r.get('vol_dryup',0))}</td>
            <td>{dot(r.get('bb_squeeze',0))}</td>
            <td>{dot(r.get('atr_declining',0))}</td>
            <td>{dot(r.get('flat_base',0))}</td>
            <td>{dot(r.get('higher_lows',0))}</td>
            <td>{dot(r.get('ad_trend',0))}</td>
            <td>{dot(r.get('rs_line',0))}</td>
            <td class="sep-fund" style="color:{rev_color};font-weight:500">{rev_str}</td>
            <td>{dot(fcf)}</td>
            <td>{dot(marge)}</td>
            <td class="sep-short" style="color:{si_color};font-weight:500">{si:.1f}%</td>
            <td style="color:{dtc_color}">{dtc:.1f}</td>
            <td class="sep-insider" style="color:#888">{r.get('insider_score',0):.0f}/10</td>
            <td>{dot(r.get('cluster_buy',0))}</td>
            <td class="sep-reddit" style="color:{reddit_color}">{reddit_m}</td>
            <td style="color:{reddit_color}">{reddit_z:.2f}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Screener Pre-Breakout</title>
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
table {{ width: 100%; border-collapse: collapse; font-size: 11px; min-width: 1050px; background: #fff; }}
thead tr.group th {{ font-size: 9px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.06em; padding: 5px 8px; border-bottom: 0.5px solid #e0e0d8; text-align: center; }}
.gh-ticker {{ background: #EEEDFE; color: #3C3489; text-align: left !important; padding-left: 12px !important; }}
.gh-tech {{ background: #E6F1FB; color: #185FA5; border-left: 2px solid #378ADD; }}
.gh-fund {{ background: #E1F5EE; color: #0F6E56; border-left: 2px solid #1D9E75; }}
.gh-short {{ background: #FAEEDA; color: #854F0B; border-left: 2px solid #EF9F27; }}
.gh-insider {{ background: #FAECE7; color: #993C1D; border-left: 2px solid #D85A30; }}
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
.sep-tech    {{ border-left: 2px solid #378ADD; }}
.sep-fund    {{ border-left: 2px solid #1D9E75; }}
.sep-short   {{ border-left: 2px solid #EF9F27; }}
.sep-insider {{ border-left: 2px solid #D85A30; }}
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
<h1>Screener pre-breakout</h1>
<p class="sub">Mis a jour le {date_str} — {total} tickers scannes</p>
<div class="metrics">
    <div class="m1"><div class="metric-label">Tickers scannes</div><div class="metric-value">{total}</div></div>
    <div class="m2"><div class="metric-label">Score moyen</div><div class="metric-value">{avg:.1f}</div></div>
    <div class="m3"><div class="metric-label">Score max</div><div class="metric-value">{max_score:.1f}</div></div>
    <div class="m4"><div class="metric-label">Candidats >= 5</div><div class="metric-value">{cand5}</div></div>
</div>
<div class="table-wrap">
<table>
<thead>
<tr class="group">
    <th colspan="2" class="gh-ticker">Ticker</th>
    <th colspan="9" class="gh-tech">Technique — 9 criteres</th>
    <th colspan="3" class="gh-fund">Fondamental</th>
    <th colspan="2" class="gh-short">Short interest</th>
    <th colspan="2" class="gh-insider">Insider</th>
    <th colspan="2" class="gh-reddit">Reddit</th>
</tr>
<tr class="sub">
    <th class="left">Ticker</th><th class="left">Score</th>
    <th class="sep-tech">OBV</th><th>Vol+</th><th>Dry</th><th>BB</th><th>ATR</th><th>Base</th><th>HiLo</th><th>A/D</th><th>RS</th>
    <th class="sep-fund">Rev%</th><th>FCF</th><th>Marge</th>
    <th class="sep-short">SI%</th><th>DTC</th>
    <th class="sep-insider">Score</th><th>Cluster</th>
    <th class="sep-reddit">Mentions</th><th>Z-score</th>
</tr>
</thead>
<tbody>{rows}</tbody>
</table>
</div>
<div class="glossary">
<div class="glossary-header">Glossaire des criteres</div>
<div class="glossary-grid">
<div class="glossary-item"><div class="glossary-key">OBV</div><div class="glossary-desc">On Balance Volume haussier</div><div class="glossary-score">OBV > SMA 20j</div></div>
<div class="glossary-item"><div class="glossary-key">Vol+</div><div class="glossary-desc">Volume anormalement eleve</div><div class="glossary-score">> 1.5x moyenne 20j</div></div>
<div class="glossary-item"><div class="glossary-key">Dry</div><div class="glossary-desc">Dry-up volume en fin de base</div><div class="glossary-score">< 70% moy 20j sur 5j</div></div>
<div class="glossary-item"><div class="glossary-key">BB</div><div class="glossary-desc">Bollinger Squeeze</div><div class="glossary-score">Bandes au plus etroit sur 125j</div></div>
<div class="glossary-item"><div class="glossary-key">ATR</div><div class="glossary-desc">Volatilite en hausse</div><div class="glossary-score">ATR14 > ATR14 il y a 10j (IC corrige)</div></div>
<div class="glossary-item"><div class="glossary-key">Base</div><div class="glossary-desc">Flat base detectee</div><div class="glossary-score">Range < 15% sur 20j</div></div>
<div class="glossary-item"><div class="glossary-key">HiLo</div><div class="glossary-desc">Higher lows successifs (x2)</div><div class="glossary-score">3 creux en hausse sur 60j — IC fort</div></div>
<div class="glossary-item"><div class="glossary-key">A/D</div><div class="glossary-desc">Accumulation/Distribution (x2)</div><div class="glossary-score">A/D > SMA 20j — IC le plus fort (0.52)</div></div>
<div class="glossary-item"><div class="glossary-key">RS</div><div class="glossary-desc">RS Line vs IWM Russell 2000</div><div class="glossary-score">RS > SMA 20j</div></div>
<div class="glossary-item"><div class="glossary-key">Rev%</div><div class="glossary-desc">Croissance revenus YoY</div><div class="glossary-score">Signal fort si >= +20%</div></div>
<div class="glossary-item"><div class="glossary-key">FCF</div><div class="glossary-desc">Free Cash Flow positif</div><div class="glossary-score">FCF > 0 dernier exercice</div></div>
<div class="glossary-item"><div class="glossary-key">Marge</div><div class="glossary-desc">Marge brute en hausse</div><div class="glossary-score">Marge N > Marge N-1</div></div>
<div class="glossary-item"><div class="glossary-key">SI%</div><div class="glossary-desc">Short Interest % du float</div><div class="glossary-score">Signal fort si >= 10%</div></div>
<div class="glossary-item"><div class="glossary-key">DTC</div><div class="glossary-desc">Days to Cover</div><div class="glossary-score">Signal fort si >= 5 jours</div></div>
<div class="glossary-item"><div class="glossary-key">Insider</div><div class="glossary-desc">Score insider buying Form 4</div><div class="glossary-score">Cluster buy = +3 pts</div></div>
<div class="glossary-item"><div class="glossary-key">Cluster</div><div class="glossary-desc">Cluster Buy detecte</div><div class="glossary-score">2+ insiders en 30 jours</div></div>
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