"""Backtester et validation walk-forward (etape 5).

Assemble toutes les briques precedentes (signaux, combinaison, risque) en
une simulation complete, bougie par bougie, avec couts de transaction. La
boucle explicite (pas un vectorise pur) est un choix delibere : sur un
univers de quelques actifs et un historique de quelques milliers de
bougies, la clarte et la correction priment sur la vitesse - c'est un
backtester de recherche, pas un moteur haute frequence.

Limite connue et assumee : la simulation utilise des rendements
cloture-a-cloture. Le stop-loss ATR (etape 4) n'est donc pas execute a
l'interieur d'une bougie ici (pas de simulation intra-bougie) - seul le
coupe-circuit de drawdown, qui agit entre les bougies, est applique.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .metrics import sharpe_ratio
from .portfolio import build_universe_scores, target_weights_row
from .risk import DrawdownCircuitBreaker, inverse_vol_weights, volatility_target_leverage
from .signals import ema_trend_signal, ewma_volatility, ou_meanreversion_signal, rolling_hurst


@dataclass
class BacktestConfig:
    # Signaux
    ema_fast: int = 12
    ema_slow: int = 48
    ema_vol_window: int = 48
    hurst_window: int = 100
    hurst_min_lag: int = 2
    hurst_max_lag: int = 20
    ou_window: int = 100
    ou_significance_t: float = 2.0
    ewma_lambda: float = 0.94

    # Allocation / risque
    top_n: Optional[int] = None
    target_vol: float = 0.01  # vol cible PAR PERIODE (pas annualisee) : a adapter si le timeframe change
    max_leverage: float = 1.0
    halt_drawdown: float = 0.20
    resume_drawdown: float = 0.10
    circuit_breaker_cooldown: int = 24  # en nombre de bougies (24 = ~1 jour en 1h)

    # Execution
    transaction_cost_bps: float = 15.0  # cout aller-retour approx (spread+frais taker Kraken)
    initial_capital: float = 10_000.0


@dataclass
class BacktestResult:
    equity: pd.Series
    weights_history: pd.DataFrame
    turnover_history: pd.Series
    cost_history: pd.Series
    trading_allowed_history: pd.Series


def compute_symbol_signals(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Calcule les 3 signaux + la vol EWMA pour un actif. Vectorise (pas de
    dependance a l'etat du portefeuille), reutilisable tel quel hors backtest."""
    hurst = rolling_hurst(df["close"], window=cfg.hurst_window, min_lag=cfg.hurst_min_lag, max_lag=cfg.hurst_max_lag)
    ema_trend = ema_trend_signal(df["close"], fast=cfg.ema_fast, slow=cfg.ema_slow, vol_window=cfg.ema_vol_window)
    ou_signal = ou_meanreversion_signal(df["close"], window=cfg.ou_window, significance_t=cfg.ou_significance_t)["signal"]
    ewma_vol = ewma_volatility(df["close"], lam=cfg.ewma_lambda)

    return pd.DataFrame(
        {
            "close": df["close"],
            "hurst": hurst,
            "ema_trend": ema_trend,
            "ou_signal": ou_signal,
            "ewma_vol": ewma_vol,
        }
    )


def _align_universe(price_data: Dict[str, pd.DataFrame], cfg: BacktestConfig) -> Dict[str, pd.DataFrame]:
    """Calcule les signaux par actif puis aligne tous les actifs sur l'index
    (dates) commun a tous, pour pouvoir iterer ligne par ligne en toute
    coherence temporelle.

    Important : on ne filtre que sur les colonnes qui DOIVENT etre valides
    (close, hurst, ema_trend, ewma_vol). ou_signal est volontairement exclu
    de ce filtre - il est frequemment NaN quand aucune reversion n'est
    statistiquement significative (cf. etape 2), ce qui est un etat normal
    et attendu, pas une donnee manquante. composite_score() traite deja ce
    NaN comme "aucune contribution" (fillna(0)). Le filtrer ici aussi
    supprimerait silencieusement une grande partie de l'historique valide.
    """
    required_cols = ["close", "hurst", "ema_trend", "ewma_vol"]
    per_symbol = {symbol: compute_symbol_signals(df, cfg) for symbol, df in price_data.items()}

    common_index = None
    for df in per_symbol.values():
        idx = df.dropna(subset=required_cols).index
        common_index = idx if common_index is None else common_index.intersection(idx)

    return {symbol: df.loc[common_index] for symbol, df in per_symbol.items()}


