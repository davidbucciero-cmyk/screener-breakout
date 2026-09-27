"""Explorateur de parametres pour le dashboard interactif.

Calcule une grille de resultats (Sharpe/CAGR/max drawdown/hit rate, en train
ET en hors-echantillon) sur une combinatoire de couples EMA, seuil de
significativite OU, vol cible et cout de transaction - pour que le
dashboard puisse afficher un resultat instantane quand l'utilisateur bouge
un curseur, sans recalcul serveur.

Simplification assumee et affichee dans le dashboard : le coupe-circuit de
drawdown est DESACTIVE ici (contrairement a run_backtest standard). Avec le
coupe-circuit actif, chaque combinaison de (target_vol, cost_bps) aurait un
chemin d'equity different, donc potentiellement des haltes a des moments
differents - une dependance sequentielle qui empecherait de vectoriser le
balayage de grille. Sans coupe-circuit, poids et volatilite de portefeuille
ne dependent que de (ema_pair, ou_significance_t) ; target_vol et cost_bps
n'affectent plus que des operations vectorisables (levier, cout), donc toute
la grille se calcule en quelques secondes plutot qu'en dizaines de minutes.
Le dashboard statique (run_backtest complet) reste la version de reference
avec coupe-circuit.

Le vrai objectif, sanctionne dans les valeurs par defaut du dashboard : ne
JAMAIS choisir des parametres sur la seule base du Sharpe "train" (c'est
l'essence meme du surapprentissage) - toujours regarder le chiffre
hors-echantillon, calcule sur une portion de donnees jamais utilisee pour
choisir quoi que ce soit.
"""
import json
import os
import warnings
from typing import Dict, List, Tuple

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from .metrics import cagr as cagr_fn
from .metrics import hit_rate, max_drawdown, sharpe_ratio
from .portfolio import composite_score, target_weights_row
from .risk import inverse_vol_weights
from .signals import ema_trend_signal, ewma_volatility, ou_meanreversion_signal, rolling_hurst
from .synthetic import synthetic_dataframe

EMA_PAIRS: List[Tuple[int, int]] = [(6, 24), (8, 32), (10, 40), (12, 48), (16, 64), (20, 80), (24, 96), (32, 128)]
SIG_T_VALUES: List[float] = [1.0, 1.5, 2.0, 3.0]
TARGET_VOL_VALUES: List[float] = [0.005, 0.0075, 0.01, 0.015, 0.02, 0.03]
COST_BPS_VALUES: List[float] = [0.0, 5.0, 10.0, 15.0, 25.0, 50.0]

HURST_WINDOW = 100
HURST_MAX_LAG = 20
OU_WINDOW = 100
EWMA_LAMBDA = 0.94
MAX_LEVERAGE = 1.0
TRAIN_FRACTION = 0.65
PERIODS_PER_YEAR = 8760


def _demo_universe(n_periods: int = 2200, end_ms: int = 1_759_000_000_000) -> Dict[str, pd.DataFrame]:
    kwargs = {
        "BTC/USD": dict(start_price=62000, drift=0.0006, gbm_vol=0.006, momentum_rho=0.35, ou_theta=0.02, ou_sigma=0.01, seed=101),
        "ETH/USD": dict(start_price=3400, drift=-0.0003, gbm_vol=0.007, momentum_rho=0.3, ou_theta=0.015, ou_sigma=0.012, seed=102),
        "SOL/USD": dict(start_price=145, drift=0.0002, gbm_vol=0.009, ou_theta=0.06, ou_sigma=0.02, seed=103),
        "ADA/USD": dict(start_price=0.45, drift=0.0, gbm_vol=0.008, ou_theta=0.0, ou_sigma=0.0, seed=104),
        "XRP/USD": dict(start_price=0.55, drift=0.0004, gbm_vol=0.0065, momentum_rho=0.25, ou_theta=0.01, ou_sigma=0.008, seed=105),
    }
    return {s: synthetic_dataframe(n_periods, end_ms=end_ms, **kw) for s, kw in kwargs.items()}


