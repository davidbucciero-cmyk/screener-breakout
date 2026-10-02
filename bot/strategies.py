"""Strategies candidates, parametres fixes a priori (non optimises, pour ne pas sur-ajuster).

Toutes les series de rendements sont indexees par l'heure d'OUVERTURE de la bougie sur laquelle
le rendement est gagne. Une decision prise a l'instant D (= cloture de la bougie precedente) porte
sur la bougie ouverte a D.

A - Breakout mat-fanion 1h : mat >= 5 % en 48h, fanion <= 4 % de range sur 12h, retracement <= 50 %
    du mat, cloture au-dessus du plus haut du fanion. Stop sous le fanion, objectif = hauteur du mat,
    sortie au plus tard apres 72h.
B - Trend ensemble quotidien (20/60/120/250 j) + ciblage vol 40 %/an, sans levier, bande 10 %
    (meme logique que btc_forecast/trend.py, le compte demo actuel).
C - A, seulement quand l'ensemble de B est >= 0.5 (tendance de fond haussiere).
"""
import math

import numpy as np
import pandas as pd

from btc_forecast.trend import apply_band, trend_signals, vol_target
from bot.state import FLAG_LEN, MAST_LEN, build_snapshots

FEE_BPS = 25.0       # taker Alpaca crypto, par cote
SLIPPAGE_BPS = 5.0   # par cote
COST = (FEE_BPS + SLIPPAGE_BPS) / 1e4

MAST_MIN = 0.05
FLAG_RANGE_MAX = 0.04
RETRACE_MAX = 0.5
MAX_HOURS = 72
TARGET_VOL = 0.40
BAND = 0.10


def simulate_trades(df, entries, stop_pct, target_pct, max_hours=MAX_HOURS):
    """Long uniquement, une position a la fois, entree a la cloture de la bougie signal.

    entries / stop_pct / target_pct : indexes par instant de decision (cloture de bougie).
    Stop et objectif testes sur high/low de chaque bougie suivante ; si les deux sont touches dans la
    meme bougie, on suppose le stop (pire cas). Gap sous le stop : sortie a l'ouverture.
    """
    o, h, l, c = (df[k].to_numpy(float) for k in ('open', 'high', 'low', 'close'))
    decision = df.index + pd.Timedelta(hours=1)
    sig = entries.reindex(decision).fillna(False).to_numpy(bool)
    sp = stop_pct.reindex(decision).to_numpy(float)
    tp = target_pct.reindex(decision).to_numpy(float)
    r = np.zeros(len(df))
    trades = []
    i, n = 0, len(df)
    while i < n - 1:
        if not sig[i] or not (sp[i] > 0) or not (tp[i] > 0):
            i += 1
            continue
        entry = c[i]
        stop, target = entry * (1 - sp[i]), entry * (1 + tp[i])
        prev = entry
        j = i + 1
        while True:
            reason, px = None, c[j]
            if o[j] <= stop:
                reason, px = 'stop', o[j]
            elif l[j] <= stop:
                reason, px = 'stop', stop
            elif o[j] >= target:
                reason, px = 'objectif', o[j]
            elif h[j] >= target:
                reason, px = 'objectif', target
            elif j - i >= max_hours:
                reason = 'temps'
            elif j == n - 1:
                reason = 'fin'
            gross = px / prev
            if j == i + 1:
                gross *= 1 - COST
            if reason:
                gross *= 1 - COST
            r[j] = gross - 1
            prev = px
            if reason:
                trades.append({'entry_time': decision[i], 'exit_time': decision[j], 'entry_price': entry,
                               'exit_price': px, 'hours': j - i, 'reason': reason,
                               'pnl': (1 - COST) ** 2 * px / entry - 1})
                break
            j += 1
        i = j  # re-entree possible des la cloture de la bougie de sortie
    cols = ['entry_time', 'exit_time', 'entry_price', 'exit_price', 'hours', 'reason', 'pnl']
    return pd.Series(r, index=df.index), pd.DataFrame(trades, columns=cols)


