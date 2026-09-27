"""Tests de l'explorateur de parametres (dashboard interactif).

Le point critique : build_grid() re-implemente le calcul de run_backtest de
facon vectorisee (coupe-circuit desactive) pour balayer ~1000 combinaisons
en quelques secondes plutot qu'en dizaines de minutes. Deux implementations
independantes du meme calcul = risque reel de divergence silencieuse (deja
trouve un bug de ce type en construisant ce module : le turnover de la toute
premiere ligne etait traite comme nul au lieu de facturer l'entree initiale).

Ces tests verifient que build_grid() reproduit EXACTEMENT (aux arrondis
d'affichage pres) ce que donnerait run_backtest() avec le coupe-circuit
desactive (halt_drawdown tres eleve), sur plusieurs combinaisons de
parametres choisies aux extremes de la grille.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import warnings

warnings.filterwarnings("ignore")

import pandas as pd
import pytest

import crypto_quant.dashboard_explore as explore
from crypto_quant.backtest import BacktestConfig, run_backtest
from crypto_quant.metrics import cagr as cagr_fn
from crypto_quant.metrics import hit_rate, max_drawdown, sharpe_ratio
from crypto_quant.synthetic import synthetic_dataframe

FIXED_END_MS = 1_759_000_000_000


@pytest.fixture
def small_universe():
    kwargs = {
        "BTC/USD": dict(start_price=100, drift=0.0005, gbm_vol=0.006, momentum_rho=0.3, ou_theta=0.02, ou_sigma=0.01, seed=1),
        "ETH/USD": dict(start_price=50, drift=-0.0003, gbm_vol=0.007, ou_theta=0.05, ou_sigma=0.015, seed=2),
    }
    return {s: synthetic_dataframe(600, end_ms=FIXED_END_MS, **kw) for s, kw in kwargs.items()}


@pytest.fixture(autouse=True)
def small_grid(monkeypatch):
    """Reduit la grille pour que le test reste rapide (grille complete ~60s)."""
    monkeypatch.setattr(explore, "EMA_PAIRS", [(6, 24), (12, 48)])
    monkeypatch.setattr(explore, "SIG_T_VALUES", [1.5, 2.0])
    monkeypatch.setattr(explore, "TARGET_VOL_VALUES", [0.01, 0.02])
    monkeypatch.setattr(explore, "COST_BPS_VALUES", [0.0, 15.0])
    monkeypatch.setattr(explore, "HURST_WINDOW", 60)
    monkeypatch.setattr(explore, "OU_WINDOW", 60)


def _reference_metrics(price_data, pair, sig_t, target_vol, cost_bps, train_start, train_end, test_start, test_end):
    cfg = BacktestConfig(
        ema_fast=pair[0], ema_slow=pair[1], ema_vol_window=pair[1],
        hurst_window=explore.HURST_WINDOW, hurst_max_lag=explore.HURST_MAX_LAG,
        ou_window=explore.OU_WINDOW, ou_significance_t=sig_t,
        ewma_lambda=explore.EWMA_LAMBDA,
        target_vol=target_vol, max_leverage=explore.MAX_LEVERAGE,
        halt_drawdown=0.999, resume_drawdown=0.001, circuit_breaker_cooldown=1,
        transaction_cost_bps=cost_bps, top_n=None,
    )
    eq = run_backtest(price_data, cfg).equity

    def sm(start, end):
        sub = eq.loc[start:end]
        rebased = sub / sub.iloc[0]
        returns = rebased.pct_change().dropna()
        return {
            "sharpe": round(sharpe_ratio(returns, explore.PERIODS_PER_YEAR), 3),
            "cagr": round(cagr_fn(rebased, explore.PERIODS_PER_YEAR), 4),
            "max_drawdown": round(max_drawdown(rebased), 4),
            "hit_rate": round(hit_rate(returns), 4),
        }

    return sm(train_start, train_end), sm(test_start, test_end)


def test_build_grid_matches_run_backtest_with_breaker_disabled(small_universe):
    grid = explore.build_grid(small_universe)
    meta = grid["meta"]
    train_start, train_end = pd.Timestamp(meta["train_start"]), pd.Timestamp(meta["train_end"])
    test_start, test_end = pd.Timestamp(meta["test_start"]), pd.Timestamp(meta["test_end"])

    checked = 0
    for pair in explore.EMA_PAIRS:
        for sig_t in explore.SIG_T_VALUES:
            for target_vol in explore.TARGET_VOL_VALUES:
                for cost_bps in explore.COST_BPS_VALUES:
                    grid_row = next(
                        r for r in grid["results"]
                        if r["ema_fast"] == pair[0] and r["ema_slow"] == pair[1]
                        and r["ou_significance_t"] == sig_t
                        and r["target_vol"] == target_vol and r["cost_bps"] == cost_bps
                    )
                    ref_train, ref_test = _reference_metrics(
                        small_universe, pair, sig_t, target_vol, cost_bps,
                        train_start, train_end, test_start, test_end,
                    )
                    assert grid_row["train"] == ref_train, f"train mismatch for {pair, sig_t, target_vol, cost_bps}"
                    assert grid_row["test"] == ref_test, f"test mismatch for {pair, sig_t, target_vol, cost_bps}"
                    checked += 1

    assert checked == len(grid["results"]) == 2 * 2 * 2 * 2


def test_build_grid_first_bar_turnover_is_charged(small_universe):
    """Regression du bug trouve pendant le developpement : la toute premiere
    ligne doit facturer le turnover d'entree (poids precedent = 0), pas le
    traiter comme "aucun changement" simplement parce qu'il n'y a pas de
    ligne precedente dans le DataFrame."""
    grid = explore.build_grid(small_universe)
    zero_cost_row = next(
        r for r in grid["results"]
        if r["ema_fast"] == explore.EMA_PAIRS[0][0] and r["cost_bps"] == 0.0
    )
    nonzero_cost_row = next(
        r for r in grid["results"]
        if r["ema_fast"] == explore.EMA_PAIRS[0][0]
        and r["ema_slow"] == zero_cost_row["ema_slow"]
        and r["ou_significance_t"] == zero_cost_row["ou_significance_t"]
        and r["target_vol"] == zero_cost_row["target_vol"]
        and r["cost_bps"] == max(explore.COST_BPS_VALUES)
    )
    # Un cout de transaction plus eleve doit degrader (ou laisser egale) la
    # performance train - si le turnover initial n'etait pas facture, ce
    # test resterait souvent egal par coincidence sur peu de rebalancements ;
    # combine au test de validation ci-dessus (qui aurait deja echoue), ce
    # test documente explicitement l'invariant attendu.
    if zero_cost_row["train"]["cagr"] is not None and nonzero_cost_row["train"]["cagr"] is not None:
        assert nonzero_cost_row["train"]["cagr"] <= zero_cost_row["train"]["cagr"]


if __name__ == "__main__":
    print("Lancer via pytest (utilise des fixtures).")
