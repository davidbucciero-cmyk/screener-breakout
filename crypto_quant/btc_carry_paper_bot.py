"""Bot de paper trading autonome sur le carry BTC (etape 22 quater).

Meme philosophie que `gold_paper_bot.py` (etape 18) : une iteration par
jour, declenchee par une Routine planifiee, PAPER TRADING UNIQUEMENT
(aucun ordre reel, aucune cle API). Etat persiste en JSON, a
commit/push par l'appelant pour survivre au conteneur ephemere.

Difference structurelle avec le bot or : ici la strategie est un SPREAD
a deux jambes (long spot BTC / short perpetuel BTC ou l'inverse selon
le signe du basis), pas une position longue sur un seul actif - `
LiveExecutor` (etape 6) ne modelise que des positions longues sur un
symbole unique, donc ce bot ne l'utilise PAS : il reimplemente le meme
pas-a-pas que `btc_carry.carry_spread_equity` (etapes 22/22 ter), mais
en version INCREMENTALE (un seul jour a la fois, etat persiste) plutot
qu'en un seul passage vectorise sur tout l'historique.

Reutilise quand meme : `risk.DrawdownCircuitBreaker` +
`execution.save/load_breaker_state` (meme coupe-circuit, meme
persistance que le bot or) et les fonctions de signal de `btc_carry.py`
(`basis_zscore`, `basis_vol_gate`) deja testees.

Limites assumees (detaillees dans README.md, etape 22) : fenetre reelle
~2 ans (plafond Kraken), strategie sensible au cout de transaction,
necessite une infra de vente a decouvert pour un passage au reel (Kraken
Futures la supporte nativement, contrairement a l'or - mais ce module
reste PAPER, aucune execution reelle n'est jamais tentee ici).
"""
from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd

from .btc_carry import BTCCarryConfig, basis_vol_gate, basis_zscore
from .execution import load_breaker_state, save_breaker_state
from .risk import DrawdownCircuitBreaker

DEFAULT_STATE_DIR = os.path.join(os.path.dirname(__file__), "btc_carry_paper_bot_state")
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data_cache_btc_carry")
INITIAL_PAPER_CASH = 10_000.0
DEFAULT_CONFIG = BTCCarryConfig()

# history_days : assez pour le warm-up du z-score (z_window=30, min_periods=10)
# et de la porte de vol (vol_gate_window=20), avec large marge.
HISTORY_DAYS = 180


def fetch_btc_spot_and_perp(history_days: int = HISTORY_DAYS, cache_dir: str = DEFAULT_CACHE_DIR) -> tuple[pd.Series, pd.Series]:
    """Recupere spot Kraken (BTC/USD) et perpetuel Kraken Futures
    (BTC/USD:BTC, PI_XBTUSD), memes deux jambes que celles validees en
    walk-forward a l'etape 22 - meme exchange pour les deux cotes (cf.
    docstring de btc_carry.py sur le bruit inter-exchange trouve avec
    Binance.US+Deribit).

    Fix reseau necessaire dans CET environnement proxifie, applique ICI
    (au point d'appel, pas dans data.py:build_exchange - meme convention
    deja documentee au README pour le spot Kraken, etape 7) :
    `exchange.session.trust_env = True`.
    """
    import ccxt

    from .data import CCXTDataFeed

    kraken_spot = ccxt.kraken({"enableRateLimit": True, "timeout": 20000})
    kraken_spot.session.trust_env = True
    spot_feed = CCXTDataFeed(exchange_id="kraken", cache_dir=cache_dir, exchange_client=kraken_spot)
    spot_df = spot_feed.get_history("BTC/USD", "1d", history_days=history_days)

    kraken_fut = ccxt.krakenfutures({"enableRateLimit": True, "timeout": 20000})
    kraken_fut.session.trust_env = True
    perp_feed = CCXTDataFeed(exchange_id="krakenfutures", cache_dir=cache_dir, exchange_client=kraken_fut)
    perp_df = perp_feed.get_history("BTC/USD:BTC", "1d", history_days=history_days)

    spot = spot_df["close"].groupby(spot_df.index.floor("D")).last()
    perp = perp_df["close"].groupby(perp_df.index.floor("D")).last()
    common = spot.index.intersection(perp.index).sort_values()
    if len(common) == 0:
        raise RuntimeError("Aucun jour commun entre le spot et le perpetuel Kraken recuperes")
    return spot.reindex(common), perp.reindex(common)


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


def _position_state_path(state_dir: str) -> str:
    return os.path.join(state_dir, "position.json")


def _load_position_state(state_dir: str) -> dict:
    path = _position_state_path(state_dir)
    if not os.path.exists(path):
        return {"prev_position": 0.0, "cash_equity": INITIAL_PAPER_CASH}
    with open(path) as f:
        return json.load(f)


