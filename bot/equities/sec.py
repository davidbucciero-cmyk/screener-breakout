"""Donnees SEC : tickers, nombre d'actions (page de garde) et comptes annuels via l'API XBRL frames.

Une frame renvoie, pour une periode calendaire, une valeur par entreprise (la derniere deposee pour
cette periode). Les comptes annuels sont consideres connus 90 jours apres la fin de l'exercice.
"""
import logging
import os
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)
# La SEC exige un User-Agent avec un contact ; meme valeur que screener/scripts/step3_insiders.py.
UA = {'User-Agent': os.environ.get('SEC_USER_AGENT', 'david.bucciero@outlook.fr'),
      'Accept-Encoding': 'gzip, deflate'}
FRAMES = 'https://data.sec.gov/api/xbrl/frames/{tax}/{tag}/{unit}/{period}.json'

REVENUE_TAGS = ['Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax', 'SalesRevenueNet']
COST_TAGS = ['CostOfRevenue', 'CostOfGoodsAndServicesSold', 'CostOfGoodsSold']
ANNUAL_TAGS = {'gross_profit': ['GrossProfit'], 'revenue': REVENUE_TAGS, 'cost_of_revenue': COST_TAGS,
               'net_income': ['NetIncomeLoss'], 'cfo': ['NetCashProvidedByUsedInOperatingActivities']}


def get(url, retries=4):
    for attempt in range(retries):
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 404:
            return None
        if r.ok:
            time.sleep(0.12)  # limite SEC : 10 requetes/s
            return r
        log.warning(f'{url} : HTTP {r.status_code}, retry')
        time.sleep(2 ** attempt)
    r.raise_for_status()


def company_tickers():
    js = get('https://www.sec.gov/files/company_tickers_exchange.json').json()
    df = pd.DataFrame(js['data'], columns=js['fields'])
    df = df[df['exchange'].isin(['NYSE', 'Nasdaq'])].dropna(subset=['ticker'])
    df['ticker'] = df['ticker'].str.upper().str.replace('.', '-', regex=False)  # convention Yahoo
    return df[['cik', 'ticker', 'name', 'exchange']].drop_duplicates('ticker')


def parse_frame(js):
    df = pd.DataFrame(js.get('data', []))
    if df.empty:
        return df
    df['end'] = pd.to_datetime(df['end'])
    return df[['cik', 'end', 'val']]


def frame(tag, period, unit='USD', tax='us-gaap'):
    r = get(FRAMES.format(tax=tax, tag=tag, unit=unit, period=period))
    return parse_frame(r.json()) if r is not None else pd.DataFrame(columns=['cik', 'end', 'val'])


def shares_outstanding(first_year=2009, last_year=None):
    """Nombre d'actions par CIK et date de page de garde (trimestriel)."""
    last_year = last_year or pd.Timestamp.now().year
    parts = []
    for y in range(first_year, last_year + 1):
        for q in range(1, 5):
            df = frame('EntityCommonStockSharesOutstanding', f'CY{y}Q{q}I', unit='shares', tax='dei')
            parts.append(df)
    out = pd.concat(parts, ignore_index=True).dropna()
    return out[out['val'] > 0].drop_duplicates(['cik', 'end']).sort_values(['cik', 'end'])


def annual_fundamentals(first_year=2008, last_year=None):
    """Une ligne par (cik, annee) : revenue, gross_profit, net_income, cfo, assets, et date de disponibilite."""
    last_year = last_year or pd.Timestamp.now().year - 1
    rows = []
    for y in range(first_year, last_year + 1):
        cols = {}
        for name, tags in ANNUAL_TAGS.items():
            s = None
            for tag in tags:  # premier tag renseigne pour chaque entreprise
                df = frame(tag, f'CY{y}')
                v = df.set_index('cik')['val'] if not df.empty else pd.Series(dtype=float)
                v = v[~v.index.duplicated()]
                s = v if s is None else s.combine_first(v)
            cols[name] = s
        assets = frame('Assets', f'CY{y}Q4I').drop_duplicates('cik').set_index('cik')
        cols['assets'] = assets['val'] if not assets.empty else pd.Series(dtype=float)
        df = pd.DataFrame(cols)
        df['year'] = y
        end = assets['end'] if not assets.empty else pd.Series(dtype='datetime64[ns]')
        df['period_end'] = pd.to_datetime(end.reindex(df.index)).fillna(pd.Timestamp(f'{y}-12-31'))
        rows.append(df.reset_index(names='cik'))
        log.info(f'Comptes annuels {y} : {len(df)} entreprises')
    out = pd.concat(rows, ignore_index=True)
    gp_fallback = out['revenue'] - out['cost_of_revenue']
    out['gross_profit'] = out['gross_profit'].fillna(gp_fallback)
    out['available'] = out['period_end'] + pd.Timedelta(days=90)
    return out