def _slice_metrics(equity_full: pd.Series, start: int, end: int) -> dict:
    """Metriques d'une sous-tranche [start:end) de la courbe d'equity,
    rebasee a 1.0 au debut de la tranche (comparaison equitable train/test,
    independante du niveau d'equity accumule avant la tranche)."""
    sub = equity_full.iloc[start:end]
    if len(sub) < 2:
        return {"sharpe": None, "cagr": None, "max_drawdown": None, "hit_rate": None}
    rebased = sub / sub.iloc[0]
    returns = rebased.pct_change().dropna()
    s = sharpe_ratio(returns, PERIODS_PER_YEAR)
    c = cagr_fn(rebased, PERIODS_PER_YEAR)
    mdd = max_drawdown(rebased)
    hr = hit_rate(returns)
    return {
        "sharpe": None if pd.isna(s) else round(float(s), 3),
        "cagr": None if pd.isna(c) else round(float(c), 4),
        "max_drawdown": None if pd.isna(mdd) else round(float(mdd), 4),
        "hit_rate": None if pd.isna(hr) else round(float(hr), 4),
    }


def build_grid(price_data: Dict[str, pd.DataFrame]) -> dict:
    symbols = list(price_data.keys())

    # --- Precompute : ce qui ne depend PAS de la grille (une fois par actif) ---
    hurst = {s: rolling_hurst(price_data[s]["close"], window=HURST_WINDOW, max_lag=HURST_MAX_LAG) for s in symbols}
    vol = {s: ewma_volatility(price_data[s]["close"], lam=EWMA_LAMBDA) for s in symbols}
    close = {s: price_data[s]["close"] for s in symbols}

    # --- Precompute : EMA par paire (rapide, vectorise) ---
    ema_by_pair = {
        pair: {s: ema_trend_signal(close[s], fast=pair[0], slow=pair[1], vol_window=pair[1]) for s in symbols}
        for pair in EMA_PAIRS
    }

    # --- Precompute : OU par seuil de significativite (le plus couteux, O(n*window)) ---
    ou_by_sigt = {
        sig_t: {s: ou_meanreversion_signal(close[s], window=OU_WINDOW, significance_t=sig_t)["signal"] for s in symbols}
        for sig_t in SIG_T_VALUES
    }

    # --- Index commun : valide pour hurst/vol ET pour CHAQUE paire EMA (le
    # signal OU est volontairement exclu, cf. _align_universe standard) ---
    common_index = None
    for s in symbols:
        idx = hurst[s].dropna().index.intersection(vol[s].dropna().index)
        for pair in EMA_PAIRS:
            idx = idx.intersection(ema_by_pair[pair][s].dropna().index)
        common_index = idx if common_index is None else common_index.intersection(idx)
    common_index = common_index.sort_values()

    n = len(common_index)
    split = int(n * TRAIN_FRACTION)

    close_df = pd.DataFrame({s: close[s].loc[common_index] for s in symbols})
    # asset_returns.loc[t] = rendement realise de t vers t+1 (close[t+1]/close[t]-1),
    # range sur la ligne t : c'est le rendement que le poids DECIDE a la ligne
    # t va capter, exactement comme run_backtest (close_df.iloc[t+1]/iloc[t]-1).
    asset_returns = close_df.pct_change().shift(-1)
    vol_df = pd.DataFrame({s: vol[s].loc[common_index] for s in symbols})

    results = []

    for pair in EMA_PAIRS:
        for sig_t in SIG_T_VALUES:
            hurst_df = pd.DataFrame({s: hurst[s].loc[common_index] for s in symbols})
            ema_df = pd.DataFrame({s: ema_by_pair[pair][s].loc[common_index] for s in symbols})
            ou_df = pd.DataFrame({s: ou_by_sigt[sig_t][s].loc[common_index] for s in symbols})

            raw_scores = pd.DataFrame(
                {s: composite_score(hurst_df[s], ema_df[s], ou_df[s])["raw_score"] for s in symbols}
            )
            w_score = raw_scores.apply(lambda row: target_weights_row(row), axis=1)
            w_tilted = pd.DataFrame(
                [inverse_vol_weights(w_score.iloc[i], vol_df.iloc[i]) for i in range(n)],
                index=common_index,
                columns=symbols,
            )
            portfolio_vol = (w_tilted * vol_df).sum(axis=1)  # estimation conservatrice, cf. risk.py

            for target_vol in TARGET_VOL_VALUES:
                leverage = (target_vol / portfolio_vol).clip(upper=MAX_LEVERAGE).fillna(0.0)
                w_final = w_tilted.mul(leverage, axis=0)
                # Turnover et rendement brut a la ligne t (poids decide a t,
                # rendement t->t+1 deja aligne sur t dans asset_returns - PAS
                # de shift supplementaire ici, cf. commentaire ci-dessus).
                #
                # w_final.shift().fillna(0.0), PAS w_final.diff().fillna(0.0) :
                # a la toute premiere ligne il n'y a pas de position
                # precedente, donc le "poids precedent" est bien 0 (portefeuille
                # vide au demarrage, comme prev_weights dans run_backtest) - le
                # turnover d'entree initial est reel et doit etre facture, pas
                # traite comme s'il n'y avait aucun changement. diff().fillna(0)
                # faisait l'erreur inverse (turnover initial invisible),
                # detectee en validant ce calcul contre run_backtest().
                prev_w = w_final.shift().fillna(0.0)
                lev_turnover = (w_final - prev_w).abs().sum(axis=1)
                gross_return = (w_final * asset_returns).sum(axis=1)

                for cost_bps in COST_BPS_VALUES:
                    net_return = gross_return - lev_turnover * (cost_bps / 10_000.0)
                    # step_returns[t] = rendement realise en PASSANT de la
                    # ligne t-1 a la ligne t (donc step_returns[0]=0 : aucun
                    # rendement avant le premier point). Equivaut exactement a
                    # equity[t+1] = equity[t]*(1+portfolio_return[t]) de
                    # run_backtest, avec equity[0]=1.0 (rebase).
                    step_returns = net_return.shift(1).fillna(0.0)
                    equity = (1 + step_returns).cumprod()

                    train_metrics = _slice_metrics(equity, 0, split)
                    test_metrics = _slice_metrics(equity, split, n)

                    results.append(
                        {
                            "ema_fast": pair[0],
                            "ema_slow": pair[1],
                            "ou_significance_t": sig_t,
                            "target_vol": target_vol,
                            "cost_bps": cost_bps,
                            "train": train_metrics,
                            "test": test_metrics,
                        }
                    )

    return {
        "axes": {
            "ema_pairs": [{"fast": p[0], "slow": p[1], "label": f"{p[0]}/{p[1]}"} for p in EMA_PAIRS],
            "sig_t_values": SIG_T_VALUES,
            "target_vol_values": TARGET_VOL_VALUES,
            "cost_bps_values": COST_BPS_VALUES,
        },
        "meta": {
            "n_periods": n,
            "train_periods": split,
            "test_periods": n - split,
            "train_start": common_index[0].isoformat(),
            "train_end": common_index[split - 1].isoformat(),
            "test_start": common_index[split].isoformat(),
            "test_end": common_index[-1].isoformat(),
            "n_combinations": len(results),
            "circuit_breaker": "desactive dans cet explorateur (cf. docstring dashboard_explore.py)",
        },
        "results": results,
    }


def main():
    price_data = _demo_universe()
    grid = build_grid(price_data)

    out_dir = os.path.join(os.path.dirname(__file__), "dashboard")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "explore_grid.json")
    with open(out_path, "w") as f:
        json.dump(grid, f)

    print(f"Ecrit : {out_path}")
    print(f"Combinaisons : {grid['meta']['n_combinations']}")
    print(f"Train: {grid['meta']['train_start']} -> {grid['meta']['train_end']} ({grid['meta']['train_periods']} bougies)")
    print(f"Test:  {grid['meta']['test_start']} -> {grid['meta']['test_end']} ({grid['meta']['test_periods']} bougies)")


if __name__ == "__main__":
    main()
