"""Tests du module risque/sizing (etape 4)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd

from crypto_quant.risk import (
    DrawdownCircuitBreaker,
    atr,
    atr_stop_loss_price,
    inverse_vol_weights,
    kelly_fraction,
    portfolio_volatility_estimate,
    volatility_target_leverage,
)


def test_inverse_vol_weights_favors_less_volatile_asset():
    score_weights = pd.Series({"BTC": 0.5, "ETH": 0.5})  # meme poids-score au depart
    vols = pd.Series({"BTC": 0.02, "ETH": 0.06})  # ETH 3x plus volatil

    tilted = inverse_vol_weights(score_weights, vols)

    assert abs(tilted.sum() - 1.0) < 1e-9
    assert tilted["BTC"] > tilted["ETH"], "L'actif moins volatil doit recevoir plus de poids a score egal"
    # Le ratio des poids doit etre l'inverse du ratio des vols (3x).
    assert abs(tilted["BTC"] / tilted["ETH"] - 3.0) < 1e-6


def test_inverse_vol_weights_zero_when_no_positive_score():
    score_weights = pd.Series({"BTC": 0.0, "ETH": 0.0})
    vols = pd.Series({"BTC": 0.02, "ETH": 0.06})
    tilted = inverse_vol_weights(score_weights, vols)
    assert (tilted == 0).all()


def test_portfolio_volatility_estimate_is_weighted_sum():
    weights = pd.Series({"BTC": 0.6, "ETH": 0.4})
    vols = pd.Series({"BTC": 0.02, "ETH": 0.05})
    expected = 0.6 * 0.02 + 0.4 * 0.05
    assert abs(portfolio_volatility_estimate(weights, vols) - expected) < 1e-12


def test_volatility_target_leverage_caps_at_max_leverage():
    weights = pd.Series({"BTC": 1.0})
    low_vol = pd.Series({"BTC": 0.001})  # vol tres faible -> levier voudrait etre tres eleve
    leverage = volatility_target_leverage(weights, low_vol, target_vol=0.02, max_leverage=1.0)
    assert leverage == 1.0, "Le levier ne doit jamais depasser max_leverage (spot, pas d'emprunt)"


def test_volatility_target_leverage_scales_down_when_too_risky():
    weights = pd.Series({"BTC": 1.0})
    high_vol = pd.Series({"BTC": 0.10})
    leverage = volatility_target_leverage(weights, high_vol, target_vol=0.02, max_leverage=1.0)
    assert abs(leverage - 0.2) < 1e-9


def test_kelly_fraction_zero_on_negative_edge():
    # win_rate bas, payoff faible -> edge negatif -> Kelly doit etre nul, jamais negatif.
    f = kelly_fraction(win_rate=0.3, payoff_ratio=1.0, kelly_cap=0.25)
    assert f == 0.0


def test_kelly_fraction_positive_edge_is_capped_by_kelly_cap():
    # Edge net positif connu : p=0.6, b=1.5 -> Kelly plein = 0.6 - 0.4/1.5 = 0.3333
    full_kelly = 0.6 - 0.4 / 1.5
    f_quarter = kelly_fraction(win_rate=0.6, payoff_ratio=1.5, kelly_cap=0.25)
    assert abs(f_quarter - full_kelly * 0.25) < 1e-9
    assert f_quarter < full_kelly, "Le Kelly fractionnaire doit etre strictement plus prudent que le Kelly plein"


def test_atr_reacts_to_true_range_including_gaps():
    # Une bougie avec un gap (open tres eloigne du close precedent) doit
    # augmenter l'ATR meme si sa propre amplitude high-low est faible.
    df = pd.DataFrame(
        {
            "open": [100, 101, 102, 150, 151],
            "high": [101, 102, 103, 151, 152],
            "low": [99, 100, 101, 149, 150],
            "close": [100.5, 101.5, 102.5, 150.5, 151.5],
        }
    )
    result = atr(df, window=3)
    # La derniere valeur d'ATR doit capturer le gap 103 -> 150.
    assert result.iloc[-1] > (df["high"] - df["low"]).iloc[-3:].mean()


def test_atr_stop_loss_price_long_position():
    stop = atr_stop_loss_price(entry_price=100.0, atr_value=2.0, direction=1, atr_mult=2.0)
    assert stop == 96.0


def test_drawdown_circuit_breaker_halts_and_resumes_with_hysteresis():
    # Equity : monte a 100, chute a 75 (dd=-25%, doit haltee au-dela de 20%),
    # reste basse (85, dd=-15%, ne doit PAS reprendre tant que dd > -10%),
    # puis remonte a 92 (dd=-8%, doit reprendre).
    equity = pd.Series([100, 100, 75, 85, 92], index=pd.RangeIndex(5))
    breaker = DrawdownCircuitBreaker(halt_drawdown=0.20, resume_drawdown=0.10)
    allowed = breaker.evaluate(equity)

    assert list(allowed) == [True, True, False, False, True]


def test_drawdown_circuit_breaker_rejects_invalid_thresholds():
    try:
        DrawdownCircuitBreaker(halt_drawdown=0.10, resume_drawdown=0.20)
        assert False, "Devrait lever une erreur si resume_drawdown >= halt_drawdown"
    except ValueError:
        pass


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK: {t.__name__}")
    print(f"\nTous les tests risk.py passent ({len(tests)} tests).")
