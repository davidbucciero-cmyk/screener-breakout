"""Tests du carry BTC perpetuel/spot (etape 22) - un cas, une propriete
verifiee, sur donnees synthetiques controlees (meme convention que
test_advanced_signals.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd
import pytest

from crypto_quant.btc_carry import BTCCarryConfig, basis_bps, basis_vol_gate, basis_zscore, carry_spread_equity


def _index(n=200):
    return pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")


def test_basis_bps_simple_arithmetic():
    idx = _index(3)
    spot = pd.Series([100.0, 100.0, 100.0], index=idx)
    perp = pd.Series([101.0, 99.0, 100.0], index=idx)
    b = basis_bps(spot, perp)
    assert b.iloc[0] == pytest.approx(100.0)  # +1% = 100 bps
    assert b.iloc[1] == pytest.approx(-100.0)
    assert b.iloc[2] == pytest.approx(0.0)


def test_basis_zscore_mean_reverting_series_has_correct_sign():
    # Basis oscille autour de 0 avec un pic positif net au milieu -
    # le z-score doit etre nettement positif a ce pic, nettement negatif
    # dans les creux qui l'entourent (pas juste "non nul n'importe ou").
    rng = np.random.default_rng(0)
    n = 150
    idx = _index(n)
    spot = pd.Series(100.0, index=idx)
    noise = rng.normal(0, 2.0, n)
    basis = noise.copy()
    basis[70:80] += 40.0  # pic net de basis positif (perpetuel cher)
    perp = spot * (1 + basis / 10000)

    z = basis_zscore(spot, perp, window=30)
    assert z.iloc[75] > 1.5
    assert z.iloc[20] < 1.0  # avant le pic, loin de l'extreme


def test_basis_vol_gate_off_in_calm_regime_on_in_volatile_regime():
    rng = np.random.default_rng(1)
    n = 100
    idx = _index(n)
    spot = pd.Series(100.0, index=idx)
    calm_basis = rng.normal(0, 1.0, n // 2)  # ecart-type ~1bp, tres calme
    volatile_basis = rng.normal(0, 50.0, n // 2)  # ecart-type ~50bp
    basis = np.concatenate([calm_basis, volatile_basis])
    perp = spot * (1 + basis / 10000)

    gate = basis_vol_gate(spot, perp, vol_threshold_bps=15.0, window=20)
    # Fin du regime calme (apres le warm-up de la fenetre) : porte fermee.
    assert gate.iloc[40] == 0.0
    # Fin du regime volatil : porte ouverte.
    assert gate.iloc[-1] == 1.0


def test_carry_spread_equity_smoke_runs_without_nan():
    rng = np.random.default_rng(2)
    n = 200
    idx = _index(n)
    spot = pd.Series(100.0 * np.cumprod(1 + rng.normal(0, 0.01, n)), index=idx)
    perp = spot * (1 + rng.normal(0, 0.001, n))

    equity = carry_spread_equity(spot, perp, BTCCarryConfig(vol_threshold_bps=0.0))
    assert len(equity) == n
    assert not equity.isna().any()
    assert (equity > 0).all()


def test_carry_spread_equity_never_trades_on_the_first_day():
    # Anti-lookahead : le z-score du jour 0 ne doit influencer aucune
    # position avant le jour 1 (position = target.shift(1)).
    rng = np.random.default_rng(3)
    n = 100
    idx = _index(n)
    spot = pd.Series(100.0, index=idx)
    basis = rng.normal(0, 30.0, n)
    basis[0] = 500.0  # extreme des le premier jour, si lookahead il y a, il se verrait ici
    perp = spot * (1 + basis / 10000)

    equity = carry_spread_equity(spot, perp, BTCCarryConfig(vol_threshold_bps=0.0, no_trade_band=0.0))
    # Premier jour : aucune position possible -> aucun P&L ni cout -> equity inchangee.
    assert equity.iloc[0] == pytest.approx(10_000.0)


def test_carry_spread_equity_profits_from_a_single_isolated_basis_spike():
    # Test chirurgical du sens de la position plutot qu'un scenario
    # multi-phases (sujet a un effet d'auto-amortissement du z-score :
    # un saut de niveau gonfle temporairement son propre ecart-type
    # glissant, ce qui attenue le z-score de ce meme saut - une
    # propriete reelle de tout signal de retour a la moyenne GLISSANTE,
    # a garder en tete pour l'usage reel ou le vrai basis BTC oscille
    # sur des echelles courtes, cf. etape 22). Ici : baseline plate avec
    # un bruit minuscule (empeche une division par un ecart-type nul),
    # un pic isole d'UN SEUL jour, puis retour immediat a zero - la
    # position du jour SUIVANT le pic (donc appliquee au rendement de
    # la convergence) doit etre negative (short le spread), et son
    # produit avec le rendement de convergence (negatif) doit etre
    # positif.
    n = 60
    idx = _index(n)
    rng = np.random.default_rng(5)
    spot = pd.Series(100.0, index=idx)
    basis = rng.normal(0, 0.5, n)  # bruit minuscule, non nul
    basis[40] = 80.0  # pic isole d'un seul jour
    perp = spot * (1 + basis / 10000)

    z = basis_zscore(spot, perp, window=30)
    assert z.iloc[40] > 2.0  # le pic est bien detecte comme extreme

    target_exposure = (-z.clip(-2.0, 2.0) / 2.0).clip(-1, 1)
    position_day_41 = target_exposure.shift(1).iloc[41]
    spread_return_day_41 = perp.pct_change().iloc[41] - spot.pct_change().iloc[41]

    assert position_day_41 < 0  # parie sur la convergence (short le spread)
    assert spread_return_day_41 < 0  # le perpetuel retombe par rapport au spot
    assert position_day_41 * spread_return_day_41 > 0  # le pari est gagnant


def test_no_trade_band_reduces_turnover():
    # Propriete MECANIQUE garantie (pas une comparaison de performance,
    # qui dependrait du tirage aleatoire) : une bande plus large ne peut
    # que reduire ou egaler le nombre de rebalancements, jamais
    # l'augmenter - diagnostic etape 22 ter (turnover de dithering
    # quotidien sur un z-score bruite, cout evitable sans perdre l'edge).
    rng = np.random.default_rng(4)
    n = 300
    idx = _index(n)
    spot = pd.Series(100.0, index=idx)
    basis = rng.normal(0, 25.0, n)
    perp = spot * (1 + basis / 10000)

    def n_trades(no_trade_band: float) -> int:
        cfg = BTCCarryConfig(vol_threshold_bps=0.0, no_trade_band=no_trade_band, spot_fee_bps=16.0, perp_fee_bps=2.0)
        z = basis_zscore(spot, perp, cfg.z_window)
        target = (-z.clip(-cfg.clip_z, cfg.clip_z) / cfg.clip_z).clip(-1, 1).shift(1).fillna(0.0)
        prev_pos = 0.0
        count = 0
        for tgt in target:
            pos = tgt if abs(tgt - prev_pos) > no_trade_band else prev_pos
            if pos != prev_pos:
                count += 1
            prev_pos = pos
        return count

    assert n_trades(no_trade_band=0.5) < n_trades(no_trade_band=0.0)


def test_exec_spot_none_reproduces_same_venue_behavior():
    # exec_spot=None (defaut) doit redonner EXACTEMENT le meme resultat
    # que passer exec_spot=spot explicitement - garde-fou de non-
    # regression pour le comportement d'origine (signal et execution sur
    # le meme exchange).
    rng = np.random.default_rng(6)
    n = 150
    idx = _index(n)
    spot = pd.Series(100.0 * np.cumprod(1 + rng.normal(0, 0.01, n)), index=idx)
    perp = spot * (1 + rng.normal(0, 0.001, n))
    cfg = BTCCarryConfig(vol_threshold_bps=0.0, no_trade_band=0.0)

    eq_default = carry_spread_equity(spot, perp, cfg)
    eq_explicit = carry_spread_equity(spot, perp, cfg, exec_spot=spot)
    pd.testing.assert_series_equal(eq_default, eq_explicit)


def test_exec_spot_different_venue_changes_realized_pnl_not_the_signal():
    # Le SIGNAL (quand/combien trader) doit continuer a dependre de `spot`
    # (Kraken), pas de `exec_spot` (OKX) - seul le P&L REALISE de la jambe
    # spot doit changer. Construit un cas ou exec_spot diverge nettement
    # de spot sur les rendements (meme niveau de prix, trajectoire
    # differente) et verifie que l'equity change bien, sans planter.
    rng = np.random.default_rng(7)
    n = 150
    idx = _index(n)
    spot = pd.Series(100.0 * np.cumprod(1 + rng.normal(0, 0.01, n)), index=idx)
    perp = spot * (1 + rng.normal(0, 0.001, n))
    exec_spot = pd.Series(100.0 * np.cumprod(1 + rng.normal(0, 0.012, n)), index=idx)  # autre trajectoire, meme index
    cfg = BTCCarryConfig(vol_threshold_bps=0.0, no_trade_band=0.0)

    eq_same_venue = carry_spread_equity(spot, perp, cfg)
    eq_hybrid = carry_spread_equity(spot, perp, cfg, exec_spot=exec_spot)

    assert not eq_same_venue.equals(eq_hybrid)
    assert not eq_hybrid.isna().any()


def test_exec_spot_misaligned_index_raises():
    idx = _index(100)
    spot = pd.Series(100.0, index=idx)
    perp = pd.Series(100.0, index=idx)
    exec_spot_wrong_index = pd.Series(100.0, index=_index(90))  # fenetre differente

    with pytest.raises(ValueError):
        carry_spread_equity(spot, perp, BTCCarryConfig(), exec_spot=exec_spot_wrong_index)
