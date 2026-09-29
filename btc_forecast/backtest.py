import logging
import math

import numpy as np
import pandas as pd

from btc_forecast.model import prob_up

log = logging.getLogger(__name__)


def walk_forward(close, forecaster, n_test=2000, context_len=512, batch_size=64):
    """Pour chaque heure t des n_test dernieres, prevoit close[t+1] avec uniquement close[..t].

    Retourne un DataFrame indexe par t : close, next_close, ret (rendement t -> t+1), p_up, q10..q90.
    """
    close = close.astype(float)
    values = close.to_numpy()
    last_t = len(values) - 2  # derniere heure dont on connait la suivante
    first_t = max(context_len - 1, last_t - n_test + 1)
    ts = np.arange(first_t, last_t + 1)
    log.info(f'Walk-forward : {len(ts)} previsions, contexte {context_len}h')

    quantiles = []
    for i in range(0, len(ts), batch_size):
        chunk = ts[i:i + batch_size]
        contexts = [values[t - context_len + 1:t + 1] for t in chunk]
        quantiles.append(forecaster.predict_quantiles(contexts))
        if (i // batch_size) % 10 == 0:
            log.info(f'  {min(i + batch_size, len(ts))}/{len(ts)}')
    quantiles = np.vstack(quantiles)

    out = pd.DataFrame(index=close.index[ts])
    out['close'] = values[ts]
    out['next_close'] = values[ts + 1]
    out['ret'] = out['next_close'] / out['close'] - 1
    # Rendement de la bougie qui vient de cloturer (pour les baselines momentum / mean-reversion).
    out['prev_ret'] = values[ts] / values[ts - 1] - 1
    for j, q in enumerate(quantiles.T):
        out[f'q{j + 1}0'] = q
    out['p_up'] = [prob_up(c, q) for c, q in zip(out['close'], quantiles)]
    return out


def _binom_pvalue(hits, n):
    """p-value bilaterale (approx. normale) de H0 : taux de reussite = 50 %."""
    if n == 0:
        return float('nan')
    z = (hits - n / 2) / math.sqrt(n / 4)
    return math.erfc(abs(z) / math.sqrt(2))


def strategy_returns(position, ret, fee_bps):
    """position : +1 long, -1 short, 0 flat, tenue de t a t+1. Frais par cote sur chaque changement."""
    position = pd.Series(position, index=ret.index, dtype=float)
    turnover = position.diff().abs().fillna(position.abs())
    return position * ret - turnover * fee_bps / 1e4


def _perf(name, position, ret, fee_bps):
    position = pd.Series(position, index=ret.index, dtype=float)
    net = strategy_returns(position, ret, fee_bps)
    gross = strategy_returns(position, ret, 0)
    active = position != 0
    n_active = int(active.sum())
    hits = int(((np.sign(ret) == np.sign(position)) & active).sum())
    hours_per_year = 24 * 365
    std = net.std()
    return {
        'strategie': name,
        'heures_en_position': n_active,
        'taux_reussite': hits / n_active if n_active else float('nan'),
        'p_value_vs_50pct': _binom_pvalue(hits, n_active),
        'rendement_brut': float((1 + gross).prod() - 1),
        'rendement_net': float((1 + net).prod() - 1),
        'sharpe_net_annualise': float(net.mean() / std * math.sqrt(hours_per_year)) if std > 0 else float('nan'),
        'max_drawdown_net': float(((1 + net).cumprod() / (1 + net).cumprod().cummax() - 1).min()),
        'nb_trades': int((position.diff().fillna(position) != 0).sum()),
    }, net


def evaluate(preds, fee_bps=5.0, thresholds=(0.0, 0.02, 0.05, 0.10), seed=0, label='Chronos', extra_positions=None):
    """Metriques de calibration + performance des strategies vs baselines naives."""
    ret, p = preds['ret'], preds['p_up']
    up = (ret > 0).astype(float)
    base_rate = float(up.mean())

    calib = {
        'n_previsions': len(preds),
        'freq_hausse_reelle': base_rate,
        'p_up_moyenne': float(p.mean()),
        'brier_modele': float(((p - up) ** 2).mean()),
        'brier_pile_ou_face': 0.25,
        'brier_freq_constante': float(((base_rate - up) ** 2).mean()),
        'correlation_p_up_rendement': float(np.corrcoef(p, ret)[0, 1]),
    }

    rows, curves = [], {}
    for th in thresholds:
        pos = np.where(p > 0.5 + th, 1, np.where(p < 0.5 - th, -1, 0))
        name = f'{label} long/short (seuil {0.5 + th:.1%}/{0.5 - th:.1%})'
        perf, net = _perf(name, pos, ret, fee_bps)
        rows.append(perf)
        curves[name] = net
    for name, pos in (extra_positions or {}).items():
        perf, net = _perf(name, pos, ret, fee_bps)
        rows.append(perf)
        curves[name] = net
    rng = np.random.default_rng(seed)
    baselines = {
        'Buy & hold': np.ones(len(ret)),
        'Momentum (meme sens que la bougie precedente)': np.sign(preds['prev_ret']).to_numpy(),
        'Mean-reversion (sens inverse)': -np.sign(preds['prev_ret']).to_numpy(),
        'Aleatoire': rng.choice([-1, 1], size=len(ret)),
    }
    for name, pos in baselines.items():
        perf, net = _perf(name, pos, ret, fee_bps)
        rows.append(perf)
        curves[name] = net

    # Calibration par tranche de P(hausse) : le modele dit 60 %, est-ce que ca monte 60 % du temps ?
    bins = pd.cut(p, [0, 0.4, 0.45, 0.5, 0.55, 0.6, 1.0])
    reliability = preds.assign(up=up).groupby(bins, observed=True).agg(
        n=('up', 'size'), p_up_moyenne=('p_up', 'mean'), freq_hausse=('up', 'mean'))

    return calib, pd.DataFrame(rows), reliability, pd.DataFrame(curves)


def evaluate_volatility(preds, r2_hist):
    """Qualite de la prevision de variance t+1 (QLIKE, plus bas = mieux) vs variance realisee glissante.

    r2_hist : Series des rendements au carre sur tout l'historique (meme index que les bougies).
    """
    r2_next = preds['ret'] ** 2
    candidates = {'Modele': preds['var_forecast']}
    for hours in (24, 720):
        candidates[f'Variance realisee {hours}h'] = r2_hist.rolling(hours).mean().reindex(preds.index)
    rows = []
    for name, var in candidates.items():
        ok = var.notna() & (var > 0)
        v, y = var[ok], r2_next[ok]
        rows.append({
            'prevision_variance': name,
            'qlike': float((np.log(v) + y / v).mean()),
            'correlation_vol_prevue_vs_abs_rendement': float(np.corrcoef(np.sqrt(v), np.sqrt(y))[0, 1]),
        })
    return pd.DataFrame(rows)
