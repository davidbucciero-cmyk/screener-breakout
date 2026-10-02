"""Ameliorations de G, fixees le 2026-10-02 AVANT de regarder la periode 2018-2022 (jamais utilisee).

G  - reference : top 1 sur 30 j, cash si rendement negatif, vol ciblee 40 %.
G1 - plusieurs horizons : moyenne des rendements 14/30/60/90 j (moins dependant d'un parametre).
G2 - G + filtre BTC : cash le lendemain de toute cloture de BTC sous sa moyenne 200 j.
     Idee inspiree des resultats par regime deja vus sur 2022-2026 (pertes en marche baissier calme).
G3 - les 2 meilleures cryptos, moitie chacune (moins de risque sur un seul actif).
"""
import pandas as pd

from bot.multi import _closes, rotation_momentum

LOOKBACKS = (14, 30, 60, 90)


def btc_below_sma200(dfs):
    _, daily = _closes(dfs)
    btc = daily['BTCUSDT']
    sma = btc.rolling(200).mean()
    return (btc < sma).where(sma.notna(), False).astype(bool)


VARIANTS = {
    'G - reference (top 1, 30 j)': lambda d: rotation_momentum(d),
    'G1 - horizons 14/30/60/90 j': lambda d: rotation_momentum(d, lookbacks=LOOKBACKS),
    'G2 - G + filtre BTC > moyenne 200 j': lambda d: rotation_momentum(d, risk_off=btc_below_sma200(d)),
    'G3 - top 2, moitie chacune': lambda d: rotation_momentum(d, top_k=2),
}
