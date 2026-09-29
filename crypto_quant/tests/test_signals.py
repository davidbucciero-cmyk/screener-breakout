"""Tests du socle de signaux (etape 2), sur donnees synthetiques controlees.

Chaque test construit une serie dont on connait le comportement par
construction (tendancielle, mean-reverting, ou bruit pur) et verifie que le
signal correspondant reagit dans le bon sens.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np

from crypto_quant.signals import (
    ema_trend_signal,
    estimate_dominant_half_life,
    ewma_volatility,
    hurst_exponent,
    ou_meanreversion_signal,
    rolling_hurst,
    suggest_meanreversion_window,
)
from crypto_quant.synthetic import synthetic_dataframe


def test_hurst_detects_trending_series():
    # Momentum positif (increments autocorreles) -> vraie persistance de
    # tendance -> H doit etre nettement > 0.5. Une simple derive constante ne
    # suffirait pas : une marche aleatoire avec derive reste une marche
    # aleatoire (H≈0.5), cf. test_hurst_near_half_on_pure_random_walk.
    df = synthetic_dataframe(800, drift=0.0, gbm_vol=0.005, momentum_rho=0.7, ou_theta=0.0, ou_sigma=0.0, seed=1)
    h = hurst_exponent(np.log(df["close"].values), min_lag=2, max_lag=20)
    assert h > 0.6, f"Hurst attendu > 0.6 sur serie a momentum, obtenu {h:.3f}"


def test_hurst_detects_mean_reverting_series():
    # Pas de derive, bruit GBM minimal, forte composante de rappel OU ->
    # serie mean-reverting -> H doit etre nettement < 0.5.
    df = synthetic_dataframe(400, drift=0.0, gbm_vol=0.0005, ou_theta=0.3, ou_sigma=0.02, seed=2)
    h = hurst_exponent(np.log(df["close"].values), min_lag=2, max_lag=20)
    assert h < 0.4, f"Hurst attendu < 0.4 sur serie mean-reverting, obtenu {h:.3f}"


def test_hurst_near_half_on_pure_random_walk():
    # Marche aleatoire pure (pas de derive, pas de composante OU) -> H proche
    # de 0.5 (tolerance large car l'estimateur reste bruite sur un seul tirage).
    df = synthetic_dataframe(600, drift=0.0, gbm_vol=0.01, ou_theta=0.0, ou_sigma=0.0, seed=3)
    h = hurst_exponent(np.log(df["close"].values), min_lag=2, max_lag=20)
    assert 0.3 < h < 0.7, f"Hurst attendu proche de 0.5 sur marche aleatoire, obtenu {h:.3f}"


def test_rolling_hurst_has_correct_shape_and_warmup_nans():
    df = synthetic_dataframe(300, drift=0.005, gbm_vol=0.005, seed=4)
    window = 100
    h_series = rolling_hurst(df["close"], window=window, min_lag=2, max_lag=20)

    assert len(h_series) == len(df)
    assert h_series.iloc[: window - 1].isna().all()
    assert h_series.iloc[window - 1 :].notna().all()


def test_ema_trend_signal_sign_matches_injected_trend():
    up = synthetic_dataframe(300, drift=0.005, gbm_vol=0.003, ou_theta=0.0, ou_sigma=0.0, seed=5)
    down = synthetic_dataframe(300, drift=-0.005, gbm_vol=0.003, ou_theta=0.0, ou_sigma=0.0, seed=5)

    up_signal = ema_trend_signal(up["close"], fast=12, slow=48).iloc[-1]
    down_signal = ema_trend_signal(down["close"], fast=12, slow=48).iloc[-1]

    assert up_signal > 0, "Tendance haussiere doit donner un signal positif"
    assert down_signal < 0, "Tendance baissiere doit donner un signal negatif"


def test_ou_signal_detects_positive_theta_and_correct_direction():
    # Forte composante OU, quasi pas de derive/bruit -> theta estime doit
    # etre positif (reversion detectee) sur la quasi-totalite de la fenetre.
    df = synthetic_dataframe(400, drift=0.0, gbm_vol=0.0003, ou_theta=0.25, ou_sigma=0.03, seed=6)
    result = ou_meanreversion_signal(df["close"], window=100)

    valid_theta = result["theta"].dropna()
    assert len(valid_theta) > 0
    assert (valid_theta > 0).mean() > 0.8, "theta doit etre positif la plupart du temps sur serie mean-reverting"

    # Verifie le sens du signal : quand le prix est au-dessus de mu estime,
    # le signal doit etre negatif (anticipe une baisse vers la moyenne), et
    # inversement.
    log_close = np.log(df["close"])
    valid = result.dropna()
    above_mu = log_close.loc[valid.index] > valid["mu"]
    assert (valid.loc[above_mu, "signal"] < 0).mean() > 0.8
    assert (valid.loc[~above_mu, "signal"] > 0).mean() > 0.8


def test_ou_signal_is_nan_when_no_reversion_detected():
    # Serie purement tendancielle (marche aleatoire avec derive, pas d'OU) :
    # la regression AR(1) doit generalement trouver b >= 1 (pas de rappel),
    # donc le signal ne doit pas etre invente.
    df = synthetic_dataframe(300, drift=0.01, gbm_vol=0.02, ou_theta=0.0, ou_sigma=0.0, seed=8)
    result = ou_meanreversion_signal(df["close"], window=100)
    coverage = result["signal"].notna().mean()
    assert coverage < 0.5, f"Le signal OU ne devrait pas se declencher souvent sur une serie sans reversion (couverture={coverage:.2f})"


def test_ou_signal_half_life_consistent_with_theta():
    # Verification mathematique pure (cf. Chan, "Algorithmic Trading", chap. 2) :
    # half_life doit valoir exactement log(2)/theta partout ou les deux sont
    # definis, quelle que soit la serie.
    df = synthetic_dataframe(400, drift=0.0, gbm_vol=0.0003, ou_theta=0.25, ou_sigma=0.03, seed=6)
    result = ou_meanreversion_signal(df["close"], window=100)
    valid = result.dropna(subset=["theta", "half_life"])
    assert len(valid) > 0
    np.testing.assert_allclose(valid["half_life"], np.log(2) / valid["theta"], rtol=1e-9)


def test_estimate_dominant_half_life_recovers_known_value():
    # ou_theta=0.25 avec dt=1 (defaut) correspond exactement au theta discret
    # estime par regression AR(1) (meme recursion, cf. synthetic.py) -> la
    # demi-vie vraie est log(2)/0.25 ~= 2.77 periodes. gbm_vol tres faible
    # pour que la composante OU domine (comme test_ou_signal_detects_positive_theta).
    true_theta = 0.25
    df = synthetic_dataframe(500, drift=0.0, gbm_vol=0.0003, ou_theta=true_theta, ou_sigma=0.03, seed=6)
    estimated = estimate_dominant_half_life(df["close"], window=100)
    true_half_life = np.log(2) / true_theta
    assert np.isfinite(estimated)
    assert 0.5 * true_half_life < estimated < 2.0 * true_half_life, (
        f"demi-vie estimee {estimated:.2f} trop eloignee de la vraie valeur {true_half_life:.2f}"
    )


def test_estimate_dominant_half_life_nan_when_no_reversion():
    # seed=4 (contrairement au seed=8 du test ci-dessus) ne produit aucun
    # faux positif de significativite sur cette serie tendancielle - verifie
    # empiriquement, cf. commentaire equivalent plus bas.
    df = synthetic_dataframe(300, drift=0.01, gbm_vol=0.02, ou_theta=0.0, ou_sigma=0.0, seed=4)
    assert np.isnan(estimate_dominant_half_life(df["close"], window=100))


def test_suggest_meanreversion_window_scales_with_half_life():
    true_theta = 0.25
    multiplier = 3.0
    df = synthetic_dataframe(500, drift=0.0, gbm_vol=0.0003, ou_theta=true_theta, ou_sigma=0.03, seed=6)
    suggested = suggest_meanreversion_window(df["close"], window=100, multiplier=multiplier, min_window=5, max_window=300)
    expected = multiplier * np.log(2) / true_theta
    assert suggested is not None
    assert 5 <= suggested <= 300
    # Tolerance large : estimate_dominant_half_life a sa propre marge d'erreur,
    # deja verifiee separement dans test_estimate_dominant_half_life_recovers_known_value.
    assert 0.3 * expected < suggested < 3.0 * expected


def test_suggest_meanreversion_window_respects_bounds():
    true_theta = 0.25
    df = synthetic_dataframe(500, drift=0.0, gbm_vol=0.0003, ou_theta=true_theta, ou_sigma=0.03, seed=6)
    # multiplier enorme pour forcer le clamp au plafond
    suggested = suggest_meanreversion_window(df["close"], window=100, multiplier=1000.0, min_window=5, max_window=50)
    assert suggested == 50


def test_suggest_meanreversion_window_none_when_no_reversion():
    df = synthetic_dataframe(300, drift=0.01, gbm_vol=0.02, ou_theta=0.0, ou_sigma=0.0, seed=4)
    assert suggest_meanreversion_window(df["close"], window=100) is None


def test_ewma_volatility_reacts_to_regime_change():
    low_vol = synthetic_dataframe(200, drift=0.0, gbm_vol=0.001, ou_theta=0.0, ou_sigma=0.0, seed=9)
    high_vol = synthetic_dataframe(200, drift=0.0, gbm_vol=0.03, ou_theta=0.0, ou_sigma=0.0, seed=10)

    vol_low = ewma_volatility(low_vol["close"]).iloc[-1]
    vol_high = ewma_volatility(high_vol["close"]).iloc[-1]

    assert vol_high > vol_low * 5, "La vol EWMA doit clairement distinguer un regime calme d'un regime agite"


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK: {t.__name__}")
    print(f"\nTous les tests signals.py passent ({len(tests)} tests).")
