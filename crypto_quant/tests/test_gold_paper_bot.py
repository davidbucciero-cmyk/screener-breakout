"""Tests du bot de paper trading sur l'or (etape 18).

Aucun test n'appelle yfinance : price_data est toujours injecte
directement dans run_daily_step (cf. son parametre d'injection dedie).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import numpy as np
import pandas as pd

from crypto_quant.backtest import BacktestConfig
from crypto_quant.gold_paper_bot import SYMBOL, run_daily_step
from crypto_quant.synthetic import synthetic_dataframe


def _gold_like_universe(n=400, seed=1):
    df = synthetic_dataframe(
        n, timeframe="1d", drift=0.0005, gbm_vol=0.006, momentum_rho=0.5, ou_theta=0.0, ou_sigma=0.0, seed=seed
    )
    return {SYMBOL: df}


def _light_cfg(**overrides):
    # Fenetres allegees pour que le warm-up tienne dans des series de test
    # courtes - la config de production (GOLD_CONFIG) utilise des fenetres
    # de ~250 jours, trop lourdes a generer pour des tests unitaires rapides.
    base = dict(
        ema_fast=10, ema_slow=30, ema_vol_window=20, hurst_window=30, hurst_max_lag=8, ou_window=30,
        trend_gate_source="adx", target_vol=0.01, circuit_breaker_cooldown=3, calendar_gap_multiple=6.0,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def test_run_daily_step_basic_execution(tmp_path):
    price_data = _gold_like_universe()
    result = run_daily_step(state_dir=str(tmp_path), cfg=_light_cfg(), price_data=price_data)

    assert result["status"] == "execute"
    assert result["equity"] > 0
    assert -1.0 <= result["target_weight"] <= 1.0
    assert os.path.exists(os.path.join(tmp_path, "breaker.json"))
    assert os.path.exists(os.path.join(tmp_path, "dry_run.json"))
    assert os.path.exists(os.path.join(tmp_path, "last_run.json"))


def test_run_daily_step_is_idempotent_for_same_date(tmp_path):
    price_data = _gold_like_universe()
    cfg = _light_cfg()

    first = run_daily_step(state_dir=str(tmp_path), cfg=cfg, price_data=price_data)
    second = run_daily_step(state_dir=str(tmp_path), cfg=cfg, price_data=price_data)

    assert first["status"] == "execute"
    assert second["status"] == "deja_a_jour"


def test_run_daily_step_persists_equity_across_two_days(tmp_path):
    price_data = _gold_like_universe()
    cfg = _light_cfg()

    run_daily_step(state_dir=str(tmp_path), cfg=cfg, price_data=price_data)

    # Jour suivant : une bougie de plus, prix legerement different.
    df2 = price_data[SYMBOL].copy()
    new_row = df2.iloc[[-1]].copy()
    new_index = df2.index[-1] + pd.Timedelta(days=1)
    new_row.index = [new_index]
    new_row["close"] *= 1.01
    price_data_day2 = {SYMBOL: pd.concat([df2, new_row])}

    result_day2 = run_daily_step(state_dir=str(tmp_path), cfg=cfg, price_data=price_data_day2)
    assert result_day2["status"] == "execute"
    # L'equity du jour 2 doit refleter le cash+positions persistes du jour 1,
    # pas repartir du capital initial (preuve que l'etat a bien ete recharge).
    assert result_day2["equity"] != 10_000.0 or result_day2["target_weight"] == 0.0


def test_run_daily_step_forces_flat_when_circuit_breaker_halts(tmp_path):
    # Le coupe-circuit suit l'equity du COMPTE PAPER (cash+positions), pas le
    # prix brut de l'actif : tant qu'aucune position n'est ouverte, un krach
    # du prix ne fait baisser l'equity de personne. Il faut donc d'abord un
    # jour ou le bot entre en position (tendance haussiere), puis un jour ou
    # le krach frappe cette position deja ouverte, pour que le coupe-circuit
    # ait quelque chose a detecter.
    cfg = _light_cfg(halt_drawdown=0.2, resume_drawdown=0.1, circuit_breaker_cooldown=5)
    price_data_day1 = _gold_like_universe()

    day1 = run_daily_step(state_dir=str(tmp_path), cfg=cfg, price_data=price_data_day1)
    assert day1["target_weight"] > 0.0  # precondition : le bot doit etre entre en position

    df2 = price_data_day1[SYMBOL].copy()
    new_row = df2.iloc[[-1]].copy()
    new_index = df2.index[-1] + pd.Timedelta(days=1)
    new_row.index = [new_index]
    new_row["close"] *= 0.5  # krach de 50% sur la position deja ouverte
    new_row["low"] = new_row["close"] * 0.999
    new_row["high"] = new_row["close"] * 1.001
    price_data_day2 = {SYMBOL: pd.concat([df2, new_row])}

    result = run_daily_step(state_dir=str(tmp_path), cfg=cfg, price_data=price_data_day2)

    assert result["trading_allowed"] is False
    assert result["target_weight"] == 0.0


def test_run_daily_step_never_sends_real_orders():
    # Garde-fou explicite : le module ne doit jamais pouvoir declencher de
    # l'execution reelle - verifie qu'aucune des clefs de barriere live
    # (execution.py, etape 6) n'apparait dans le module.
    import inspect

    import crypto_quant.gold_paper_bot as module

    source = inspect.getsource(module)
    assert "dry_run=False" not in source
    assert "CRYPTO_QUANT_CONFIRM_LIVE_TRADING" not in source
