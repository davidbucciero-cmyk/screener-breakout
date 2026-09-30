"""Moteur a trades discrets (entree / stop-loss / breakeven / trailing),
en PARALLELE du backtester a poids continus (backtest.py) - pas un
remplacement.

Difference fondamentale avec backtest.py : la-bas, chaque actif detient un
poids CONTINU, recalcule et rebalance a chaque bougie selon le score
composite (cf. portfolio.composite_score). Ici, chaque actif est soit FLAT
soit dans un TRADE UNIQUE avec un prix d'entree, une taille fixee a
l'entree, et un stop qui ne peut que monter (jamais redescendre) une fois
le seuil de breakeven atteint - le modele "money management" classique du
trading discretionnaire/algorithmique par trade.

Long-only (coherent avec le reste du projet - spot, pas de vente a
decouvert, cf. portfolio.py) : un trade est toujours LONG, jamais short.

Reutilise les memes briques statistiques que backtest.py (Hurst/ADX, EMA
trend + skip, OU mean-reversion, overlay de regime BTC) pour la DIRECTION
du trade (entrer ou non), et risk.atr/atr_stop_loss_price (etape 4, jamais
cable dans backtest.py car le modele a poids continus n'a pas de notion de
stop par position) pour le sizing et la gestion de sortie.

Filtre de session horaire (optionnel) : mecanisme teste et fonctionnel,
mais SANS EFFET REEL sur des bougies JOURNALIERES (un seul horodatage par
jour, toujours a la meme heure convention - minuit UTC) - il ne devient un
vrai filtre que sur des donnees intraday (ex: horaire). Voir avertissement
dans _session_filter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .portfolio import composite_score
from .risk import DrawdownCircuitBreaker, atr
from .signals import (
    adx,
    adx_trend_gate,
    ema_trend_signal,
    market_regime_signal,
    ou_meanreversion_signal,
    rolling_hurst,
)


@dataclass
class DiscreteTradeConfig:
    # Signaux d'entree/sortie (memes significations que BacktestConfig)
    ema_fast: int = 12
    ema_slow: int = 48
    ema_vol_window: int = 48
    ema_skip: int = 0
    trend_gate_source: str = "hurst"  # "hurst" ou "adx" (etape 15 - ADX bat Hurst en walk-forward sur BTC/ETH)
    hurst_window: int = 100
    hurst_min_lag: int = 2
    hurst_max_lag: int = 20
    adx_period: int = 14
    adx_threshold: float = 20.0
    adx_cap: float = 40.0
    ou_window: int = 100
    ou_significance_t: float = 2.0

    # Money management par trade (nouveau - pas dans backtest.py)
    atr_period: int = 14
    atr_stop_multiple: float = 2.0  # distance initiale du stop = atr_stop_multiple * ATR
    breakeven_r_multiple: float = 1.0  # stop -> prix d'entree des que le gain latent = ce multiple du risque initial
    trailing_atr_multiple: float = 2.0  # apres breakeven, stop suiveur = plus_haut_depuis_entree - trailing_atr_multiple * ATR
    risk_per_trade: float = 0.01  # fraction de l'equity perdue si le stop INITIAL est touche
    max_position_fraction: float = 1.0  # plafond de poids total investi (spot, pas de levier)

    # Filtre de session horaire (heures UTC, bornes [start, end) ) - None desactive.
    # AVERTISSEMENT : sans effet reel sur des bougies journalieres, voir docstring module.
    session_start_hour: Optional[int] = None
    session_end_hour: Optional[int] = None

    # Overlay de regime de marche (Starkiller Capital - cf. backtest.py)
    market_regime_symbol: Optional[str] = None
    market_regime_fast: int = 5
    market_regime_slow: int = 50

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
    initial_stop: float
    weight_at_entry: float
    stop: float = field(init=False)
    breakeven_triggered: bool = field(default=False, init=False)
    highest_close: float = field(init=False)

    def __post_init__(self) -> None:
        self.stop = self.initial_stop
        self.highest_close = self.entry_price


@dataclass
class ClosedTrade:
    symbol: str
    entry_date: object
    entry_price: float
    exit_date: object
    exit_price: float
    exit_reason: str  # "stop" ou "signal"
    weight_at_entry: float


@dataclass
class DiscreteTradeResult:
    equity: pd.Series
    weights_history: pd.DataFrame
    closed_trades: List[ClosedTrade]
    trading_allowed_history: pd.Series


def _session_filter(index: pd.DatetimeIndex, start_hour: Optional[int], end_hour: Optional[int]) -> pd.Series:
    """True si l'heure UTC de la bougie tombe dans [start_hour, end_hour).

    None pour l'un ou l'autre desactive le filtre (toujours True). Gere une
    fenetre qui traverse minuit (start_hour > end_hour, ex: 22h->6h).
    """
    if start_hour is None or end_hour is None:
        return pd.Series(True, index=index)

    hours = index.hour
    if start_hour <= end_hour:
        allowed = (hours >= start_hour) & (hours < end_hour)
    else:
        allowed = (hours >= start_hour) | (hours < end_hour)
    return pd.Series(allowed, index=index)


def _compute_entry_signals(df: pd.DataFrame, cfg: DiscreteTradeConfig) -> pd.DataFrame:
    """Score composite + ATR pour un actif - memes signaux que backtest.py
    (reutilises tels quels), plus l'ATR pour le money management par trade.

    'high'/'low' sont TOUJOURS requises ici (contrairement a backtest.py,
    ou elles ne servaient qu'a l'ADX optionnel) : l'ATR, necessaire au
    stop-loss/trailing de ce moteur, en depend systematiquement.
    """
    if "high" not in df.columns or "low" not in df.columns:
        raise ValueError(
            "run_discrete_trade_backtest necessite les colonnes 'high' et 'low' dans price_data "
            "(requises par l'ATR pour le stop-loss/trailing) - absentes ici (donnees close-only)."
        )

    hurst = rolling_hurst(df["close"], window=cfg.hurst_window, min_lag=cfg.hurst_min_lag, max_lag=cfg.hurst_max_lag)
    ema_trend = ema_trend_signal(df["close"], fast=cfg.ema_fast, slow=cfg.ema_slow, vol_window=cfg.ema_vol_window, skip=cfg.ema_skip)
    ou_signal = ou_meanreversion_signal(df["close"], window=cfg.ou_window, significance_t=cfg.ou_significance_t)["signal"]
    atr_series = atr(df, window=cfg.atr_period)

    trend_gate = None
    if cfg.trend_gate_source == "adx":
        adx_series = adx(df["high"], df["low"], df["close"], period=cfg.adx_period)
        trend_gate = adx_trend_gate(adx_series, threshold=cfg.adx_threshold, cap=cfg.adx_cap)
    elif cfg.trend_gate_source != "hurst":
        raise ValueError(f"trend_gate_source invalide : {cfg.trend_gate_source!r}")

    comp = composite_score(hurst, ema_trend, ou_signal, trend_gate=trend_gate)

    return pd.DataFrame(
        {
            "close": df["close"],
            "high": df["high"],
            "low": df["low"],
            "raw_score": comp["raw_score"],
            "atr": atr_series,
        }
    )


def run_discrete_trade_backtest(
    price_data: Dict[str, pd.DataFrame], cfg: DiscreteTradeConfig
) -> DiscreteTradeResult:
    """Simule le moteur a trades discrets sur l'historique fourni.

    price_data : {symbol: DataFrame avec au moins close/high/low}, meme
    convention que backtest.py.
    """
    from .backtest import _assert_no_calendar_gaps  # meme garde-fou anti-trou de calendrier (etape 13 bis)

    symbols = list(price_data.keys())

    raw_common_index = None
    for df in price_data.values():
        raw_common_index = df.index if raw_common_index is None else raw_common_index.intersection(df.index)
    raw_common_index = raw_common_index.sort_values()
    _assert_no_calendar_gaps(raw_common_index)

    per_symbol = {symbol: _compute_entry_signals(df, cfg) for symbol, df in price_data.items()}

    required_cols = ["close", "high", "low", "raw_score", "atr"]
    common_index = None
    for df in per_symbol.values():
        idx = df.dropna(subset=required_cols).index
        common_index = idx if common_index is None else common_index.intersection(idx)
    aligned = {symbol: df.loc[common_index] for symbol, df in per_symbol.items()}

    n = len(common_index)
    if n < 2:
        raise ValueError("Pas assez de donnees alignees apres warm-up pour lancer un backtest a trades discrets")

    regime_gate = None
    if cfg.market_regime_symbol is not None:
        if cfg.market_regime_symbol not in price_data:
            raise ValueError(f"market_regime_symbol={cfg.market_regime_symbol!r} absent de l'univers fourni")
        ref_close = price_data[cfg.market_regime_symbol]["close"].reindex(common_index)
        regime_gate = market_regime_signal(ref_close, fast=cfg.market_regime_fast, slow=cfg.market_regime_slow)

    session_ok = _session_filter(common_index, cfg.session_start_hour, cfg.session_end_hour)

    breaker = DrawdownCircuitBreaker(cfg.halt_drawdown, cfg.resume_drawdown, cfg.circuit_breaker_cooldown)

    cash = cfg.initial_capital
    open_trades: Dict[str, OpenTrade] = {}
    closed_trades: List[ClosedTrade] = []

    equity = np.empty(n)
    weights_records = np.zeros((n, len(symbols)))
    trading_allowed = np.ones(n, dtype=bool)

    def _positions_value(t: int) -> float:
        return sum(tr.units * aligned[tr.symbol]["close"].iloc[t] for tr in open_trades.values())

    prev_equity = cfg.initial_capital

    for t in range(n):
        allowed = breaker.step(prev_equity)
        trading_allowed[t] = allowed
        regime_ok = regime_gate is None or bool(regime_gate.iloc[t])

        # --- 1. Gerer les trades ouverts : stop d'abord (bas du jour vs stop
        #     fixe la veille), puis signal/coupe-circuit/overlay de regime -
        #     ces trois derniers liquidant TOUJOURS la position ouverte
        #     immediatement (actions de risque ou de regime, pas seulement
        #     un blocage des nouvelles entrees) -, sinon mise a jour du
        #     stop (breakeven/trailing) pour la bougie suivante. ---
        for symbol in list(open_trades.keys()):
            trade = open_trades[symbol]
            row = aligned[symbol].iloc[t]

            if row["low"] <= trade.stop:
                exit_price = trade.stop
                notional = trade.units * exit_price
                cash += notional - notional * cfg.transaction_cost_bps / 10_000
                closed_trades.append(
                    ClosedTrade(symbol, trade.entry_date, trade.entry_price, common_index[t], exit_price, "stop", trade.weight_at_entry)
                )
                del open_trades[symbol]
                continue

            if row["raw_score"] <= 0 or not allowed or not regime_ok:
                exit_price = row["close"]
                notional = trade.units * exit_price
                cash += notional - notional * cfg.transaction_cost_bps / 10_000
                if row["raw_score"] <= 0:
                    reason = "signal"
                elif not allowed:
                    reason = "coupe-circuit"
                else:
                    reason = "regime"
                closed_trades.append(
                    ClosedTrade(symbol, trade.entry_date, trade.entry_price, common_index[t], exit_price, reason, trade.weight_at_entry)
                )
                del open_trades[symbol]
                continue

            initial_risk = trade.entry_price - trade.initial_stop
            if not trade.breakeven_triggered and (row["close"] - trade.entry_price) >= cfg.breakeven_r_multiple * initial_risk:
                trade.breakeven_triggered = True
                trade.stop = max(trade.stop, trade.entry_price)

            trade.highest_close = max(trade.highest_close, row["close"])
            if trade.breakeven_triggered and np.isfinite(row["atr"]):
                trailing_stop = trade.highest_close - cfg.trailing_atr_multiple * row["atr"]
                trade.stop = max(trade.stop, trailing_stop)

        # --- 2. Nouvelles entrees (seulement si autorise et flat sur l'actif) ---
        if allowed and regime_ok and bool(session_ok.iloc[t]):
            # Snapshot FIGE avant ces nouvelles entrees : sans lui, chaque
            # entree recalculerait l'equity apres le cout de la precedente,
            # et les poids (fractions de cette base qui bouge) cumuleraient
            # legerement au-dela de max_position_fraction une fois rapportes
            # a l'equity finale du pas de temps.
            equity_snapshot = cash + _positions_value(t)
            # Expositon COURANTE (mark-to-market), pas weight_at_entry : une
            # position ouverte qui a gagne en valeur depuis son entree pese
            # maintenant PLUS que sa fraction d'origine - l'ignorer sous-
            # estimerait l'exposition deja engagee et laisserait entrer trop
            # de nouvelles positions.
            committed = (
                sum(tr.units * aligned[tr.symbol]["close"].iloc[t] for tr in open_trades.values()) / equity_snapshot
                if equity_snapshot > 0
                else 0.0
            )
            available = max(0.0, cfg.max_position_fraction - committed)

            for symbol in symbols:
                if available <= 0:
                    break
                if symbol in open_trades:
                    continue
                row = aligned[symbol].iloc[t]
                if row["raw_score"] <= 0 or not np.isfinite(row["atr"]) or row["atr"] <= 0:
                    continue

                entry_price = row["close"]
                stop_distance = cfg.atr_stop_multiple * row["atr"]
                if stop_distance <= 0:
                    continue
                stop_pct = stop_distance / entry_price
                desired_weight = cfg.risk_per_trade / stop_pct
                weight = min(desired_weight, available, cfg.max_position_fraction)
                if weight <= 0:
                    continue

                # notional dimensionne pour que notional+cost (la sortie de
                # cash reelle) n'excede jamais weight*equity_snapshot - sans
                # ce /(1+taux), un poids plein (weight=1.0) laisserait cash
                # legerement negatif (le cout preleve EN PLUS d'une notional
                # deja egale a 100% de l'equity), gonflant artificiellement
                # l'exposition enregistree au-dessus de max_position_fraction.
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
                    initial_stop=entry_price - stop_distance,
                    weight_at_entry=weight,
                )
                available -= weight

        current_equity = cash + _positions_value(t)
        equity[t] = current_equity
        prev_equity = current_equity

        for j, symbol in enumerate(symbols):
            if symbol in open_trades:
                tr = open_trades[symbol]
                weights_records[t, j] = tr.units * aligned[symbol]["close"].iloc[t] / current_equity if current_equity > 0 else 0.0

    return DiscreteTradeResult(
        equity=pd.Series(equity, index=common_index, name="equity"),
        weights_history=pd.DataFrame(weights_records, index=common_index, columns=symbols),
        closed_trades=closed_trades,
        trading_allowed_history=pd.Series(trading_allowed, index=common_index, name="trading_allowed"),
    )
