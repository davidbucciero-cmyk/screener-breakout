"""Genere les donnees pour le dashboard du bot de paper trading carry BTC
(crypto_quant/btc_carry_dashboard/index.html, etape 22).

Tout sort de l'etat reel persiste par btc_carry_paper_bot.py (daily_log.csv,
position.json, breaker.json) - aucun chiffre invente. Les stats de backtest
(Sharpe walk-forward etc.) sont les resultats deja documentes dans
README.md, etape 22, repris ici en dur pour contexte (ne proviennent pas
d'un recalcul a chaque generation).

Usage: python -m crypto_quant.btc_carry_dashboard
"""
import json
import math
import os

import pandas as pd

from .btc_carry import BTCCarryConfig, basis_bps, basis_zscore, basis_vol_gate
from .btc_carry_paper_bot import fetch_btc_spot_and_perp

STATE_DIR = os.path.join(os.path.dirname(__file__), "btc_carry_paper_bot_state")
OUT_DIR = os.path.join(os.path.dirname(__file__), "btc_carry_dashboard")

# Resultats de validation deja documentes dans README.md (etape 22 octies) -
# contexte affiche a cote du suivi live, pas recalcule ici.
BACKTEST_CONTEXT = {
    "approach": "Signal calcule sur Kraken (spot+perpetuel) ; jambe spot executee sur OKX (moins cher)",
    "oos_sharpe": 1.298,
    "n_folds": 3,
    "window_days": 721,
    "round_trip_bps": 12.0,
    "vol_threshold_bps": 12.0,
    "no_trade_band": 0.5,
}


def load_daily_log() -> pd.DataFrame:
    path = os.path.join(STATE_DIR, "daily_log.csv")
    if not os.path.exists(path):
        return pd.DataFrame(
            columns=[
                "date", "spot_close", "perp_close", "exec_spot_close", "basis_bps",
                "trading_allowed", "prev_position", "new_position", "turnover", "equity",
            ]
        )
    return pd.read_csv(path, parse_dates=["date"])


def load_json(name: str) -> dict:
    path = os.path.join(STATE_DIR, name)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def compute_trigger_state(current_position: float, config: BTCCarryConfig = BTCCarryConfig()) -> dict:
    """Etat EXACT du declencheur, calcule en direct sur les memes donnees que
    le bot (pas reconstruit depuis le journal, trop clairseme pour une
    fenetre glissante de 30 jours au debut). Deux conditions SEPAREES :

    1. Porte de volatilite : la vol glissante (`vol_gate_window` jours) du
       basis doit depasser `vol_threshold_bps` pour autoriser le trading.
    2. Bande sans-trade : l'exposition cible (-z/clip_z) doit s'ecarter de
       la position courante de plus que `no_trade_band` pour declencher un
       trade - traduit ici en niveaux de basis (bps) via la moyenne/
       ecart-type glissants actuels, pour affichage (le seuil REEL est
       relatif et bouge chaque jour, cette traduction n'est qu'un instantane)."""
    try:
        spot, perp, _ = fetch_btc_spot_and_perp()
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    b = basis_bps(spot, perp)
    z = basis_zscore(spot, perp, config.z_window)
    mean_w = b.rolling(config.z_window, min_periods=10).mean()
    std_w = b.rolling(config.z_window, min_periods=10).std()
    recent_vol = b.rolling(config.vol_gate_window, min_periods=10).std()

    if pd.isna(z.iloc[-1]) or pd.isna(recent_vol.iloc[-1]):
        return {"available": False, "error": "pas assez d'historique pour les fenetres glissantes"}

    vol_gate_open = bool(recent_vol.iloc[-1] > config.vol_threshold_bps)

    z_up = -config.clip_z * (current_position + config.no_trade_band)
    z_down = -config.clip_z * (current_position - config.no_trade_band)
    level_up = float(mean_w.iloc[-1] + z_up * std_w.iloc[-1])
    level_down = float(mean_w.iloc[-1] + z_down * std_w.iloc[-1])

    return {
        "available": True,
        "current_basis_bps": float(b.iloc[-1]),
        "current_zscore": float(z.iloc[-1]),
        "recent_vol_bps": float(recent_vol.iloc[-1]),
        "vol_threshold_bps": config.vol_threshold_bps,
        "vol_gate_open": vol_gate_open,
        "trigger_level_low_bps": min(level_up, level_down),
        "trigger_level_high_bps": max(level_up, level_down),
    }


def build_dashboard_data() -> dict:
    log = load_daily_log()
    breaker = load_json("breaker.json")
    position = load_json("position.json")

    initial_cash = 10_000.0
    current_equity = float(position.get("cash_equity", initial_cash))
    current_position = float(position.get("prev_position", 0.0))

    equity_series = log[["date", "equity"]].copy()
    equity_series["date"] = equity_series["date"].dt.strftime("%Y-%m-%d")
    peak = log["equity"].cummax() if not log.empty else pd.Series(dtype=float)
    drawdown = (log["equity"] - peak) / peak if not log.empty else pd.Series(dtype=float)

    max_equity = float(log["equity"].max()) if not log.empty else current_equity
    current_drawdown = float(drawdown.iloc[-1]) if not drawdown.empty else 0.0
    total_return = current_equity / initial_cash - 1.0

    # Buy & hold BTC (meme capital initial, meme date de depart) : reference
    # passive au prix spot Kraken (la meme serie que celle utilisee pour le
    # signal partout ailleurs sur ce dashboard) - achete une fois au premier
    # jour suivi, jamais retouche.
    first_spot = float(log["spot_close"].iloc[0]) if not log.empty else None
    buy_hold_series = (log["spot_close"] / first_spot * initial_cash) if first_spot else pd.Series(dtype=float)
    current_buy_hold = float(buy_hold_series.iloc[-1]) if len(buy_hold_series) else initial_cash
    buy_hold_return = current_buy_hold / initial_cash - 1.0

    rows = []
    for idx, r in log.iterrows():
        rows.append(
            {
                "date": r["date"].strftime("%Y-%m-%d"),
                "spot_close": float(r["spot_close"]),
                "perp_close": float(r["perp_close"]),
                "exec_spot_close": float(r["exec_spot_close"]),
                "basis_bps": float(r["basis_bps"]),
                "trading_allowed": bool(r["trading_allowed"]),
                "prev_position": float(r["prev_position"]),
                "new_position": float(r["new_position"]),
                "turnover": float(r["turnover"]),
                "equity": float(r["equity"]),
                "buy_hold_equity": float(buy_hold_series.loc[idx]),
            }
        )

    data = {
        "generated_at": pd.Timestamp.now("UTC").isoformat(),
        "initial_cash": initial_cash,
        "current_equity": current_equity,
        "max_equity": max_equity,
        "current_drawdown": current_drawdown,
        "total_return": total_return,
        "current_position": current_position,
        "days_tracked": len(log),
        "last_date": rows[-1]["date"] if rows else None,
        "circuit_breaker": {
            "halted": bool(breaker.get("halted", False)),
            "halt_drawdown": breaker.get("halt_drawdown"),
            "resume_drawdown": breaker.get("resume_drawdown"),
        },
        "current_buy_hold": current_buy_hold,
        "buy_hold_return": buy_hold_return,
        "rows": rows,
        "backtest_context": BACKTEST_CONTEXT,
        "trigger_state": compute_trigger_state(current_position),
    }
    return data


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    data = build_dashboard_data()
    out_path = os.path.join(OUT_DIR, "data.json")
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Ecrit {out_path} ({data['days_tracked']} jours, equity={data['current_equity']:.2f})")