def run_backtest(price_data: Dict[str, pd.DataFrame], cfg: BacktestConfig) -> BacktestResult:
    """Simule la strategie complete sur l'historique fourni.

    price_data : {symbol: DataFrame avec au moins la colonne 'close'}, meme
    convention que data.py (index = datetime).
    """
    aligned = _align_universe(price_data, cfg)
    symbols = list(aligned.keys())
    n = len(next(iter(aligned.values())))

    if n < 2:
        raise ValueError("Pas assez de donnees alignees apres warm-up des signaux pour lancer un backtest")

    raw_scores = build_universe_scores({s: aligned[s][["hurst", "ema_trend", "ou_signal"]] for s in symbols})
    vol_df = pd.DataFrame({s: aligned[s]["ewma_vol"] for s in symbols})
    close_df = pd.DataFrame({s: aligned[s]["close"] for s in symbols})

    index = raw_scores.index
    equity = np.empty(n)
    equity[0] = cfg.initial_capital

    weights_records = np.zeros((n, len(symbols)))
    turnover = np.zeros(n)
    cost = np.zeros(n)
    trading_allowed = np.ones(n, dtype=bool)

    breaker = DrawdownCircuitBreaker(
        halt_drawdown=cfg.halt_drawdown,
        resume_drawdown=cfg.resume_drawdown,
        cooldown_periods=cfg.circuit_breaker_cooldown,
    )
    prev_weights = pd.Series(0.0, index=symbols)

    for t in range(n - 1):
        allowed = breaker.step(equity[t])
        trading_allowed[t] = allowed

        row_scores = raw_scores.iloc[t]
        row_vols = vol_df.iloc[t]

        w_score = target_weights_row(row_scores, top_n=cfg.top_n)
        w_tilted = inverse_vol_weights(w_score, row_vols)
        leverage = volatility_target_leverage(w_tilted, row_vols, target_vol=cfg.target_vol, max_leverage=cfg.max_leverage)
        w_final = w_tilted * leverage if allowed else w_tilted * 0.0

        period_turnover = (w_final - prev_weights).abs().sum()
        period_cost = period_turnover * cfg.transaction_cost_bps / 10_000

        asset_returns = close_df.iloc[t + 1] / close_df.iloc[t] - 1
        portfolio_return = float((w_final * asset_returns).sum()) - period_cost

        equity[t + 1] = equity[t] * (1 + portfolio_return)
        weights_records[t] = w_final.reindex(symbols).values
        turnover[t] = period_turnover
        cost[t] = period_cost

        prev_weights = w_final

    # Derniere ligne : pas de nouvelle decision (pas de rendement suivant a realiser).
    trading_allowed[-1] = breaker.step(equity[-1])
    weights_records[-1] = prev_weights.reindex(symbols).values

    return BacktestResult(
        equity=pd.Series(equity, index=index, name="equity"),
        weights_history=pd.DataFrame(weights_records, index=index, columns=symbols),
        turnover_history=pd.Series(turnover, index=index, name="turnover"),
        cost_history=pd.Series(cost, index=index, name="cost"),
        trading_allowed_history=pd.Series(trading_allowed, index=index, name="trading_allowed"),
    )


# ---------------------------------------------------------------------------
# Validation walk-forward : la discipline anti-overfitting (cf. etape 5, README)
# ---------------------------------------------------------------------------


