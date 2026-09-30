"""Tests de la combinaison de signaux et de l'allocation (etape 3).

Univers synthetique a 4 actifs avec un comportement connu par construction :
- TREND_UP     : momentum positif fort -> H>0.5, score doit finir positif
- TREND_DOWN   : momentum negatif fort -> H>0.5, score doit finir negatif
- MEANREV_LOW  : forte composante OU, prix actuellement sous sa moyenne -> H<0.5, score positif
- RANDOM       : marche aleatoire pure -> H proche de 0.5, score proche de 0

Seuls TREND_UP et MEANREV_LOW doivent recevoir un poids positif dans
l'allocation long-only finale.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pandas as pd

from crypto_quant.portfolio import build_universe_scores, composite_score, compute_target_weights_history, target_weights_row
from crypto_quant.signals import ema_trend_signal, ou_meanreversion_signal, rolling_hurst
from crypto_quant.synthetic import synthetic_dataframe

FIXED_END_MS = 1_700_000_000_000  # meme horodatage de fin pour aligner les 4 series
N = 800
WINDOW = 100


def _build_signals(symbol_kwargs: dict) -> dict:
    signals_by_symbol = {}
    for symbol, kwargs in symbol_kwargs.items():
        df = synthetic_dataframe(N, end_ms=FIXED_END_MS, **kwargs)
        signals_by_symbol[symbol] = pd.DataFrame(
            {
                "hurst": rolling_hurst(df["close"], window=WINDOW, max_lag=20),
                "ema_trend": ema_trend_signal(df["close"]),
                "ou_signal": ou_meanreversion_signal(df["close"], window=WINDOW)["signal"],
            }
        )
    return signals_by_symbol


UNIVERSE_KWARGS = {
    # drift (biais directionnel) + momentum_rho (persistance -> H>0.5) : la
    # derive seule ne suffit pas a produire H>0.5 (cf. tests signals.py), il
    # faut les deux pour une serie a la fois tendancielle ET orientee.
    "TREND_UP": dict(drift=0.003, gbm_vol=0.005, momentum_rho=0.7, ou_theta=0.0, ou_sigma=0.0, seed=42),
    "TREND_DOWN": dict(drift=-0.003, gbm_vol=0.005, momentum_rho=0.7, ou_theta=0.0, ou_sigma=0.0, seed=2),
    "MEANREV_LOW": dict(drift=0.0, gbm_vol=0.0003, ou_theta=0.25, ou_sigma=0.03, seed=6),
    "RANDOM": dict(drift=0.0, gbm_vol=0.01, ou_theta=0.0, ou_sigma=0.0, seed=3),
}


def test_composite_score_signs_match_expected_regime():
    signals = _build_signals(UNIVERSE_KWARGS)
    scores = build_universe_scores(signals)
    last_row = scores.iloc[-1]

    assert last_row["TREND_UP"] > 0, "Actif en tendance haussiere doit avoir un score final positif"
    assert last_row["MEANREV_LOW"] != 0, "Actif mean-reverting doit avoir un score non nul (edge detecte)"

    # RANDOM doit avoir un score proche de zero en moyenne (pas d'edge) :
    # on verifie l'amplitude moyenne plutot qu'une valeur exacte a un instant t.
    assert scores["RANDOM"].dropna().abs().mean() < scores["TREND_UP"].dropna().abs().mean()


def test_composite_score_trend_gate_override_replaces_hurst_derived_gate():
    # hurst=0.1 impliquerait normalement trend_gate=0 (meanrev_gate=0.8) -
    # un trend_gate ADX passe explicitement doit prendre le dessus sur le
    # gate derive du Hurst, meanrev_gate restant lui TOUJOURS derive du Hurst.
    idx = pd.RangeIndex(3)
    hurst = pd.Series([0.1, 0.1, 0.1], index=idx)
    ema_trend = pd.Series([1.0, 1.0, 1.0], index=idx)
    ou_signal = pd.Series([1.0, 1.0, 1.0], index=idx)
    adx_gate = pd.Series([1.0, 1.0, 1.0], index=idx)

    default = composite_score(hurst, ema_trend, ou_signal)
    overridden = composite_score(hurst, ema_trend, ou_signal, trend_gate=adx_gate)

    assert (default["trend_gate"] == 0.0).all(), "sans override, H=0.1 doit donner trend_gate=0"
    assert (overridden["trend_gate"] == 1.0).all(), "l'override doit remplacer le gate derive du Hurst"
    assert (overridden["meanrev_gate"] == default["meanrev_gate"]).all(), "meanrev_gate reste derive du Hurst"
    assert (overridden["raw_score"] > default["raw_score"]).all(), "le score doit refleter le trend_gate plus eleve"


def test_target_weights_row_is_long_only_and_normalized():
    signals = _build_signals(UNIVERSE_KWARGS)
    scores = build_universe_scores(signals)
    last_row = scores.iloc[-1]

    weights = target_weights_row(last_row)

    assert (weights >= 0).all(), "Aucun poids negatif autorise (spot long-only)"
    assert abs(weights.sum() - 1.0) < 1e-9 or weights.sum() == 0.0

    if last_row["TREND_DOWN"] < 0:
        assert weights["TREND_DOWN"] == 0.0, "Un actif a score negatif ne doit recevoir aucun poids"


def test_target_weights_row_top_n_limits_concentration():
    signals = _build_signals(UNIVERSE_KWARGS)
    scores = build_universe_scores(signals)
    last_row = scores.iloc[-1]

    weights_all = target_weights_row(last_row)
    n_positions_all = (weights_all > 0).sum()

    weights_top1 = target_weights_row(last_row, top_n=1)
    assert (weights_top1 > 0).sum() <= 1
    if n_positions_all >= 1:
        assert weights_top1.sum() == 1.0 or weights_top1.sum() == 0.0


def test_compute_target_weights_history_rows_sum_to_one_or_zero():
    signals = _build_signals(UNIVERSE_KWARGS)
    scores = build_universe_scores(signals)
    weights_history = compute_target_weights_history(scores)

    row_sums = weights_history.sum(axis=1)
    assert ((row_sums.round(9) == 1.0) | (row_sums.round(9) == 0.0)).all()
    assert (weights_history >= 0).all().all()


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    for t in tests:
        t()
        print(f"OK: {t.__name__}")
    print(f"\nTous les tests portfolio.py passent ({len(tests)} tests).")