def _save_position_state(state_dir: str, prev_position: float, cash_equity: float) -> None:
    with open(_position_state_path(state_dir), "w") as f:
        json.dump({"prev_position": prev_position, "cash_equity": cash_equity}, f)


def _daily_log_path(state_dir: str) -> str:
    return os.path.join(state_dir, "daily_log.csv")


def _append_daily_log(state_dir: str, row: dict) -> None:
    """Journal append-only (une ligne par jour execute) - `position.json`
    n'est qu'un instantane ecrase a chaque appel, ce fichier est le seul
    endroit ou suivre l'historique de l'equity paper dans le temps."""
    path = _daily_log_path(state_dir)
    df_row = pd.DataFrame([row])
    if os.path.exists(path):
        df_row.to_csv(path, mode="a", header=False, index=False)
    else:
        df_row.to_csv(path, mode="w", header=True, index=False)


def run_daily_step(
    state_dir: str = DEFAULT_STATE_DIR,
    config: BTCCarryConfig = DEFAULT_CONFIG,
    spot: Optional[pd.Series] = None,
    perp: Optional[pd.Series] = None,
) -> dict:
    """Execute UNE iteration du bot : recupere spot+perpetuel, met a jour
    l'equity avec le rendement realise de la position DEJA DETENUE
    (decidee hier), decide la nouvelle position cible (basis d'aujourd'hui,
    bande sans-trade contre la position actuelle), persiste l'etat.

    `spot`/`perp` : injection pour les tests (evite un vrai appel reseau) -
    None (defaut) declenche fetch_btc_spot_and_perp() normalement.

    Idempotent si deja execute pour la derniere date disponible (meme
    convention que gold_paper_bot.run_daily_step).
    """
    os.makedirs(state_dir, exist_ok=True)

    if spot is None or perp is None:
        spot, perp = fetch_btc_spot_and_perp()

    last_date = spot.index[-1]
    last_date_str = last_date.date().isoformat()

    if _load_last_run_date(state_dir) == last_date_str:
        return {"status": "deja_a_jour", "date": last_date_str}

    state = _load_position_state(state_dir)
    prev_position = float(state["prev_position"])
    cash_equity = float(state["cash_equity"])

    # Rendement du spread REALISE depuis la derniere cloture (applique a la
    # position DEJA DETENUE, decidee lors de l'execution precedente - aucune
    # fuite vers le futur, la position d'aujourd'hui n'est decidee qu'apres).
    spread_return_today = float(perp.pct_change().iloc[-1] - spot.pct_change().iloc[-1])
    if not pd.notna(spread_return_today):
        spread_return_today = 0.0
    equity_after_move = cash_equity * (1 + prev_position * spread_return_today)

    breaker = load_breaker_state(
        os.path.join(state_dir, "breaker.json"),
        # BTCCarryConfig n'a pas de champ dedie au coupe-circuit (le spread
        # est deja borne par construction, contrairement a une position
        # directionnelle) - memes seuils que GOLD_CONFIG par defaut.
        default=DrawdownCircuitBreaker(halt_drawdown=0.20, resume_drawdown=0.10, cooldown_periods=5),
    )
    allowed = breaker.step(equity_after_move)

    z = basis_zscore(spot, perp, config.z_window)
    gate = (
        basis_vol_gate(spot, perp, config.vol_threshold_bps, config.vol_gate_window)
        if config.vol_threshold_bps > 0
        else pd.Series(1.0, index=spot.index)
    )
    raw_target = float((-z.clip(-config.clip_z, config.clip_z) / config.clip_z).clip(-1, 1).iloc[-1] * gate.iloc[-1])
    desired_position = raw_target if allowed else 0.0

    if abs(desired_position - prev_position) > config.no_trade_band:
        new_position = desired_position
    else:
        new_position = prev_position

    turnover = abs(new_position - prev_position)
    cost = turnover * config.cost_bps / 10_000 * 2
    final_equity = equity_after_move * (1 - cost)

    _save_position_state(state_dir, new_position, final_equity)
    save_breaker_state(breaker, os.path.join(state_dir, "breaker.json"))
    _save_last_run_date(state_dir, last_date_str)
    _append_daily_log(
        state_dir,
        {
            "date": last_date_str,
            "spot_close": float(spot.iloc[-1]),
            "perp_close": float(perp.iloc[-1]),
            "basis_bps": float((perp.iloc[-1] / spot.iloc[-1] - 1) * 10000),
            "trading_allowed": allowed,
            "prev_position": prev_position,
            "new_position": new_position,
            "turnover": turnover,
            "equity": final_equity,
        },
    )

    return {
        "status": "execute",
        "date": last_date_str,
        "spot_close": float(spot.iloc[-1]),
        "perp_close": float(perp.iloc[-1]),
        "trading_allowed": allowed,
        "prev_position": prev_position,
        "new_position": new_position,
        "turnover": turnover,
        "equity": final_equity,
    }


if __name__ == "__main__":
    import sys

    result = run_daily_step()
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0)
