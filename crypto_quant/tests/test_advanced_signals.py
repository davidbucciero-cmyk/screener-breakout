"""Tests des blocs quant avances (etape 21) - un bloc, une ou deux proprietes
verifiees, sur donnees synthetiques controlees (meme convention que
test_signals.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from crypto_quant.advanced_signals import (
    bayesian_aggregate_probabilities,
    carry_signal,
    cash_and_carry_consistency,
    cointegration_spread_signal,
    cross_sectional_momentum_tilt,
    daily_vwap_approx,
    garch_volatility,
    hmm_regime_signal,
    implied_probability_from_options,
    js_divergence,
    kl_divergence,
    macro_factor_exposure,
    min_variance_weights,
    ml_regularized_signal,
    risk_parity_weights,
    signal_distribution_divergence,
)
from crypto_quant.metrics import spa_test
from crypto_quant.synthetic import synthetic_dataframe


def _gold_like_series(n=400, seed=1, drift=0.0003, vol=0.008):
    df = synthetic_dataframe(n, timeframe="1d", drift=drift, gbm_vol=vol, momentum_rho=0.4, seed=seed)
    return df


def test_garch_volatility_shape_and_positivity():
    df = _gold_like_series(500, seed=1)
    vol = garch_volatility(df["close"])
    assert len(vol) == len(df)
    valid = vol.dropna()
    assert len(valid) > 0
    assert (valid > 0).all()


def test_garch_volatility_rejects_non_positive_price():
    close = pd.Series([100.0] * 50 + [-1.0] + [100.0] * 50, index=pd.date_range("2024-01-01", periods=101, freq="D"))
    with pytest.raises(ValueError, match="prix <= 0"):
        garch_volatility(close)


def test_hmm_regime_signal_bounded_probability():
    df = _gold_like_series(300, seed=2)
    prob = hmm_regime_signal(df["close"], n_states=2)
    valid = prob.dropna()
    assert len(valid) > 0
    assert (valid >= 0).all() and (valid <= 1).all()


def test_hmm_regime_signal_detects_higher_vol_regime():
    # Deux segments : vol faible puis vol forte - l'etat "haute vol" doit
    # etre nettement plus probable sur le segment volatil.
    calm = synthetic_dataframe(200, timeframe="1d", drift=0.0001, gbm_vol=0.002, momentum_rho=0.0, ou_theta=0.0, ou_sigma=0.0, seed=3)
    volatile = synthetic_dataframe(
        200, timeframe="1d", drift=0.0001, gbm_vol=0.02, momentum_rho=0.0, ou_theta=0.0, ou_sigma=0.0, seed=4,
        end_ms=int((calm.index[-1] + pd.Timedelta(days=200)).timestamp() * 1000),
    )
    combined = pd.concat([calm["close"], volatile["close"]])
    combined.index = pd.date_range("2023-01-01", periods=len(combined), freq="D", tz="UTC")

    prob = hmm_regime_signal(combined, n_states=2)
    prob_calm_segment = prob.iloc[50:200].mean()
    prob_volatile_segment = prob.iloc[250:400].mean()
    assert prob_volatile_segment > prob_calm_segment


def test_carry_signal_sign_matches_backwardation():
    index = pd.date_range("2024-01-01", periods=50, freq="D")
    front = pd.Series(100.0, index=index)
    next_cheaper = pd.Series(95.0, index=index)  # backwardation : le suivant est moins cher
    carry = carry_signal(front, next_cheaper, days_to_next_expiry=90)
    assert (carry > 0).all()


def test_cointegration_spread_signal_detects_known_relationship():
    n = 300
    rng = np.random.default_rng(7)
    log_b = np.cumsum(rng.normal(0, 0.01, n))
    noise = rng.normal(0, 0.002, n)
    log_a = 0.5 * log_b + noise  # a = cointegre avec b, hedge ratio connu = 0.5
    index = pd.date_range("2023-01-01", periods=n, freq="D")
    asset_a = pd.Series(np.exp(log_a) * 100, index=index)
    asset_b = pd.Series(np.exp(log_b) * 100, index=index)

    result = cointegration_spread_signal(asset_a, asset_b, window=100, significance_t=1.0)
    estimated_beta = result["beta"].dropna().mean()
    assert abs(estimated_beta - 0.5) < 0.15


def test_cross_sectional_momentum_tilt_favors_strongest_asset():
    index = pd.date_range("2024-01-01", periods=100, freq="D")
    returns = pd.DataFrame(
        {"strong": np.full(100, 0.01), "weak": np.full(100, -0.005), "flat": np.full(100, 0.0)}, index=index
    )
    weights = cross_sectional_momentum_tilt(returns, lookback=30)
    last = weights.iloc[-1]
    assert last["strong"] > last["flat"] > last["weak"]
    assert (last >= 0).all()


def test_cash_and_carry_consistency_zero_deviation_when_theoretical():
    index = pd.date_range("2024-01-01", periods=30, freq="D")
    spot = pd.Series(100.0, index=index)
    T = 90 / 365.0
    r = 0.02
    theoretical_front = spot * np.exp(r * T)
    result = cash_and_carry_consistency(theoretical_front, spot, risk_free_rate=r, days_to_next_expiry=90)
    assert np.allclose(result["deviation"], 0.0, atol=1e-9)


def test_macro_factor_exposure_recovers_known_beta():
    n = 400
    rng = np.random.default_rng(11)
    dxy_ret = rng.normal(0, 0.005, n)
    real_yield_ret = rng.normal(0, 0.003, n)
    vix = rng.normal(20, 2, n)
    true_beta_dxy = -0.8
    gold_ret = true_beta_dxy * dxy_ret + rng.normal(0, 0.001, n)
    index = pd.date_range("2023-01-01", periods=n, freq="D")

    result = macro_factor_exposure(
        pd.Series(gold_ret, index=index),
        pd.Series(dxy_ret, index=index),
        pd.Series(real_yield_ret, index=index),
        pd.Series(vix, index=index),
        window=200,
    )
    estimated = result["beta_dxy"].dropna().mean()
    assert abs(estimated - true_beta_dxy) < 0.2


def test_implied_probability_from_options_near_half_at_the_money():
    calls = pd.DataFrame({"strike": [100.0], "impliedVolatility": [0.15]})
    result = implied_probability_from_options(calls, spot=100.0, days_to_expiry=30, risk_free_rate=0.0)
    # A la monnaie, r=0 : d2 legerement negatif (terme -0.5*sigma^2*T), donc
    # prob < 0.5 mais proche.
    assert 0.4 < result["prob_above_strike"].iloc[0] < 0.5


def test_implied_probability_decreases_with_strike():
    calls = pd.DataFrame({"strike": [90.0, 100.0, 110.0], "impliedVolatility": [0.15, 0.15, 0.15]})
    result = implied_probability_from_options(calls, spot=100.0, days_to_expiry=30)
    probs = result.sort_values("strike")["prob_above_strike"].values
    assert probs[0] > probs[1] > probs[2]


def test_kl_js_divergence_zero_for_identical_distributions():
    p = np.array([0.2, 0.3, 0.5])
    assert kl_divergence(p, p) == pytest.approx(0.0, abs=1e-9)
    assert js_divergence(p, p) == pytest.approx(0.0, abs=1e-9)


def test_js_divergence_bounded_by_ln2():
    p = np.array([1.0, 0.0])
    q = np.array([0.0, 1.0])
    assert js_divergence(p, q) == pytest.approx(np.log(2), abs=1e-6)


def test_signal_distribution_divergence_detects_different_sources():
    index = pd.date_range("2024-01-01", periods=200, freq="D")
    rng = np.random.default_rng(5)
    signal_a = pd.Series(rng.normal(0, 1, 200), index=index)
    signal_b = pd.Series(rng.normal(5, 1, 200), index=index)  # distribution nettement decalee
    result = signal_distribution_divergence(signal_a, signal_b, bins=15)
    assert result["kl_divergence"] > 0.5
    assert result["js_divergence"] > 0.1


def test_bayesian_aggregate_probabilities_averages_in_logit_space():
    df = pd.DataFrame({"a": [0.9], "b": [0.1]})
    combined = bayesian_aggregate_probabilities(df)
    # Deux sources opposees et egalement ponderees -> logits s'annulent -> 0.5
    assert combined.iloc[0] == pytest.approx(0.5, abs=1e-6)


def test_bayesian_aggregate_probabilities_respects_weights():
    df = pd.DataFrame({"a": [0.9], "b": [0.1]})
    weights = pd.Series({"a": 10.0, "b": 0.0})
    combined = bayesian_aggregate_probabilities(df, weights=weights)
    assert combined.iloc[0] == pytest.approx(0.9, abs=1e-6)


def test_daily_vwap_approx_shape_and_warmup():
    df = _gold_like_series(100, seed=9)
    vwap = daily_vwap_approx(df, window=20)
    assert len(vwap) == len(df)
    assert vwap.iloc[:19].isna().all()
    assert vwap.iloc[19:].notna().all()


def test_risk_parity_weights_equalizes_risk_contribution():
    cov = pd.DataFrame([[0.04, 0.0], [0.0, 0.01]], index=["volatile", "calm"], columns=["volatile", "calm"])
    weights = risk_parity_weights(cov)
    # Actif 2x plus volatil (ecart-type) doit recevoir environ moitie moins de poids
    assert weights["volatile"] < weights["calm"]
    contrib = weights.values * (cov.values @ weights.values)
    assert np.allclose(contrib[0], contrib[1], rtol=0.05)


def test_min_variance_weights_sums_to_one_and_long_only():
    cov = pd.DataFrame([[0.04, 0.01], [0.01, 0.01]], index=["a", "b"], columns=["a", "b"])
    weights = min_variance_weights(cov)
    assert weights.sum() == pytest.approx(1.0, abs=1e-6)
    assert (weights >= 0).all()


def test_ml_regularized_signal_respects_train_test_split():
    n = 200
    index = pd.date_range("2023-01-01", periods=n, freq="D")
    rng = np.random.default_rng(13)
    feature = rng.normal(0, 1, n)
    target = pd.Series((feature > 0).astype(int), index=index)
    features = pd.DataFrame({"f1": feature}, index=index)

    result = ml_regularized_signal(features, target, train_frac=0.6)
    split = int(n * 0.6)
    assert result.iloc[:split].isna().all()
    assert result.iloc[split:].notna().all()
    assert ((result.dropna() >= 0) & (result.dropna() <= 1)).all()


def test_spa_test_rejects_when_no_real_edge():
    # Plusieurs strategies purement aleatoires testees contre un benchmark
    # nul : la meilleure NE DOIT PAS sembler significative une fois
    # corrigee pour le nombre de strategies essayees.
    rng = np.random.default_rng(21)
    n, k = 500, 20
    strategy_returns = pd.DataFrame(rng.normal(0, 0.01, (n, k)), columns=[f"strat_{i}" for i in range(k)])
    benchmark = pd.Series(0.0, index=strategy_returns.index)

    result = spa_test(strategy_returns, benchmark, n_bootstrap=500, block_size=10, seed=42)
    assert result["p_value"] > 0.05


def test_spa_test_detects_genuine_edge():
    rng = np.random.default_rng(22)
    n, k = 500, 10
    strategy_returns = pd.DataFrame(rng.normal(0, 0.01, (n, k)), columns=[f"strat_{i}" for i in range(k)])
    strategy_returns["strat_0"] += 0.01  # un edge large et constant, doit ressortir
    benchmark = pd.Series(0.0, index=strategy_returns.index)

    result = spa_test(strategy_returns, benchmark, n_bootstrap=500, block_size=10, seed=42)
    assert result["best_strategy"] == "strat_0"
    assert result["p_value"] < 0.05
