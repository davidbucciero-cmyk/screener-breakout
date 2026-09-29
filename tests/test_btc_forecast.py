import numpy as np
import pandas as pd
import pytest

from btc_forecast.backtest import evaluate, strategy_returns, walk_forward
from btc_forecast.model import QUANTILES, prob_up
from btc_forecast.report import build_html

OFFSETS = np.array([-1.28, -0.84, -0.52, -0.25, 0.0, 0.25, 0.52, 0.84, 1.28])  # quantiles N(0,1)


def synthetic_close(n=1500, phi=-0.3, seed=1):
    """Prix dont les rendements horaires sont AR(1) : un signal exploitable connu."""
    rng = np.random.default_rng(seed)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + rng.normal(0, 0.005)
    idx = pd.date_range('2025-01-01', periods=n, freq='h', tz='UTC')
    return pd.Series(30000 * np.exp(np.cumsum(r)), index=idx)


class RecordingForecaster:
    """Faux modele : memorise les contextes, predit une gaussienne autour d'une prevision AR(1)."""

    def __init__(self, phi=-0.3):
        self.phi, self.contexts = phi, []

    def predict_quantiles(self, contexts):
        self.contexts.extend(contexts)
        out = []
        for c in contexts:
            last = c[-1]
            mu = last * (1 + self.phi * (c[-1] / c[-2] - 1))
            out.append(mu + OFFSETS * last * 0.005)
        return np.array(out)


def test_prob_up_symmetric_and_tails():
    q = 100 + OFFSETS
    assert prob_up(100, q) == pytest.approx(0.5)
    assert prob_up(100, q + 0.5) > 0.5
    assert prob_up(100, q - 0.5) < 0.5
    assert prob_up(0, q) == pytest.approx(0.95)
    assert prob_up(1000, q) == pytest.approx(0.05)
    assert len(QUANTILES) == len(OFFSETS)


def test_walk_forward_has_no_lookahead():
    close = synthetic_close(800)
    fc = RecordingForecaster()
    preds = walk_forward(close, fc, n_test=100, context_len=64, batch_size=16)
    assert len(preds) == 100 and len(fc.contexts) == 100
    for (t, row), ctx in zip(preds.iterrows(), fc.contexts):
        assert len(ctx) == 64
        assert ctx[-1] == row['close']  # le contexte s'arrete a close[t]
        assert row['next_close'] not in ctx[-2:]
        assert close.loc[t] == row['close']
    # Derniere prevision = avant-derniere bougie (on doit connaitre la cible).
    assert preds.index[-1] == close.index[-2]


def test_evaluate_detects_known_signal():
    close = synthetic_close()
    preds = walk_forward(close, RecordingForecaster(), n_test=1200, context_len=64)
    calib, perf, reliability, curves = evaluate(preds, fee_bps=0)
    model = perf.iloc[0]
    random = perf[perf['strategie'] == 'Aleatoire'].iloc[0]
    assert model['taux_reussite'] > 0.55
    assert model['p_value_vs_50pct'] < 0.01
    assert model['rendement_net'] > random['rendement_net']
    assert calib['brier_modele'] < calib['brier_freq_constante']
    assert list(curves.columns) == list(perf['strategie'])
    html = build_html(calib, perf, reliability, curves,
                      {'model': 'fake', 'context_len': 64, 'start': 'a', 'end': 'b'}, 0)
    assert '<svg' in html and 'Buy &amp; hold' in html


def test_strategy_fees_only_on_position_changes():
    ret = pd.Series([0.01, 0.01, 0.01, 0.01])
    net = strategy_returns([1, 1, -1, 0], ret, fee_bps=10)
    # entree long (1 cote), flip long->short (2 cotes), sortie (1 cote)
    assert net.tolist() == pytest.approx([0.01 - 0.001, 0.01, -0.01 - 0.002, -0.001])
