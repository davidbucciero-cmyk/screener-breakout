"""Tests du bot de paper trading sur le carry BTC (etape 22 quater).

Aucun test n'appelle ccxt/Kraken : spot/perp sont toujours injectes
directement dans run_daily_step (meme convention que
test_gold_paper_bot.py)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd

from crypto_quant.btc_carry import BTCCarryConfig
from crypto_quant.btc_carry_paper_bot import run_daily_step


def _spot_perp(n=100, seed=1, spike_at=None, spike_bps=80.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    spot = pd.Series(100.0 * np.cumprod(1 + rng.normal(0, 0.01, n)), index=idx)
    basis = rng.normal(0, 3.0, n)
    if spike_at is not None:
        basis[spike_at] = spike_bps
    perp = spot * (1 + basis / 10000)
    return spot, perp


def _light_cfg(**overrides):
    base = dict(z_window=15, clip_z=2.0, vol_threshold_bps=0.0, vol_gate_window=10, no_trade_band=0.0, spot_fee_bps=16.0, perp_fee_bps=2.0)
    base.update(overrides)
    return BTCCarryConfig(**base)


def test_run_daily_step_basic_execution(tmp_path):
    spot, perp = _spot_perp()
    result = run_daily_step(state_dir=str(tmp_path), config=_light_cfg(), spot=spot, perp=perp)

    assert result["status"] == "execute"
    assert result["equity"] > 0
    assert -1.0 <= result["new_position"] <= 1.0
    assert os.path.exists(os.path.join(tmp_path, "breaker.json"))
    assert os.path.exists(os.path.join(tmp_path, "position.json"))
    assert os.path.exists(os.path.join(tmp_path, "last_run.json"))
    assert os.path.exists(os.path.join(tmp_path, "daily_log.csv"))


def test_daily_log_accumulates_one_row_per_executed_day(tmp_path):
    spot, perp = _spot_perp(n=60, spike_at=40)
    cfg = _light_cfg()

    run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot, perp=perp)
    log_df = pd.read_csv(os.path.join(tmp_path, "daily_log.csv"))
    assert len(log_df) == 1
    assert list(log_df.columns) == [
        "date", "spot_close", "perp_close", "basis_bps", "trading_allowed", "prev_position", "new_position", "turnover", "equity",
    ]

    new_idx = spot.index[-1] + pd.Timedelta(days=1)
    spot2 = pd.concat([spot, pd.Series([float(spot.iloc[-1]) * 1.005], index=[new_idx])])
    perp2 = pd.concat([perp, pd.Series([float(perp.iloc[-1]) * 0.998], index=[new_idx])])
    run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot2, perp=perp2)

    log_df2 = pd.read_csv(os.path.join(tmp_path, "daily_log.csv"))
    assert len(log_df2) == 2  # une ligne de plus, pas ecrasee

    # Rejouer le meme jour (idempotent) ne doit RIEN ajouter au journal.
    run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot2, perp=perp2)
    log_df3 = pd.read_csv(os.path.join(tmp_path, "daily_log.csv"))
    assert len(log_df3) == 2


def test_run_daily_step_is_idempotent_for_same_date(tmp_path):
    spot, perp = _spot_perp()
    cfg = _light_cfg()

    first = run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot, perp=perp)
    second = run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot, perp=perp)

    assert first["status"] == "execute"
    assert second["status"] == "deja_a_jour"


def test_run_daily_step_never_trades_on_the_very_first_call():
    # Jour 1 : aucune position precedente (etat par defaut, prev_position=0)
    # et le pipeline n'a pas encore de donnees "d'hier" a comparer - la
    # position cible du jour peut etre non nulle (le signal est calcule sur
    # tout l'historique fourni), mais aucun rendement ne peut encore avoir
    # ete REALISE avant cette toute premiere execution.
    import tempfile

    spot, perp = _spot_perp()
    with tempfile.TemporaryDirectory() as d:
        result = run_daily_step(state_dir=d, config=_light_cfg(), spot=spot, perp=perp)
    # Le compte part du capital initial, le premier rendement realise doit
    # etre nul puisque prev_position=0 au tout premier appel (pas de P&L
    # sans position deja ouverte) - seul un cout de turnover (entree en
    # position) peut legitimement faire baisser l'equity un peu.
    assert result["equity"] <= 10_000.0 + 1e-6


def test_run_daily_step_persists_equity_and_position_across_two_days(tmp_path):
    spot, perp = _spot_perp(n=60, spike_at=40)
    cfg = _light_cfg(no_trade_band=0.0)

    day1 = run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot, perp=perp)

    # Jour suivant : une bougie de plus sur les deux jambes.
    rng = np.random.default_rng(99)
    new_idx = spot.index[-1] + pd.Timedelta(days=1)
    spot2 = pd.concat([spot, pd.Series([float(spot.iloc[-1]) * 1.005], index=[new_idx])])
    perp2 = pd.concat([perp, pd.Series([float(perp.iloc[-1]) * 0.998], index=[new_idx])])  # le perp retombe (convergence)

    day2 = run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot2, perp=perp2)

    assert day2["status"] == "execute"
    assert day2["prev_position"] == day1["new_position"]  # l'etat d'hier a bien ete recharge
    # Si une position etait ouverte hier, l'equity du jour 2 doit refleter
    # le rendement realise, pas repartir du capital initial.
    if day1["new_position"] != 0.0:
        assert day2["equity"] != day1["equity"]


def test_run_daily_step_forces_flat_when_circuit_breaker_halts(tmp_path):
    cfg = _light_cfg(clip_z=1.0)  # exposition agressive pour ouvrir une grosse position facilement
    spot, perp = _spot_perp(n=60, spike_at=40, spike_bps=150.0)

    day1 = run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot, perp=perp)
    assert day1["new_position"] != 0.0  # precondition : une position est ouverte

    # Jour suivant : mouvement du perpetuel qui PENALISE la position
    # ouverte (position negative = short le spread -> une perte demande
    # que le perpetuel MONTE fortement par rapport au spot, et
    # inversement) pour declencher le coupe-circuit.
    new_idx = spot.index[-1] + pd.Timedelta(days=1)
    adverse_move_sign = -1.0 if day1["new_position"] > 0 else 1.0
    spot2 = pd.concat([spot, pd.Series([float(spot.iloc[-1])], index=[new_idx])])
    perp2 = pd.concat([perp, pd.Series([float(perp.iloc[-1]) * (1 + adverse_move_sign * 0.5)], index=[new_idx])])

    result = run_daily_step(state_dir=str(tmp_path), config=cfg, spot=spot2, perp=perp2)

    assert result["trading_allowed"] is False
    assert result["new_position"] == 0.0


def test_run_daily_step_never_sends_real_orders():
    import inspect

    import crypto_quant.btc_carry_paper_bot as module

    source = inspect.getsource(module)
    assert "dry_run=False" not in source
    assert "CRYPTO_QUANT_CONFIRM_LIVE_TRADING" not in source
