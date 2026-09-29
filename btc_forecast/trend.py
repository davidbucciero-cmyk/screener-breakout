"""Trend following BTC quotidien + ciblage de volatilite.

Signal : momentum temporel (Moskowitz, Ooi, Pedersen 2012) sur plusieurs horizons standards de la
litterature (20, 60, 120, 250 jours), non optimises sur BTC. Chaque horizon vote long (1) ou flat (0),
l'ensemble fait la moyenne -> position de 0 a 1.
Ciblage de vol (Moreira & Muir 2017) : position x vol_cible / vol_prevue, plafonnee a max_leverage.
Vol prevue : EnKF (bougies journalieres) ou vol realisee 30 j, pour mesurer l'apport de l'EnKF.
Tout est decide a la cloture du jour t et tenu de t a t+1.
"""
import math

import numpy as np
import pandas as pd

from btc_forecast.backtest import strategy_returns
from btc_forecast.enkf import EnKFConfig, run_enkf

DAYS_PER_YEAR = 365
LOOKBACKS = (20, 60, 120, 250)


def trend_signals(close, lookbacks=LOOKBACKS):
    """Vote long/flat par horizon + moyenne. Valeurs connues a la cloture de t."""
    sig = pd.DataFrame({f'{lb}j': (close / close.shift(lb) - 1 > 0).astype(float).where(close.shift(lb).notna())
                        for lb in lookbacks})
    sig['ensemble'] = sig.mean(axis=1, skipna=False)
    return sig


def vol_forecasts(df, calib_days=90, members=100):
    """Vol annualisee prevue pour le jour t+1, connue a la cloture de t."""
    r = df['close'].pct_change()
    enkf = run_enkf(df, EnKFConfig(n_members=members, calib_hours=calib_days), keep_last=True)
    return pd.DataFrame({
        'enkf': np.sqrt(enkf['var_forecast'] * DAYS_PER_YEAR),
        'realisee_30j': r.rolling(30).std() * math.sqrt(DAYS_PER_YEAR),
    }).reindex(df.index), enkf


def vol_target(signal, vol, target=0.40, max_leverage=1.0):
    return (signal * target / vol).clip(-max_leverage, max_leverage)


def apply_band(position, band=0.10):
    """Ne re-balance que si l'ecart depasse `band` (limite les frais). Sortie a 0 toujours executee."""
    out = np.empty(len(position))
    prev = 0.0
    for i, p in enumerate(position.to_numpy()):
        if np.isnan(p):
            p = 0.0
        if p == 0.0 or abs(p - prev) > band:
            prev = p
        out[i] = prev
    return pd.Series(out, index=position.index)


def return_stats(name, net):
    """Statistiques a partir des rendements journaliers nets."""
    eq = (1 + net).cumprod()
    years = len(net) / DAYS_PER_YEAR
    cagr = eq.iloc[-1] ** (1 / years) - 1
    mdd = float((eq / eq.cummax() - 1).min())
    return {
        'strategie': name,
        'rendement_annuel': float(cagr),
        'vol_annuelle': float(net.std() * math.sqrt(DAYS_PER_YEAR)),
        'sharpe': float(net.mean() / net.std() * math.sqrt(DAYS_PER_YEAR)) if net.std() > 0 else float('nan'),
        'max_drawdown': mdd,
        'calmar': float(cagr / abs(mdd)) if mdd < 0 else float('nan'),
    }


def perf_stats(name, position, ret, fee_bps):
    net = strategy_returns(position, ret, fee_bps)
    years = len(net) / DAYS_PER_YEAR
    stats = return_stats(name, net)
    stats['exposition_moyenne'] = float(position.abs().mean())
    stats['rotation_annuelle'] = float(position.diff().abs().fillna(position.abs()).sum() / years)
    return stats, net


