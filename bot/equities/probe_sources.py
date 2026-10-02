"""Sonde des sources payantes : chaque endpoint repond-il, combien de lignes, sur quelle periode ?

N'affiche jamais les cles ni les donnees, seulement : statut HTTP, nombre de lignes, colonnes, dates min/max.
"""
import os

import pandas as pd
import requests

QUIVER = 'https://api.quiverquant.com/beta'
FMP = 'https://financialmodelingprep.com'
QUIVER_ENDPOINTS = [
    '/bulk/congresstrading', '/live/congresstrading', '/historical/congresstrading/AAPL',
    '/live/govcontractsall', '/historical/govcontractsall/LMT', '/historical/govcontracts/LMT',
    '/live/lobbying', '/historical/lobbying/AAPL',
    '/live/insiders', '/historical/offexchange/AAPL', '/historical/wallstreetbets/AAPL',
]
FMP_ENDPOINTS = [
    '/stable/earnings?symbol=AAPL&limit=200', '/api/v3/earnings-surprises/AAPL',
    '/api/v3/historical/earning_calendar/AAPL', '/stable/analyst-estimates?symbol=AAPL&period=annual&limit=40',
    '/stable/grades-historical?symbol=AAPL&limit=200', '/stable/grades?symbol=AAPL&limit=200',
    '/stable/senate-trades?symbol=AAPL', '/stable/house-trades?symbol=AAPL',
    '/stable/earning-call-transcript?symbol=AAPL&year=2015&quarter=1',
]
DATE_COLS = ['TransactionDate', 'ReportDate', 'Date', 'date', 'Filed', 'transactionDate', 'disclosureDate',
             'publishedDate', 'action_date', 'Year']


def describe(name, r):
    if not r.ok:
        return f'{name} : HTTP {r.status_code} {r.text[:120]!r}'
    try:
        js = r.json()
    except ValueError:
        return f'{name} : HTTP 200, reponse non JSON'
    if isinstance(js, dict):
        if any(k in js for k in ('Error Message', 'error', 'message')):
            return f'{name} : HTTP 200 mais refus : {str(js)[:150]!r}'
        js = js.get('data', [js])
    df = pd.DataFrame(js)
    if df.empty:
        return f'{name} : HTTP 200, 0 ligne'
    span = ''
    for c in DATE_COLS:
        if c in df.columns:
            d = pd.to_datetime(df[c], errors='coerce').dropna()
            if len(d):
                span = f', {c} de {d.min():%Y-%m-%d} a {d.max():%Y-%m-%d}'
                break
    return f'{name} : HTTP 200, {len(df)} lignes{span}, colonnes {list(df.columns)[:12]}'


def main():
    qk, fk = os.environ.get('QUIVER_API_KEY'), os.environ.get('FMP_API_KEY')
    print(f"QUIVER_API_KEY : {'presente' if qk else 'ABSENTE'} ; FMP_API_KEY : {'presente' if fk else 'ABSENTE'}\n")
    if qk:
        h = {'Accept': 'application/json', 'Authorization': f'Bearer {qk}'}
        for ep in QUIVER_ENDPOINTS:
            try:
                print(describe(f'Quiver {ep}', requests.get(QUIVER + ep, headers=h, timeout=120)))
            except requests.RequestException as e:
                print(f'Quiver {ep} : erreur reseau {type(e).__name__}')
    print()
    if fk:
        for ep in FMP_ENDPOINTS:
            url = FMP + ep + ('&' if '?' in ep else '?') + f'apikey={fk}'
            try:
                print(describe(f'FMP {ep}', requests.get(url, timeout=60)))
            except requests.RequestException as e:
                print(f'FMP {ep} : erreur reseau {type(e).__name__}')


if __name__ == '__main__':
    main()
