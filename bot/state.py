"""Moteur d'etat deterministe : une bougie 1h cloturee -> un snapshot numerique compact.

Convention de temps : df est indexe par l'heure d'OUVERTURE des bougies. La bougie ouverte a t
cloture a t+1h ; son snapshot est indexe a t+1h, l'instant ou la decision est prise. Un snapshot
n'utilise donc que des bougies entierement cloturees avant la decision (test anti-lookahead dedie).

C'est la seule chose que Jev verra. Carnet d'ordres et spread sont ajoutes en live seulement
(pas d'historique gratuit), journalises mais hors de la decision tant qu'ils ne sont pas backtestables.
"""
import math

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 24 * 365
FLAG_LEN = 12   # heures de consolidation (fanion)
MAST_LEN = 48   # heures de hausse avant le fanion (mat)

FEATURES = [
    'close', 'ret_1h', 'ret_4h', 'ret_24h', 'vol_24h', 'vol_7d',
    'trend_20d', 'trend_60d', 'trend_120d', 'taker_buy_24h',
    'mast_gain_48h', 'flag_range_12h', 'flag_retrace', 'breakout_dist',
]


def build_snapshots(df):
    """Snapshots pour toutes les bougies cloturees. Colonnes = FEATURES, index = instant de decision."""
    c = df['close'].astype(float)
    logret = np.log(c).diff()
    out = pd.DataFrame(index=df.index)
    out['close'] = c
    for h in (1, 4, 24):
        out[f'ret_{h}h'] = np.log(c / c.shift(h))
    out['vol_24h'] = logret.rolling(24).std() * math.sqrt(HOURS_PER_YEAR)
    out['vol_7d'] = logret.rolling(24 * 7).std() * math.sqrt(HOURS_PER_YEAR)
    for d in (20, 60, 120):
        out[f'trend_{d}d'] = c / c.shift(24 * d) - 1
    if 'taker_buy_volume' in df:
        out['taker_buy_24h'] = df['taker_buy_volume'].rolling(24).sum() / df['volume'].rolling(24).sum()
    else:
        out['taker_buy_24h'] = np.nan

    # Mat-fanion en 1h : mat = les MAST_LEN bougies avant le fanion, fanion = les FLAG_LEN dernieres.
    flag_high = df['high'].rolling(FLAG_LEN).max()
    flag_low = df['low'].rolling(FLAG_LEN).min()
    mast_low = df['low'].shift(FLAG_LEN).rolling(MAST_LEN).min()
    peak = df['high'].rolling(MAST_LEN + FLAG_LEN).max()
    out['mast_gain_48h'] = c.shift(FLAG_LEN) / mast_low - 1
    out['flag_range_12h'] = (flag_high - flag_low) / flag_low
    out['flag_retrace'] = ((peak - flag_low) / (peak - mast_low)).clip(lower=0)
    # Distance au plus haut du fanion hors bougie courante : > 0 = cassure.
    out['breakout_dist'] = c / df['high'].shift(1).rolling(FLAG_LEN).max() - 1

    out.index = out.index + pd.Timedelta(hours=1)
    return out[FEATURES].astype(float)


def snapshot_at(df, decision_time):
    """Snapshot live : ne garde que les bougies cloturees a `decision_time`, quoi que contienne df."""
    closed = df[df.index + pd.Timedelta(hours=1) <= decision_time]
    return build_snapshots(closed.iloc[-(24 * 121):]).iloc[-1].rename(decision_time)
