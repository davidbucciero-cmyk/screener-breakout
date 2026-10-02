"""Strategies multi-actifs BTC/ETH/SOL (toutes negociables en spot sur Alpaca crypto).

Troisieme serie d'idees, fixees a priori le 2026-10-02 avant tout backtest :
G - Rotation momentum : chaque dimanche, on detient la crypto au meilleur rendement 30 j si ce
    rendement est positif, sinon cash. Exposition ciblee a 40 % de vol annuelle, sans levier.
H - Trend diversifie : trend ensemble + ciblage vol (strategie B) sur chacune des 3 cryptos, un
    tiers du capital chacune. C'est la strategie du compte demo actuel, ici avec les frais Alpaca.
Decision a la cloture du jour d (00:00 UTC d+1), appliquee aux bougies 1h du jour d+1.
"""
import math

import numpy as np
import pandas as pd

from btc_forecast.trend import apply_band, trend_signals, vol_target
from bot.strategies import BAND, COST, TARGET_VOL

SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']


def _closes(dfs):
    hourly = pd.DataFrame({s: d['close'] for s, d in dfs.items()}).dropna()
    daily = hourly.resample('1D').last().dropna()
    return hourly, daily


def _apply(hourly, w_daily):
    """Rendements nets 1h du portefeuille, trades par actif, poids 1h."""
    key = hourly.index.floor('D') - pd.Timedelta(days=1)
    w = pd.DataFrame(w_daily.reindex(key).to_numpy(), index=hourly.index, columns=hourly.columns).fillna(0.0)
    ret = hourly.pct_change().fillna(0.0)
    per_asset = w * ret - w.diff().abs().fillna(w.abs()) * COST
    r = per_asset.sum(axis=1)
    rows = []
    for s in w.columns:
        active = w[s] > 0
        seg = (active != active.shift()).cumsum()[active]
        for _, idx in seg.groupby(seg).groups.items():
            rows.append({'entry_time': idx[0], 'exit_time': idx[-1] + pd.Timedelta(hours=1), 'actif': s,
                         'hours': len(idx), 'pnl': float((1 + per_asset[s].loc[idx]).prod() - 1)})
    trades = pd.DataFrame(rows, columns=['entry_time', 'exit_time', 'actif', 'hours', 'pnl'])
    return r, trades.sort_values('entry_time').reset_index(drop=True), w


def rotation_momentum(dfs, lookback=30, top_k=1, risk_off=None):
    """Chaque dimanche : les top_k cryptos au meilleur rendement `lookback` j, si ce rendement est > 0.

    Chaque ligne pese 1/top_k, reduite pour viser 40 % de vol. risk_off (booleen quotidien, connu a
    la cloture du jour) force le cash le lendemain, meme en cours de semaine.
    """
    hourly, daily = _closes(dfs)
    mom = daily / daily.shift(lookback) - 1
    vol = daily.pct_change().rolling(30).std() * math.sqrt(365)
    rank = mom.rank(axis=1, ascending=False, method='first')
    sel = (rank <= top_k) & (mom > 0) & (vol > 0)
    w = (sel * (TARGET_VOL / vol).clip(upper=1.0) / top_k).fillna(0.0)
    # Re-balance hebdomadaire (cloture du dimanche), poids tenus jusqu'au suivant.
    w = w[w.index.dayofweek == 6].reindex(w.index).ffill().fillna(0.0)
    if risk_off is not None:
        w = w.mul(1 - risk_off.reindex(w.index).fillna(False).astype(float), axis=0)
    return _apply(hourly, w)


def diversified_trend(dfs):
    hourly, daily = _closes(dfs)
    w = pd.DataFrame(index=daily.index)
    for s in daily.columns:
        ens = trend_signals(daily[s])['ensemble']
        vol = daily[s].pct_change().rolling(30).std() * math.sqrt(365)
        w[s] = apply_band(vol_target(ens, vol, target=TARGET_VOL, max_leverage=1.0), BAND) / len(daily.columns)
    return _apply(hourly, w.clip(lower=0).fillna(0.0))


def equal_weight_hold(dfs):
    hourly, daily = _closes(dfs)
    w = pd.DataFrame(1 / len(daily.columns), index=daily.index, columns=daily.columns)
    return _apply(hourly, w)


MULTI = {
    'G - Rotation momentum BTC/ETH/SOL': rotation_momentum,
    'H - Trend diversifie BTC/ETH/SOL': diversified_trend,
}


# --- Quatrieme serie, fixee a priori le 2026-10-02 avant tout backtest ------------------------------
# I - Momentum transversal sur 11 cryptos negociables sur Alpaca : chaque dimanche, les 3 meilleures
#     sur 30 j si leur rendement est > 0, un tiers chacune, vol ciblee. Facteur documente en crypto
#     (Liu, Tsyvinski & Wu 2022). Extension de G a un univers plus large.
# J - G + filtre de financement : cash le lendemain si le funding moyen 7 j du perpetuel BTC est dans
#     le decile haut de l'annee passee (longs a levier encombres).
# K - Panier de strategies : un tiers G, un tiers H, un tiers E (diversification entre strategies).
UNIVERSE = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOGEUSDT', 'LTCUSDT',
            'BCHUSDT', 'UNIUSDT', 'AAVEUSDT', 'DOTUSDT']


def cross_sectional_momentum(dfs_universe):
    return rotation_momentum(dfs_universe, top_k=3)


def rotation_with_funding(dfs, crowded):
    return rotation_momentum(dfs, risk_off=crowded)


def blend(*results):
    """Capital reparti a parts egales entre strategies (rendements nets deja frais inclus)."""
    rs = pd.concat([r for r, _ in results], axis=1).dropna()
    trades = pd.concat([t for _, t in results], ignore_index=True)
    return rs.mean(axis=1), trades
