"""Taux de financement du perpetuel BTC (BitMEX XBTUSD, toutes les 8h), API publique sans cle.

Funding eleve = les acheteurs a levier paient cher pour rester longs : marche encombre a la hausse.
"""
import logging
import time

import pandas as pd
import requests

log = logging.getLogger(__name__)
URL = 'https://www.bitmex.com/api/v1/funding'


def fetch_funding(start, symbol='XBTUSD'):
    cursor = pd.Timestamp(start)
    cursor = cursor.tz_localize('UTC') if cursor.tzinfo is None else cursor
    rows = []
    while True:
        r = requests.get(URL, params={'symbol': symbol, 'count': 500, 'reverse': 'false',
                                      'startTime': cursor.isoformat()}, timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        last = pd.Timestamp(batch[-1]['timestamp'])
        if len(batch) < 500 or last <= cursor:
            break
        cursor = last + pd.Timedelta(seconds=1)
        time.sleep(1.5)  # limite publique BitMEX
    s = pd.Series({pd.Timestamp(x['timestamp']): float(x['fundingRate']) for x in rows}).sort_index()
    log.info(f'{len(s)} taux de financement {symbol} du {s.index[0]} au {s.index[-1]}')
    return s


def crowded_longs(funding, window_days=7, history_days=365, quantile=0.9):
    """Vrai le jour d si le funding moyen sur 7 j est dans le decile haut de l'annee passee.

    Calcule uniquement avec les taux publies au plus tard a la cloture du jour d.
    """
    daily = funding.resample('1D').mean()
    avg = daily.rolling(window_days, min_periods=window_days).mean()
    thr = avg.rolling(history_days, min_periods=180).quantile(quantile)
    return (avg > thr).where(thr.notna(), False).astype(bool)
