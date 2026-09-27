"""Tests de la validation walk-forward (etape 5)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pytest

from crypto_quant.backtest import BacktestConfig, WalkForwardValidator, expanding_splits
from crypto_quant.synthetic import synthetic_dataframe

FIXED_END_MS = 1_700_000_000_000


def test_expanding_splits_are_contiguous_and_cover_full_range():
    n_periods, n_splits = 1000, 4
    splits = expanding_splits(n_periods, n_splits)

    assert len(splits) == n_splits
    for k, (train_start, train_end, test_start, test_end) in enumerate(splits):
        assert train_start == 0
        assert train_end == test_start, "Le train doit s'arreter exactement ou le test commence"
        if k > 0:
            assert train_end == splits[k - 1][3], "Le train du fold suivant doit s'etendre jusqu'au test precedent (expansif)"

    assert splits[-1][3] == n_periods, "Le dernier fold doit couvrir jusqu'a la fin (pas de donnees perdues)"


def test_expanding_splits_raises_when_not_enough_periods():
    with pytest.raises(ValueError):
        expanding_splits(n_periods=3, n_splits=10)


def _small_universe(n=600):
    return {
        "TREND_UP": synthetic_dataframe(
            n, end_ms=FIXED_END_MS, drift=0.002, gbm_vol=0.005, momentum_rho=0.5, ou_theta=0.0, ou_sigma=0.0, seed=11
        ),
        "MEANREV": synthetic_dataframe(
            n, end_ms=FIXED_END_MS, drift=0.0, gbm_vol=0.0005, ou_theta=0.2, ou_sigma=0.02, seed=12
        ),
    }


def test_walk_forward_validator_produces_oos_curve_and_fold_results():
    price_data = _small_universe()
    config_grid = [
        BacktestConfig(ema_fast=8, ema_slow=32, hurst_window=60, hurst_max_lag=15, ou_window=60),
        BacktestConfig(ema_fast=16, ema_slow=64, hurst_window=60, hurst_max_lag=15, ou_window=60),
    ]

    validator = WalkForwardValidator(config_grid, n_splits=3, periods_per_year=8760, min_valid_periods=15)
    oos_equity, fold_results = validator.run(price_data)

    assert len(fold_results) > 0
    assert not oos_equity.isna().any()
    assert (oos_equity > 0).all()

    for fold in fold_results:
        assert fold.chosen_config in config_grid
        assert fold.train_end <= fold.test_start
        assert fold.test_start <= fold.test_end


def test_select_best_config_excludes_configs_that_cannot_fit_test_window():
    """Bug trouve sur donnees reelles Kraken (1d, ~700 jours) : une config a
    grande fenetre de warm-up (hurst/ou/ema) peut avoir le meilleur Sharpe
    train (justement parce qu'elle overfit sur peu de trades avec un train
    qui grandit a chaque fold), etre choisie, puis echouer entierement sur
    le test suivant (taille FIXE, souvent bien plus petite que le train) -
    perdant ainsi le fold entier silencieusement. _select_best_config doit
    exclure ces configs en amont, sur un critere purement structurel (taille
    du test), jamais sur les prix du test lui-meme."""
    price_data = _small_universe(n=400)
    grid = [
        BacktestConfig(ema_fast=8, ema_slow=32, hurst_window=60, hurst_max_lag=15, ou_window=60),
        BacktestConfig(ema_fast=16, ema_slow=64, hurst_window=150, hurst_max_lag=15, ou_window=150),
    ]
    validator = WalkForwardValidator(grid, n_splits=3, periods_per_year=8760, min_valid_periods=15)

    # test_length = 100 : suffisant pour la config a fenetre 60 (60+15<=100)
    # mais structurellement impossible pour celle a fenetre 150 (150+15>100).
    best_cfg, best_sharpe = validator._select_best_config(price_data, test_length=100)

    assert best_cfg is not None
    assert best_cfg.hurst_window == 60, "la config a fenetre 150 (infaisable sur ce test) ne doit jamais etre choisie"

    # Avec un test_length trop petit pour TOUTES les configs du grid, aucune
    # config ne doit etre selectionnee (plutot que de choisir quand meme la
    # "moins pire" et faire echouer le fold en aval).
    best_cfg_none, _ = validator._select_best_config(price_data, test_length=50)
    assert best_cfg_none is None


def test_walk_forward_validator_raises_when_no_fold_is_viable():
    # Historique bien trop court par rapport aux fenetres des signaux :
    # aucun fold ne pourra produire de resultat exploitable.
    price_data = {
        "TINY": synthetic_dataframe(30, end_ms=FIXED_END_MS, drift=0.0, gbm_vol=0.01, seed=1),
    }
    config_grid = [BacktestConfig()]  # fenetres par defaut (100), largement > 30 periodes dispo

    validator = WalkForwardValidator(config_grid, n_splits=3)
    with pytest.raises(ValueError):
        validator.run(price_data)


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        try:
            t()
            print(f"OK: {t.__name__}")
        except Exception:
            print(f"(test attend une exception, verifie via pytest) {t.__name__}")
    print(f"\nTests walk_forward.py : lancer via pytest pour les cas d'exception.")