def _reference_index(price_data: Dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """Intersection des dates disponibles pour TOUS les actifs (avant tout
    calcul de signal), utilisee pour decouper les folds de maniere coherente
    quelle que soit la config testee."""
    index = None
    for df in price_data.values():
        index = df.index if index is None else index.intersection(df.index)
    return index.sort_values()


def expanding_splits(n_periods: int, n_splits: int) -> List[Tuple[int, int, int, int]]:
    """Decoupe [0, n_periods) en folds a fenetre d'entrainement EXPANSIVE.

    Fold k : train = [0, k*fold_size), test = [k*fold_size, (k+1)*fold_size).
    Le dernier fold absorbe le reste pour ne pas perdre de donnees en fin de
    serie. Renvoie des index POSITIONNELS (a appliquer sur l'index de dates
    de reference), pas des dates.
    """
    if n_splits < 1:
        raise ValueError("n_splits doit etre >= 1")
    fold_size = n_periods // (n_splits + 1)
    if fold_size < 1:
        raise ValueError(f"Pas assez de periodes ({n_periods}) pour {n_splits} splits")

    splits = []
    for k in range(1, n_splits + 1):
        train_end = k * fold_size
        test_end = (k + 1) * fold_size if k < n_splits else n_periods
        splits.append((0, train_end, train_end, test_end))
    return splits


def _slice_price_data(price_data: Dict[str, pd.DataFrame], dates: pd.DatetimeIndex) -> Dict[str, pd.DataFrame]:
    return {symbol: df.loc[dates] for symbol, df in price_data.items()}


@dataclass
class FoldResult:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    chosen_config: BacktestConfig
    train_sharpe: float
    test_result: BacktestResult


class WalkForwardValidator:
    """Recherche d'hyperparametres en walk-forward : sur chaque fold, le
    meilleur config du grid est choisi UNIQUEMENT sur le train (par Sharpe),
    puis applique tel quel sur le test suivant, jamais revu. Les segments de
    test sont enchaines en une seule courbe hors-echantillon de bout en
    bout - c'est cette courbe, pas la performance en train, qui doit servir
    a juger la strategie.

    Limite connue : chaque fold reconstruit ses signaux independamment
    (aucun etat/historique partage entre folds), donc chaque fold "gaspille"
    ses cfg.*_window premieres periodes en warm-up. Un fold trop court par
    rapport aux fenetres des signaux ne produira aucun resultat exploitable
    et sera saute (voir min_valid_periods) plutot que de fausser la
    validation avec un resultat degenere.
    """

    def __init__(
        self,
        config_grid: List[BacktestConfig],
        n_splits: int = 4,
        periods_per_year: float = 8760,
        min_valid_periods: int = 20,
    ):
        if not config_grid:
            raise ValueError("config_grid ne peut pas etre vide")
        self.config_grid = config_grid
        self.n_splits = n_splits
        self.periods_per_year = periods_per_year
        self.min_valid_periods = min_valid_periods

    def run(self, price_data: Dict[str, pd.DataFrame]) -> Tuple[pd.Series, List[FoldResult]]:
        ref_index = _reference_index(price_data)
        splits = expanding_splits(len(ref_index), self.n_splits)

        fold_results: List[FoldResult] = []
        oos_returns_segments: List[pd.Series] = []

        for train_start, train_end, test_start, test_end in splits:
            train_slice = _slice_price_data(price_data, ref_index[train_start:train_end])
            test_slice = _slice_price_data(price_data, ref_index[test_start:test_end])

            best_cfg, best_sharpe = self._select_best_config(train_slice)
            if best_cfg is None:
                continue  # aucune config n'a produit de resultat exploitable sur ce train

            try:
                test_result = run_backtest(test_slice, best_cfg)
            except ValueError:
                continue
            if len(test_result.equity) < 2:
                continue

            fold_results.append(
                FoldResult(
                    train_start=ref_index[train_start],
                    train_end=ref_index[train_end - 1],
                    test_start=ref_index[test_start],
                    test_end=ref_index[test_end - 1],
                    chosen_config=best_cfg,
                    train_sharpe=best_sharpe,
                    test_result=test_result,
                )
            )
            oos_returns_segments.append(test_result.equity.pct_change().dropna())

        if not oos_returns_segments:
            raise ValueError(
                "Aucun fold n'a produit de resultat exploitable - historique trop court "
                "par rapport aux fenetres des signaux, ou n_splits trop eleve"
            )

        oos_returns = pd.concat(oos_returns_segments)
        # Courbe hors-echantillon reconstituee en enchainant les rendements de
        # chaque fold de test (base 1.0, pas les dollars du cfg.initial_capital
        # de chaque fold independant - ce sont des rendements qui s'enchainent,
        # pas des niveaux de capital directement comparables entre folds).
        oos_equity = (1 + oos_returns).cumprod()
        oos_equity.name = "oos_equity"

        return oos_equity, fold_results

    def _select_best_config(self, train_slice: Dict[str, pd.DataFrame]) -> Tuple[Optional[BacktestConfig], float]:
        best_cfg = None
        best_sharpe = -np.inf

        for cfg in self.config_grid:
            try:
                train_result = run_backtest(train_slice, cfg)
            except ValueError:
                continue
            if len(train_result.equity) < self.min_valid_periods:
                continue

            train_returns = train_result.equity.pct_change().dropna()
            sharpe = sharpe_ratio(train_returns, self.periods_per_year)
            if np.isnan(sharpe):
                continue
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_cfg = cfg

        return best_cfg, best_sharpe
