"""Backtest et gate d'acceptation. Le gate est du code : aucun modele ne note sa propre strategie."""
import math

import numpy as np
import pandas as pd

GATE = {'sharpe': 1.5, 'max_drawdown': -0.15, 'hit_rate': 0.55, 't_stat': 2.0}


def metrics(r, trades):
    """r : rendements nets 1h ; trades : DataFrame avec une colonne pnl."""
    daily = (1 + r).groupby(r.index.floor('D')).prod() - 1
    n = len(daily)
    std = daily.std()
    eq = (1 + r).cumprod()
    years = n / 365
    total = float(eq.iloc[-1] - 1) if len(eq) else float('nan')
    return {
        'jours': n,
        'rendement_total': total,
        'rendement_annuel': float((1 + total) ** (1 / years) - 1) if years > 0 and total > -1 else float('nan'),
        'sharpe': float(daily.mean() / std * math.sqrt(365)) if std > 0 else float('nan'),
        't_stat': float(daily.mean() / (std / math.sqrt(n))) if std > 0 else float('nan'),
        'max_drawdown': float((eq / eq.cummax() - 1).min()) if len(eq) else float('nan'),
        'hit_rate': float((trades['pnl'] > 0).mean()) if len(trades) else float('nan'),
        'nb_trades': int(len(trades)),
        'expo_moyenne_pct_heures': float((r != 0).mean()),
    }


def gate(m):
    checks = {
        'sharpe': m['sharpe'] > GATE['sharpe'],
        'max_drawdown': m['max_drawdown'] > GATE['max_drawdown'],
        'hit_rate': m['hit_rate'] > GATE['hit_rate'],
        't_stat': m['t_stat'] > GATE['t_stat'],
    }
    checks = {k: bool(v) for k, v in checks.items()}  # NaN -> False
    checks['passed'] = all(checks.values())
    return checks


def regimes(r, close_1h):
    """Perf par regime journalier, labels calcules uniquement avec le passe."""
    daily_close = close_1h.resample('1D').last().dropna()
    trend = daily_close / daily_close.shift(60) - 1
    vol = daily_close.pct_change().rolling(30).std()
    vol_med = vol.expanding(180).median()
    label_t = np.where(trend > 0.10, 'haussier', np.where(trend < -0.10, 'baissier', 'range'))
    label_v = np.where(vol > vol_med, 'vol haute', 'vol basse')
    labels = pd.Series([f'{a} / {b}' for a, b in zip(label_t, label_v)], index=daily_close.index)
    # Le regime du jour d est connu a la cloture de d-1.
    labels = labels.shift(1)
    daily = (1 + r).groupby(r.index.floor('D')).prod() - 1
    df = pd.DataFrame({'ret': daily, 'regime': labels.reindex(daily.index)}).dropna()
    rows = []
    for reg, g in df.groupby('regime'):
        s = g['ret'].std()
        rows.append({'regime': reg, 'jours': len(g),
                     'rendement_annualise': float((1 + g['ret']).prod() ** (365 / len(g)) - 1),
                     'sharpe': float(g['ret'].mean() / s * math.sqrt(365)) if s > 0 else float('nan')})
    return pd.DataFrame(rows)


def split(r, trades, start, end=None):
    end = end or r.index[-1] + pd.Timedelta(hours=1)
    rr = r[(r.index >= start) & (r.index < end)]
    tt = trades[(trades['entry_time'] >= start) & (trades['entry_time'] < end)] if len(trades) else trades
    return rr, tt