def flag_setup(df):
    """Signal mat-fanion + stop/objectif en % du prix d'entree, indexes par instant de decision."""
    snap = build_snapshots(df)
    entries = ((snap['breakout_dist'] > 0) & (snap['mast_gain_48h'] >= MAST_MIN)
               & (snap['flag_range_12h'] <= FLAG_RANGE_MAX) & (snap['flag_retrace'] <= RETRACE_MAX))
    shift = pd.Timedelta(hours=1)
    flag_low = df['low'].rolling(FLAG_LEN).min()
    mast_low = df['low'].shift(FLAG_LEN).rolling(MAST_LEN).min()
    peak = df['high'].rolling(MAST_LEN + FLAG_LEN).max()
    stop_pct = (1 - flag_low / df['close']).set_axis(df.index + shift)
    target_pct = ((peak - mast_low) / df['close']).set_axis(df.index + shift)
    return entries, stop_pct, target_pct


def trend_positions(df, target_vol=TARGET_VOL, band=BAND):
    """Exposition 0..1 par bougie 1h et ensemble de tendance, decides sur les clotures journalieres.

    Le jour d (bougies ouvertes de d 00:00 a d 23:00) cloture a d+1 00:00 : son signal s'applique
    aux bougies du jour d+1.
    """
    daily = df['close'].resample('1D').last().dropna()
    sig = trend_signals(daily)
    vol = daily.pct_change().rolling(30).std() * math.sqrt(365)
    pos_daily = apply_band(vol_target(sig['ensemble'], vol, target=target_vol, max_leverage=1.0), band)
    key = df.index.floor('D') - pd.Timedelta(days=1)
    pos = pd.Series(pos_daily.reindex(key).to_numpy(), index=df.index).fillna(0.0).clip(0, 1)
    ens = pd.Series(sig['ensemble'].reindex(key).to_numpy(), index=df.index)
    return pos, ens


def position_returns(df, pos):
    """Rendements nets d'une exposition fractionnaire tenue bougie par bougie."""
    ret = df['close'].pct_change().fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    return pos * ret - turnover * COST


def position_trades(df, pos, r):
    """Trades = periodes continues d'exposition > 0."""
    active = pos > 0
    seg = (active != active.shift()).cumsum()[active]
    rows = []
    for _, idx in seg.groupby(seg).groups.items():
        rows.append({'entry_time': idx[0], 'exit_time': idx[-1] + pd.Timedelta(hours=1),
                     'hours': len(idx), 'reason': 'signal', 'pnl': float((1 + r.loc[idx]).prod() - 1)})
    return pd.DataFrame(rows, columns=['entry_time', 'exit_time', 'hours', 'reason', 'pnl'])


def run_strategies(df):
    """{nom: (rendements nets 1h, trades)} pour A, B, C et buy & hold."""
    entries, stop_pct, target_pct = flag_setup(df)
    pos_b, ens = trend_positions(df)
    r_b = position_returns(df, pos_b)
    # L'ensemble applicable a la bougie ouverte a D est indexe par D : meme index que les entrees.
    ens_at_decision = ens.reindex(entries.index)
    out = {
        'A - Breakout mat-fanion 1h': simulate_trades(df, entries, stop_pct, target_pct),
        'B - Trend ensemble + ciblage vol': (r_b, position_trades(df, pos_b, r_b)),
        'C - Mat-fanion filtre par la tendance': simulate_trades(
            df, entries & (ens_at_decision >= 0.5), stop_pct, target_pct),
    }
    for k, fn in NEW_STRATEGIES.items():
        out[NAMES[k]] = fn(df)
    bh = pd.Series(1.0, index=df.index)
    r_bh = position_returns(df, bh)
    out['Reference - Buy & hold'] = (r_bh, position_trades(df, bh, r_bh))
    return out


