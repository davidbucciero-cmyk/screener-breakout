"""Systeme de breakout Donchian avec filtre de tendance (etape 19).

Systeme CTA classique (lignee "Turtle Trading" : canal de Donchian +
filtre de moyenne mobile longue), propose par l'utilisateur comme
alternative aux signaux EMA/Hurst/ADX deja en place (backtest.py,
discrete_trading.py). Implemente en PARALLELE de discrete_trading.py
plutot que par extension : la logique d'entree/sortie est fondamentalement
differente (canal de prix, pas score composite Hurst/EMA/OU) - seule la
gestion de trade (stop ATR, sizing par risque, coupe-circuit) est
reutilisee dans l'esprit, pas le code (les deux moteurs restent
independants pour ne pas fragiliser discrete_trading.py deja valide).

Regles (telles que proposees, cf. capture d'ecran) :
- Signal calcule a la CLOTURE de chaque bougie journaliere.
- Achat : cloture au-dessus de la MM 200 jours ET au-dessus du plus haut
  des 20 jours PRECEDENTS (canal exclut la bougie courante - sinon le
  signal se "voit" lui-meme et le breakout ne signifie plus rien).
- Entree a l'OUVERTURE de la bougie SUIVANTE (pas a la meme cloture qui
  vient de generer le signal) - plus realiste, differe deliberement de
  discrete_trading.py qui entre a la cloture du jour du signal (latence
  zero entre signal et execution, optimiste).
- Stop initial a 2 x ATR(20) de l'entree.
- Sortie : cloture sous le plus bas des 10 jours precedents (canal de
  sortie, independant du stop) - ou coupe-circuit.
- Sizing par risque (risk_per_trade / distance au stop en %), une seule
  position a la fois, pas de pyramidage.

Limite assumee : LONG-ONLY (coherent avec le reste du projet - spot, pas
de vente a decouvert, cf. portfolio.py docstring). La regle symetrique
"vente a decouvert" proposee n'est PAS implementee ici - la tester
demanderait une infra de short (marge, emprunt de titres) que ce projet
n'a jamais construite.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .risk import DrawdownCircuitBreaker, atr


@dataclass
class DonchianConfig:
    entry_window: int = 20  # breakout : cloture au-dessus du plus haut des N jours precedents
    trend_ma_window: int = 200  # filtre : cloture au-dessus de la moyenne mobile N jours
    exit_window: int = 10  # sortie : cloture sous le plus bas des N jours precedents
    atr_period: int = 20
    atr_stop_multiple: float = 2.0
    risk_per_trade: float = 0.0025  # borne basse de la fourchette proposee (0.25%-0.5%)
    max_position_fraction: float = 1.0
    calendar_gap_multiple: float = 3.0  # seuil de detection de trou de calendrier (etape 13 bis/14) - 6.0 pour marches traditionnels (week-ends/jours feries)
    transaction_cost_bps: float = 15.0
    initial_capital: float = 10_000.0
    halt_drawdown: float = 0.20
    resume_drawdown: float = 0.10
    circuit_breaker_cooldown: int = 24


@dataclass
class OpenTrade:
    symbol: str
    entry_date: object
    entry_price: float
    units: float
    stop: float


@dataclass
class ClosedTrade:
    symbol: str
    entry_date: object
    entry_price: float
    exit_date: object
    exit_price: float
    exit_reason: str  # "stop", "channel" ou "coupe-circuit"


@dataclass
class DonchianResult:
    equity: pd.Series
    weights_history: pd.DataFrame
    closed_trades: List[ClosedTrade]
    trading_allowed_history: pd.Series


def _compute_signals(df: pd.DataFrame, cfg: DonchianConfig) -> pd.DataFrame:
    if "high" not in df.columns or "low" not in df.columns:
        raise ValueError("run_donchian_backtest necessite les colonnes 'high'/'low' (ATR pour le stop).")
    if "open" not in df.columns:
        raise ValueError("run_donchian_backtest necessite la colonne 'open' (entree a l'ouverture du jour suivant).")

    close = df["close"]
    trend_ma = close.rolling(cfg.trend_ma_window).mean()
    prior_high = close.shift(1).rolling(cfg.entry_window).max()
    prior_low_exit = close.shift(1).rolling(cfg.exit_window).min()
    atr_series = atr(df, window=cfg.atr_period)

    entry_signal = (close > trend_ma) & (close > prior_high)

    return pd.DataFrame(
        {
            "open": df["open"],
            "close": close,
            "high": df["high"],
            "low": df["low"],
            "entry_signal": entry_signal,
            "exit_level": prior_low_exit,
            "atr": atr_series,
        }
    )


def run_donchian_backtest(price_data: Dict[str, pd.DataFrame], cfg: DonchianConfig) -> DonchianResult:
    """Simule le systeme de breakout Donchian sur l'historique fourni.

    price_data : {symbol: DataFrame avec au moins open/high/low/close},
    meme convention que backtest.py/discrete_trading.py.
    """
    from .backtest import _assert_no_calendar_gaps  # meme garde-fou anti-trou de calendrier (etape 13 bis)

    symbols = list(price_data.keys())

    raw_common_index = None
    for df in price_data.values():
        raw_common_index = df.index if raw_common_index is None else raw_common_index.intersection(df.index)
    raw_common_index = raw_common_index.sort_values()
    _assert_no_calendar_gaps(raw_common_index, max_gap_multiple=cfg.calendar_gap_multiple)

    per_symbol = {symbol: _compute_signals(df, cfg) for symbol, df in price_data.items()}

    required_cols = ["open", "close", "high", "low", "exit_level", "atr"]
    common_index = None
    for df in per_symbol.values():
        idx = df.dropna(subset=required_cols).index
        common_index = idx if common_index is None else common_index.intersection(idx)
    aligned = {symbol: df.loc[common_index] for symbol, df in per_symbol.items()}

    n = len(common_index)
    if n < 2:
        raise ValueError("Pas assez de donnees alignees apres warm-up pour lancer le backtest Donchian")

    breaker = DrawdownCircuitBreaker(cfg.halt_drawdown, cfg.resume_drawdown, cfg.circuit_breaker_cooldown)

    cash = cfg.initial_capital
    open_trades: Dict[str, OpenTrade] = {}
    closed_trades: List[ClosedTrade] = []
    # Decidees a la cloture du jour t (canal casse), executees a l'ouverture
    # du jour t+1 - cf. docstring module.
    pending_entries: Dict[str, float] = {}

    equity = np.empty(n)
    weights_records = np.zeros((n, len(symbols)))
    trading_allowed = np.ones(n, dtype=bool)

    def _positions_value(t: int) -> float:
        return sum(tr.units * aligned[tr.symbol]["close"].iloc[t] for tr in open_trades.values())

    prev_equity = cfg.initial_capital

    for t in range(n):
        allowed = breaker.step(prev_equity)
        trading_allowed[t] = allowed

        # --- 0. Executer a l'OUVERTURE du jour les entrees decidees hier ---
        entries_to_execute = pending_entries
        pending_entries = {}
        if allowed and entries_to_execute:
            equity_snapshot = cash + _positions_value(t)
            committed = (
                sum(tr.units * aligned[tr.symbol]["close"].iloc[t] for tr in open_trades.values()) / equity_snapshot
                if equity_snapshot > 0
                else 0.0
            )
            available = max(0.0, cfg.max_position_fraction - committed)
            for symbol, stop_distance in entries_to_execute.items():
                if available <= 0:
                    break
                if symbol in open_trades:
                    continue
                row = aligned[symbol].iloc[t]
                entry_price = row["open"]
                if not np.isfinite(entry_price) or entry_price <= 0 or stop_distance <= 0:
                    continue
                stop_pct = stop_distance / entry_price
                weight = min(cfg.risk_per_trade / stop_pct, available, cfg.max_position_fraction)
                if weight <= 0:
                    continue
                cost_rate = cfg.transaction_cost_bps / 10_000
                notional = weight * equity_snapshot / (1 + cost_rate)
                units = notional / entry_price
                cost = notional * cost_rate
                cash -= notional + cost
                open_trades[symbol] = OpenTrade(
                    symbol=symbol,
                    entry_date=common_index[t],
                    entry_price=entry_price,
                    units=units,
                    stop=entry_price - stop_distance,
                )
                available -= weight

        # --- 1. Gerer les trades ouverts : stop (bas du jour) puis sortie de canal (cloture) ---
        for symbol in list(open_trades.keys()):
            trade = open_trades[symbol]
            row = aligned[symbol].iloc[t]

            if row["low"] <= trade.stop:
                exit_price = trade.stop
                notional = trade.units * exit_price
                cash += notional - notional * cfg.transaction_cost_bps / 10_000
                closed_trades.append(
                    ClosedTrade(symbol, trade.entry_date, trade.entry_price, common_index[t], exit_price, "stop")
                )
                del open_trades[symbol]
                continue

            if not allowed or row["close"] < row["exit_level"]:
                exit_price = row["close"]
                notional = trade.units * exit_price
                cash += notional - notional * cfg.transaction_cost_bps / 10_000
                reason = "coupe-circuit" if not allowed else "channel"
                closed_trades.append(
                    ClosedTrade(symbol, trade.entry_date, trade.entry_price, common_index[t], exit_price, reason)
                )
                del open_trades[symbol]

        # --- 2. Decider les entrees de DEMAIN a partir du signal de cloture d'AUJOURD'HUI ---
        if allowed:
            for symbol in symbols:
                if symbol in open_trades:
                    continue
                row = aligned[symbol].iloc[t]
                if not bool(row["entry_signal"]) or not np.isfinite(row["atr"]) or row["atr"] <= 0:
                    continue
                pending_entries[symbol] = cfg.atr_stop_multiple * row["atr"]

        current_equity = cash + _positions_value(t)
        equity[t] = current_equity
        prev_equity = current_equity

        for j, symbol in enumerate(symbols):
            if symbol in open_trades:
                tr = open_trades[symbol]
                weights_records[t, j] = tr.units * aligned[symbol]["close"].iloc[t] / current_equity if current_equity > 0 else 0.0

    return DonchianResult(
        equity=pd.Series(equity, index=common_index, name="equity"),
        weights_history=pd.DataFrame(weights_records, index=common_index, columns=symbols),
        closed_trades=closed_trades,
        trading_allowed_history=pd.Series(trading_allowed, index=common_index, name="trading_allowed"),
    )
