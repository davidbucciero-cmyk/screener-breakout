"""Bot de paper trading autonome sur l'or (etape 18).

Concu pour tourner UNE FOIS PAR JOUR (bougie journaliere, coherent avec
tout le pipeline de recherche), declenche par une Routine planifiee (cf.
README) plutot que par une boucle continue.

Reutilise integralement les briques deja validees plutot que d'en
reconstruire de nouvelles :
- backtest.compute_live_weights : meme pipeline signal -> score composite
  -> poids que le backtester (etapes 2 a 5), avec la config recalibree a
  l'etape 17 bis (ADX, fenetres CTA 100/250 jours - la seule qui a montre
  un resultat OOS honnete sur l'or).
- risk.DrawdownCircuitBreaker + execution.save/load_breaker_state (etape
  4/6) : coupe-circuit de drawdown, persiste entre deux executions.
- execution.LiveExecutor en mode simulation + save/load_dry_run_state
  (etape 6/18) : PAPER TRADING UNIQUEMENT - aucun ordre reel n'est jamais
  envoye ici (pas de cles API, pas de client d'exchange reel). Passer a du
  reel demanderait de reprendre LiveExecutor en mode reel directement, avec
  ses 3 barrieres de securite deja en place (etape 6) - PAS ce module.

Etat persiste dans des fichiers JSON qui doivent etre COMMIT/PUSH par
l'appelant (la Routine) apres chaque execution : le conteneur cloud qui
execute ce script est recree a chaque declenchement (cf. la doc de
l'environnement), seul ce qui est commit/push survit d'un jour a l'autre.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

import pandas as pd

from .backtest import BacktestConfig, compute_live_weights
from .execution import LiveExecutor, load_breaker_state, load_dry_run_state, save_breaker_state, save_dry_run_state
from .risk import DrawdownCircuitBreaker

SYMBOL = "GOLD"
YFINANCE_TICKER = "GC=F"

# Config recalibree a l'etape 17 bis : ADX, fenetres ~1 an (100/250 jours),
# la seule qui ait montre un resultat OOS honnete sur l'or (Sharpe 0.30,
# p=0.24-0.30 - directionnellement interessant, jamais prouve a 5%).
GOLD_CONFIG = BacktestConfig(
    ema_fast=100,
    ema_slow=250,
    ema_vol_window=63,
    hurst_window=250,
    ou_window=250,
    trend_gate_source="adx",
    target_vol=0.01,
    circuit_breaker_cooldown=5,
    calendar_gap_multiple=6.0,
)

DEFAULT_STATE_DIR = os.path.join(os.path.dirname(__file__), "gold_paper_bot_state")
INITIAL_PAPER_CASH = 10_000.0


def fetch_gold_history(period: str = "3y") -> pd.DataFrame:
    """Recupere l'historique OHLC de l'or (futures GC=F, yfinance).

    period="3y" laisse largement assez de marge pour le warm-up (ema_slow
    /hurst_window/ou_window = 250 jours OUVRES, ~1 an) tout en restant une
    requete legere.
    """
    import yfinance as yf

    df = yf.download(YFINANCE_TICKER, period=period, interval="1d", progress=False)
    if df.empty:
        raise RuntimeError(f"yfinance n'a renvoye aucune donnee pour {YFINANCE_TICKER}")

    df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close", "Volume"]]
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index.name = "datetime"
    return df.sort_index()


def _last_run_path(state_dir: str) -> str:
    return os.path.join(state_dir, "last_run.json")


def _load_last_run_date(state_dir: str) -> Optional[str]:
    path = _last_run_path(state_dir)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f).get("last_run_date")


def _save_last_run_date(state_dir: str, date_str: str) -> None:
    with open(_last_run_path(state_dir), "w") as f:
        json.dump({"last_run_date": date_str}, f)


def run_daily_step(
    state_dir: str = DEFAULT_STATE_DIR,
    cfg: BacktestConfig = GOLD_CONFIG,
    price_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> dict:
    """Execute UNE iteration du bot : recupere le prix, calcule la decision,
    simule l'ordre (paper trading), persiste l'etat. A appeler une fois par
    jour (cf. docstring module) - idempotent si deja execute pour la
    derniere bougie disponible (utile si la Routine se redeclenche par
    erreur le meme jour).

    price_data : injection pour les tests (evite un vrai appel reseau
    yfinance) - None (defaut) declenche fetch_gold_history() normalement.

    Renvoie un dict resumant l'execution (toujours serialisable en JSON),
    jamais d'exception pour un cas "rien de neuf" - seulement pour un vrai
    probleme (donnees introuvables, pipeline en echec).
    """
    os.makedirs(state_dir, exist_ok=True)

    if price_data is None:
        price_data = {SYMBOL: fetch_gold_history()}
    df = price_data[SYMBOL]
    last_date = df.index[-1]
    last_date_str = last_date.date().isoformat()

    if _load_last_run_date(state_dir) == last_date_str:
        return {"status": "deja_a_jour", "date": last_date_str}

    latest_close = float(df["close"].iloc[-1])

    breaker = load_breaker_state(
        os.path.join(state_dir, "breaker.json"),
        default=DrawdownCircuitBreaker(
            halt_drawdown=cfg.halt_drawdown, resume_drawdown=cfg.resume_drawdown, cooldown_periods=cfg.circuit_breaker_cooldown
        ),
    )
    executor = LiveExecutor(dry_run=True, exchange_client=object(), initial_dry_run_cash=INITIAL_PAPER_CASH)
    load_dry_run_state(executor, os.path.join(state_dir, "dry_run.json"))

    current_equity = executor.dry_run_cash + executor.dry_run_holdings.get(SYMBOL, 0.0) * latest_close
    allowed = breaker.step(current_equity)

    target_weight = 0.0
    if allowed:
        weights = compute_live_weights(price_data, cfg)
        target_weight = float(weights.get(SYMBOL, 0.0))

    orders = executor.compute_rebalance_orders(
        current_holdings=executor.dry_run_holdings,
        target_weights={SYMBOL: target_weight},
        prices={SYMBOL: latest_close},
        total_equity=current_equity,
    )
    executed = executor.execute_orders(orders, prices={SYMBOL: latest_close})

    final_equity = executor.dry_run_cash + executor.dry_run_holdings.get(SYMBOL, 0.0) * latest_close

    save_breaker_state(breaker, os.path.join(state_dir, "breaker.json"))
    save_dry_run_state(executor, os.path.join(state_dir, "dry_run.json"))
    _save_last_run_date(state_dir, last_date_str)

    return {
        "status": "execute",
        "date": last_date_str,
        "close": latest_close,
        "trading_allowed": allowed,
        "target_weight": target_weight,
        "orders": executed,
        "equity": final_equity,
    }


if __name__ == "__main__":
    import sys

    result = run_daily_step()
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0)
