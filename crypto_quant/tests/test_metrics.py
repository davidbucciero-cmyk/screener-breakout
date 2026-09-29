"""Tests des metriques de performance (etape 5), sur des courbes d'equity
construites a la main pour connaitre le resultat exact attendu.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd

from crypto_quant.metrics import (
    average_turnover,
    cagr,
    calmar_ratio,
    hit_rate,
    max_drawdown,
    permutation_test_sharpe,
    returns_from_equity,
    sharpe_ratio,
    sharpe_significance,
    sortino_ratio,
    summarize_performance,
)


def test_cagr_doubles_in_one_year():
    n = 365
    equity = pd.Series(np.linspace(100, 200, n + 1))
    result = cagr(equity, periods_per_year=n)
    assert abs(result - 1.0) < 1e-6, f"Doubler en 1 an = CAGR de 100%, obtenu {result:.4f}"


def test_cagr_nan_on_zero_length():
    equity = pd.Series([100.0])
    assert np.isnan(cagr(equity, periods_per_year=365))


def test_max_drawdown_detects_worst_dip():
    equity = pd.Series([100, 110, 90, 95, 120, 80])
    # Pic a 110 (indice 1), creux a 90 (indice 2) -> dd = (90-110)/110 = -18.18%
    # Pic a 120 (indice 4), creux a 80 (indice 5) -> dd = (80-120)/120 = -33.33% (pire)
    result = max_drawdown(equity)
    assert abs(result - (-1 / 3)) < 1e-6, f"Attendu -33.3%, obtenu {result:.4f}"


def test_sharpe_ratio_nan_on_constant_returns():
    returns = pd.Series([0.01] * 50)  # ecart-type nul
    result = sharpe_ratio(returns, periods_per_year=365)
    assert np.isnan(result), "Ecart-type nul doit donner NaN, pas une division par zero silencieuse"


def test_sharpe_ratio_positive_for_positive_mean_returns():
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(loc=0.001, scale=0.01, size=1000))
    result = sharpe_ratio(returns, periods_per_year=365)
    assert result > 0


def test_sortino_only_penalizes_downside():
    # Deux series avec le meme ecart-type total mais une volatilite a la
    # hausse tres differente : le Sortino ne doit pas changer avec la vol
    # a la hausse, seulement avec la vol a la baisse.
    low_upside_vol = pd.Series([0.01, -0.02, 0.01, -0.02, 0.01, -0.02] * 20)
    high_upside_vol = pd.Series([0.05, -0.02, 0.05, -0.02, 0.05, -0.02] * 20)

    sortino_low = sortino_ratio(low_upside_vol, periods_per_year=365)
    sortino_high = sortino_ratio(high_upside_vol, periods_per_year=365)

    # La vol a la baisse est identique (-0.02) dans les deux cas ; seule la
    # moyenne (excess return) change -> Sortino doit augmenter avec la
    # hausse de la moyenne, pas etre penalise par la plus grande vol totale.
    assert sortino_high > sortino_low


def test_calmar_ratio_nan_on_zero_drawdown():
    assert np.isnan(calmar_ratio(cagr_value=0.10, max_dd=0.0))


def test_calmar_ratio_basic():
    result = calmar_ratio(cagr_value=0.20, max_dd=-0.10)
    assert abs(result - 2.0) < 1e-9


def test_hit_rate_counts_positive_periods():
    returns = pd.Series([0.01, -0.01, 0.02, 0.0, -0.005])
    result = hit_rate(returns)
    assert abs(result - 2 / 5) < 1e-9


def test_average_turnover_sums_absolute_weight_changes():
    weights = pd.DataFrame(
        {
            "BTC": [0.5, 0.5, 0.0],
            "ETH": [0.5, 0.0, 1.0],
        }
    )
    # t0->t1: |0.5-0.5| + |0.5-0.0| = 0.5
    # t1->t2: |0.0-0.5| + |1.0-0.0| = 1.5
    result = average_turnover(weights)
    assert abs(result - (0.5 + 1.5) / 2) < 1e-9


def test_summarize_performance_returns_all_expected_keys():
    equity = pd.Series(np.linspace(100, 150, 200) + np.random.default_rng(1).normal(0, 0.5, 200))
    summary = summarize_performance(equity, periods_per_year=8760)
    for key in ["cagr", "sharpe", "sharpe_p_value", "sortino", "max_drawdown", "calmar", "hit_rate", "n_periods"]:
        assert key in summary


def test_sharpe_significance_rejects_null_on_strong_signal():
    # Moyenne nettement positive, faible bruit, gros echantillon -> doit
    # rejeter tres largement l'hypothese nulle "rendement moyen = 0".
    rng = np.random.default_rng(0)
    returns = pd.Series(rng.normal(loc=0.01, scale=0.01, size=500))
    result = sharpe_significance(returns)
    assert result["n"] == 500
    assert result["p_value"] < 0.001


def test_sharpe_significance_does_not_reject_null_on_pure_noise():
    rng = np.random.default_rng(0)
    noise = pd.Series(rng.normal(loc=0.0, scale=0.01, size=500))
    result = sharpe_significance(noise)
    assert result["p_value"] > 0.05, "Du bruit pur ne doit pas etre declare significatif"


def test_sharpe_significance_nan_on_constant_returns():
    result = sharpe_significance(pd.Series([0.01] * 50))
    assert np.isnan(result["t_stat"])
    assert np.isnan(result["p_value"])


def test_permutation_test_sharpe_rejects_null_when_timing_is_perfect():
    # Strategie "oracle" : le poids applique a t (weights_history[t-1], via
    # le shift(1) interne) vaut 1 exactement quand le rendement de l'actif
    # a t est positif. Un timing aussi parfait ne doit presque jamais etre
    # egale par un ordre aleatoire des memes poids -> p_value proche de 0.
    rng = np.random.default_rng(42)
    n = 100
    asset_returns = pd.DataFrame({"BTC": rng.normal(0, 0.02, n)})

    oracle_weights = np.zeros(n)
    oracle_weights[:-1] = (asset_returns["BTC"].values[1:] > 0).astype(float)
    weights_history = pd.DataFrame({"BTC": oracle_weights})

    result = permutation_test_sharpe(weights_history, asset_returns, n_simulations=500, seed=1)
    assert result["p_value"] < 0.01


def test_permutation_test_sharpe_does_not_reject_null_when_timing_is_uninformed():
    # Motif de poids fixe, independant des rendements (bruit pur) -> le
    # timing reel ne doit pas se distinguer d'un ordre aleatoire.
    rng = np.random.default_rng(42)
    n = 100
    asset_returns = pd.DataFrame({"BTC": rng.normal(0, 0.02, n)})
    weights_history = pd.DataFrame({"BTC": np.tile([1.0, 0.0], n // 2)})

    result = permutation_test_sharpe(weights_history, asset_returns, n_simulations=500, seed=1)
    assert result["p_value"] > 0.1


def test_permutation_test_sharpe_uses_only_common_columns():
    n = 50
    asset_returns = pd.DataFrame({"BTC": np.full(n, 0.01), "ETH": np.full(n, -0.01)})
    weights_history = pd.DataFrame({"BTC": np.full(n, 1.0), "SOL": np.full(n, 1.0)})  # SOL absent des rendements

    result = permutation_test_sharpe(weights_history, asset_returns, n_simulations=50, seed=1)
    assert np.isfinite(result["observed_sharpe"])  # ne plante pas, ignore juste SOL


def test_permutation_test_sharpe_nan_when_no_common_columns():
    asset_returns = pd.DataFrame({"BTC": [0.01, 0.02]})
    weights_history = pd.DataFrame({"ETH": [1.0, 1.0]})
    result = permutation_test_sharpe(weights_history, asset_returns, n_simulations=10, seed=1)
    assert np.isnan(result["observed_sharpe"])
    assert np.isnan(result["p_value"])
    assert result["n_simulations"] == 0


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK: {t.__name__}")
    print(f"\nTous les tests metrics.py passent ({len(tests)} tests).")