def run_trend(df, target_vol=0.40, max_leverage=1.0, fee_bps=10.0, band=0.10, calib_days=90):
    close = df['close']
    ret = close.shift(-1) / close - 1  # rendement t -> t+1
    sig = trend_signals(close)
    vols, enkf = vol_forecasts(df, calib_days)

    # Fenetre commune : tous les signaux et vols disponibles, rendement suivant connu.
    ok = sig.notna().all(axis=1) & vols.notna().all(axis=1) & ret.notna()
    idx = ret.index[ok]
    ret, sig, vols = ret.loc[idx], sig.loc[idx], vols.loc[idx]
    one = pd.Series(1.0, index=idx)

    def vt(s, v):
        return apply_band(vol_target(s, vols[v], target_vol, max_leverage), band)

    strategies = {
        'Buy & hold': one,
        'Buy & hold + ciblage vol 30j': vt(one, 'realisee_30j'),
        'Buy & hold + ciblage vol EnKF': vt(one, 'enkf'),
        'Trend ensemble (sans ciblage)': sig['ensemble'],
        'Trend ensemble + ciblage vol 30j': vt(sig['ensemble'], 'realisee_30j'),
        'Trend ensemble + ciblage vol EnKF': vt(sig['ensemble'], 'enkf'),
    }
    for lb in LOOKBACKS:
        strategies[f'Trend {lb}j seul (sans ciblage)'] = sig[f'{lb}j']

    rows, curves = [], {}
    for name, pos in strategies.items():
        stats, net = perf_stats(name, pos, ret, fee_bps)
        rows.append(stats)
        curves[name] = net
    curves = pd.DataFrame(curves)
    yearly = (1 + curves).groupby(curves.index.year).prod() - 1
    yearly.index.name = 'annee'
    positions = pd.DataFrame(strategies)
    return pd.DataFrame(rows), curves, yearly, enkf.loc[enkf.index.isin(idx)], vols, positions


PORTFOLIO_STRATEGIES = ['Buy & hold', 'Trend ensemble (sans ciblage)', 'Trend ensemble + ciblage vol 30j']


def run_portfolio(dfs, **kwargs):
    """Portefeuille a poches egales, sans re-equilibrage entre poches (comme le compte demo) :
    chaque crypto recoit 1/N du capital au depart et suit sa propre strategie.

    dfs : {symbole: DataFrame OHLC journalier}. Fenetre commune a toutes les cryptos.
    """
    per_asset = {s: run_trend(df, **kwargs) for s, df in dfs.items()}
    idx = None
    for res in per_asset.values():
        idx = res[1].index if idx is None else idx.intersection(res[1].index)

    rows, curves, sleeves = [], {}, {}
    for strat in PORTFOLIO_STRATEGIES:
        equities = pd.DataFrame({s: (1 + res[1].loc[idx, strat]).cumprod() for s, res in per_asset.items()})
        port_eq = equities.mean(axis=1)
        net = port_eq.pct_change().fillna(port_eq.iloc[0] - 1)
        name = f'Portefeuille {strat}'
        stats = return_stats(name, net)
        # Exposition du portefeuille = moyenne des expositions ponderee par la valeur des poches.
        pos = pd.DataFrame({s: res[5].loc[idx, strat] for s, res in per_asset.items()})
        stats['exposition_moyenne'] = float((pos * equities).sum(axis=1).div(equities.sum(axis=1)).mean())
        rows.append(stats)
        curves[name] = net
        sleeves[strat] = pd.DataFrame({s: res[1].loc[idx, strat] for s, res in per_asset.items()})
    # Chaque crypto seule sur la meme fenetre, pour comparaison.
    for s, res in per_asset.items():
        strat = 'Trend ensemble + ciblage vol 30j'
        stats = return_stats(f'{s} seul - {strat}', res[1].loc[idx, strat])
        stats['exposition_moyenne'] = float(res[5].loc[idx, strat].mean())
        rows.append(stats)
        curves[f'{s} seul - {strat}'] = res[1].loc[idx, strat]

    curves = pd.DataFrame(curves)
    yearly = (1 + curves).groupby(curves.index.year).prod() - 1
    yearly.index.name = 'annee'
    corr = {strat: df.corr() for strat, df in sleeves.items()}
    return pd.DataFrame(rows), curves, yearly, corr