# --- Deuxieme serie d'idees, fixees a priori le 2026-10-02 avant tout backtest ---------------------
# D - Retour a la moyenne 1h en marche sans tendance : |tendance 60 j| < 10 %, cloture a plus de
#     2,5 ecarts-types sous sa moyenne 48h -> achat ; objectif = la moyenne, stop a 1,5 ecart-type
#     sous l'entree, sortie au plus tard apres 24h.
# E - Cassure de Donchian quotidienne (tortues) : cloture > plus haut des 20 jours precedents ->
#     entree ; cloture < plus bas des 10 jours precedents -> sortie. Exposition ciblee a 40 % de vol.
# F - RSI(2) quotidien en tendance haussiere (Connors) : RSI2 < 10 et cloture > moyenne 200 j ->
#     entree ; cloture > moyenne 5 j -> sortie. Exposition ciblee a 40 % de vol.

def rsi(close, n):
    """RSI de Wilder."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / down)).where(down > 0, 100.0)


def _daily(df):
    d = pd.DataFrame({'close': df['close'].resample('1D').last(), 'high': df['high'].resample('1D').max(),
                      'low': df['low'].resample('1D').min()}).dropna()
    d['vol'] = d['close'].pct_change().rolling(30).std() * math.sqrt(365)
    return d


def _state_machine(enter, exit_):
    """1 entre un signal d'entree et un signal de sortie, 0 sinon (decide a la cloture du jour)."""
    out, inside = np.zeros(len(enter)), False
    for i, (e, x) in enumerate(zip(enter.to_numpy(bool), exit_.to_numpy(bool))):
        if inside and x:
            inside = False
        elif not inside and e:
            inside = True
        out[i] = float(inside)
    return pd.Series(out, index=enter.index)


def _daily_to_hourly(df, pos_daily):
    """Position decidee a la cloture du jour d, appliquee aux bougies du jour d+1."""
    key = df.index.floor('D') - pd.Timedelta(days=1)
    return pd.Series(pos_daily.reindex(key).to_numpy(), index=df.index).fillna(0.0).clip(0, 1)


def _daily_strategy(df, enter, exit_, daily):
    raw = _state_machine(enter, exit_)
    pos_daily = apply_band(vol_target(raw, daily['vol'], target=TARGET_VOL, max_leverage=1.0), BAND)
    pos = _daily_to_hourly(df, pos_daily)
    r = position_returns(df, pos)
    return r, position_trades(df, pos, r)


def donchian(df):
    d = _daily(df)
    enter = d['close'] > d['high'].shift(1).rolling(20).max()
    exit_ = d['close'] < d['low'].shift(1).rolling(10).min()
    return _daily_strategy(df, enter, exit_, d)


def rsi2_uptrend(df):
    d = _daily(df)
    r2 = rsi(d['close'], 2)
    enter = (r2 < 10) & (d['close'] > d['close'].rolling(200).mean())
    exit_ = d['close'] > d['close'].rolling(5).mean()
    return _daily_strategy(df, enter, exit_, d)


def range_mean_reversion(df):
    c = df['close']
    mean, std = c.rolling(48).mean(), c.rolling(48).std()
    z = (c - mean) / std
    daily = df['close'].resample('1D').last().dropna()
    trend60 = (daily / daily.shift(60) - 1)
    trend_h = pd.Series(trend60.reindex(df.index.floor('D') - pd.Timedelta(days=1)).to_numpy(), index=df.index)
    shift = pd.Timedelta(hours=1)
    entries = ((z < -2.5) & (trend_h.abs() < 0.10)).set_axis(df.index + shift)
    stop_pct = (1.5 * std / c).set_axis(df.index + shift)
    target_pct = ((mean - c) / c).set_axis(df.index + shift)
    return simulate_trades(df, entries, stop_pct, target_pct, max_hours=24)


NEW_STRATEGIES = {'D': range_mean_reversion, 'E': donchian, 'F': rsi2_uptrend}
NAMES = {'D': 'D - Retour a la moyenne 1h en range', 'E': 'E - Cassure Donchian 20/10 j',
         'F': 'F - RSI2 quotidien en tendance haussiere'}
