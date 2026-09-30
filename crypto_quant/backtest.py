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
from .signals import (
    adx,
    adx_trend_gate,
    baz_response,
    ema_trend_signal,
    ewma_volatility,
    market_regime_signal,
    multi_horizon_trend_signal,
    ou_meanreversion_signal,
    rolling_hurst,
)


@dataclass
class BacktestConfig:
    # Signaux
    ema_fast: int = 12
    ema_slow: int = 48
    ema_vol_window: int = 48
    ema_skip: int = 0  # bougies recentes exclues de l'EMA (cf. "12-1 mois" academique, signals.ema_trend_signal)
    ema_bounded_response: bool = False  # applique signals.baz_response a ema_trend (Baz et al. 2015 / Rohrbach et al. 2017)
    ema_multi_horizon: bool = False  # remplace ema_trend_signal par signals.multi_horizon_trend_signal (3 paires EMA)
    ema_multi_price_vol_window: int = 63
    ema_multi_signal_vol_window: int = 252
    hurst_window: int = 100
    hurst_min_lag: int = 2
    hurst_max_lag: int = 20
    trend_gate_source: str = "hurst"  # "hurst" (defaut) ou "adx" - lequel filtre le mieux le "ranging" (a comparer)
    adx_period: int = 14
    adx_threshold: float = 20.0
    adx_cap: float = 40.0
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
    rebalance_threshold: float = 0.0  # zone morte : ne rebalance que si |w_cible - w_detenu| (L1) depasse ce seuil

    # Detection de trou de calendrier (etape 13 bis) : multiple du pas typique
    # au-dela duquel un ecart est considere comme un vrai trou de donnees.
    # 3.0 (defaut) convient a la crypto (24/7, un trou = un vrai probleme).
    # Les marches traditionnels ont des week-ends/jours feries (jusqu'a ~5
    # jours pour un long week-end) : augmenter (ex: 6.0) pour eviter de
    # confondre un week-end normal avec un vrai trou de donnees.
    calendar_gap_multiple: float = 3.0

    # Overlay de regime de marche (Starkiller Capital, 2023) : cash integral
    # pour TOUT le portefeuille quand market_regime_symbol est en tendance
    # baissiere, independamment des signaux par actif. Desactive si None.
    market_regime_symbol: Optional[str] = None
    market_regime_fast: int = 5
    market_regime_slow: int = 50


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
    if cfg.ema_multi_horizon:
        ema_trend = multi_horizon_trend_signal(
            df["close"],
            price_vol_window=cfg.ema_multi_price_vol_window,
            signal_vol_window=cfg.ema_multi_signal_vol_window,
            use_bounded_response=cfg.ema_bounded_response,
            skip=cfg.ema_skip,
        ).rename("ema_trend")
    else:
        ema_trend = ema_trend_signal(
            df["close"], fast=cfg.ema_fast, slow=cfg.ema_slow, vol_window=cfg.ema_vol_window, skip=cfg.ema_skip
        )
        if cfg.ema_bounded_response:
            ema_trend = baz_response(ema_trend).rename("ema_trend")
    ou_signal = ou_meanreversion_signal(df["close"], window=cfg.ou_window, significance_t=cfg.ou_significance_t)["signal"]
    ewma_vol = ewma_volatility(df["close"], lam=cfg.ewma_lambda)

    columns = {
        "close": df["close"],
        "hurst": hurst,
        "ema_trend": ema_trend,
        "ou_signal": ou_signal,
        "ewma_vol": ewma_vol,
    }

    if cfg.trend_gate_source == "adx":
        if "high" not in df.columns or "low" not in df.columns:
            raise ValueError(
                "trend_gate_source='adx' necessite les colonnes 'high' et 'low' dans price_data - "
                "absentes ici (donnees close-only)."
            )
        adx_series = adx(df["high"], df["low"], df["close"], period=cfg.adx_period)
        columns["trend_gate"] = adx_trend_gate(adx_series, threshold=cfg.adx_threshold, cap=cfg.adx_cap)
    elif cfg.trend_gate_source != "hurst":
        raise ValueError(f"trend_gate_source invalide : {cfg.trend_gate_source!r} (attendu 'hurst' ou 'adx')")

    return pd.DataFrame(columns)


def _assert_no_calendar_gaps(index: pd.DatetimeIndex, max_gap_multiple: float = 3.0) -> None:
    """Echoue bruyamment si le calendrier BRUT (prix, avant tout calcul de
    signal) contient un trou (ex: suspension du trading USD sur un exchange
    - Binance.US, juillet 2023 a fevrier 2025).

    run_backtest itere PAR POSITION (t -> t+1), jamais par date (cf. sa
    docstring) : sans cette garde, un trou de plusieurs mois entre deux
    bougies consecutives serait silencieusement traite comme le rendement
    d'une SEULE periode, contaminant EMA/vol/Hurst et le P&L simule autour
    de ce point - l'artefact qui a contamine les etapes 9bis a 13 avant
    detection (voir README, etape 13 bis).

    Applique au calendrier des PRIX BRUTS (avant dropna des signaux) : un
    signal individuel peut legitimement etre NaN au milieu d'une serie sans
    qu'il y ait de trou de marche reel (ex: vol glissante nulle sur une
    periode de prix parfaitement plat - cf. docstring de _align_universe) -
    ce n'est pas le probleme vise ici, et ne doit pas declencher cette
    garde.

    Ne corrige rien ici (detection seule) : en cas d'erreur, appeler
    data.largest_contiguous_segment(price_data) AVANT de construire
    price_data passe a run_backtest, pour ne garder que le plus grand
    segment continu.
    """
    if len(index) < 3:
        return

    gaps = index[1:] - index[:-1]
    modal_step = pd.Series(gaps).mode().iloc[0]
    max_gap = gaps.max()

    if max_gap > modal_step * max_gap_multiple:
        gap_pos = int(np.argmax(gaps.values))
        raise ValueError(
            f"Trou de calendrier detecte dans les prix bruts : {index[gap_pos]} -> "
            f"{index[gap_pos + 1]} (ecart de {max_gap} contre un pas typique de {modal_step}). "
            "Le backtester iterant par position, ce trou serait traite comme le rendement d'une "
            "seule periode - utiliser data.largest_contiguous_segment(price_data) avant de "
            "construire l'univers passe a run_backtest/WalkForwardValidator."
        )


def _score_columns(cfg: BacktestConfig) -> List[str]:
    """Colonnes a extraire de chaque actif aligne pour build_universe_scores -
    'trend_gate' seulement quand trend_gate_source='adx' (absente sinon,
    portfolio.composite_score retombe alors sur le gate derive du Hurst)."""
    cols = ["hurst", "ema_trend", "ou_signal"]
    if cfg.trend_gate_source == "adx":
        cols.append("trend_gate")
    return cols


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
    raw_common_index = None
    for df in price_data.values():
        raw_common_index = df.index if raw_common_index is None else raw_common_index.intersection(df.index)
    _assert_no_calendar_gaps(raw_common_index.sort_values(), max_gap_multiple=cfg.calendar_gap_multiple)

    required_cols = ["close", "hurst", "ema_trend", "ewma_vol"]
    per_symbol = {symbol: compute_symbol_signals(df, cfg) for symbol, df in price_data.items()}

    common_index = None
    for df in per_symbol.values():
        idx = df.dropna(subset=required_cols).index
        common_index = idx if common_index is None else common_index.intersection(idx)

    return {symbol: df.loc[common_index] for symbol, df in per_symbol.items()}


def compute_live_weights(price_data: Dict[str, pd.DataFrame], cfg: BacktestConfig) -> pd.Series:
    """Calcule les poids cibles ACTUELS (derniere bougie disponible), avec le
    meme pipeline que run_backtest (signaux -> score composite -> poids
    long-only -> tilt vol inverse -> ciblage de volatilite), pour une
    decision de trading live (etape 6).

    Ne calcule PAS le coupe-circuit de drawdown : celui-ci a besoin de
    l'historique d'equity de la STRATEGIE (pas du marche), qui doit etre
    suivi/persiste separement en production (cf. execution.py,
    save_breaker_state/load_breaker_state) et applique par l'appelant apres
    ce calcul, pas ici.
    """
    aligned = _align_universe(price_data, cfg)
    symbols = list(aligned.keys())
    if not symbols or len(next(iter(aligned.values()))) == 0:
        raise ValueError("Pas assez de donnees alignees apres warm-up des signaux pour calculer des poids live")

    raw_scores = build_universe_scores({s: aligned[s][_score_columns(cfg)] for s in symbols})
    vol_df = pd.DataFrame({s: aligned[s]["ewma_vol"] for s in symbols})

    last_scores = raw_scores.iloc[-1]
    last_vols = vol_df.iloc[-1]

    w_score = target_weights_row(last_scores, top_n=cfg.top_n)
    w_tilted = inverse_vol_weights(w_score, last_vols)
    leverage = volatility_target_leverage(w_tilted, last_vols, target_vol=cfg.target_vol, max_leverage=cfg.max_leverage)
    return w_tilted * leverage


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

    raw_scores = build_universe_scores({s: aligned[s][_score_columns(cfg)] for s in symbols})
    vol_df = pd.DataFrame({s: aligned[s]["ewma_vol"] for s in symbols})
    close_df = pd.DataFrame({s: aligned[s]["close"] for s in symbols})

    regime_gate = None
    if cfg.market_regime_symbol is not None:
        if cfg.market_regime_symbol not in close_df.columns:
            raise ValueError(f"market_regime_symbol={cfg.market_regime_symbol!r} absent de l'univers fourni")
        regime_gate = market_regime_signal(
            close_df[cfg.market_regime_symbol], fast=cfg.market_regime_fast, slow=cfg.market_regime_slow
        )

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

        market_ok = True if regime_gate is None else bool(regime_gate.iloc[t])
        trade_ok = allowed and market_ok

        w_score = target_weights_row(row_scores, top_n=cfg.top_n)
        w_tilted = inverse_vol_weights(w_score, row_vols)
        leverage = volatility_target_leverage(w_tilted, row_vols, target_vol=cfg.target_vol, max_leverage=cfg.max_leverage)
        w_target = w_tilted * leverage if trade_ok else w_tilted * 0.0

        # Zone morte : si le coupe-circuit vient de couper OU que l'overlay de
        # regime de marche est passe risk-off, on liquide TOUJOURS
        # immediatement (jamais soumis au seuil - ce sont des actions de
        # risque, pas un rebalancement de signal). Sinon, ne rebalance que si
        # l'ecart au poids cible depasse rebalance_threshold - sans ca, un
        # signal qui ne bouge vraiment qu'a l'echelle de ses fenetres (des
        # jours) declenche quand meme un rebalancement (et son cout) a chaque
        # bougie.
        if trade_ok and cfg.rebalance_threshold > 0:
            proposed_turnover = (w_target - prev_weights).abs().sum()
            w_held = prev_weights if proposed_turnover < cfg.rebalance_threshold else w_target
        else:
            w_held = w_target

        period_turnover = (w_held - prev_weights).abs().sum()
        period_cost = period_turnover * cfg.transaction_cost_bps / 10_000

        asset_returns = close_df.iloc[t + 1] / close_df.iloc[t] - 1
        portfolio_return = float((w_held * asset_returns).sum()) - period_cost

        equity[t + 1] = equity[t] * (1 + portfolio_return)
        weights_records[t] = w_held.reindex(symbols).values
        turnover[t] = period_turnover
        cost[t] = period_cost

        prev_weights = w_held

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
            test_length = test_end - test_start

            best_cfg, best_sharpe = self._select_best_config(train_slice, test_length)
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

    def _select_best_config(
        self, train_slice: Dict[str, pd.DataFrame], test_length: int
    ) -> Tuple[Optional[BacktestConfig], float]:
        """Choisit la config au meilleur Sharpe train, PARMI celles qui ont
        structurellement une chance de produire un resultat exploitable sur
        le prochain segment de test (de taille fixe `test_length`).

        Sans ce filtre, une config a grande fenetre de warm-up (hurst/ou/ema)
        peut sembler la meilleure sur un train qui grandit a chaque fold
        (justement parce qu'elle overfit sur peu de trades), etre choisie,
        puis echouer entierement sur le test suivant (pas assez de bougies
        pour sortir du warm-up) - ce qui invalidait silencieusement le fold
        entier (voir README). Ce filtre ne regarde jamais les PRIX du test,
        seulement la taille du segment : aucune fuite d'information train/test.
        """
        best_cfg = None
        best_sharpe = -np.inf

        for cfg in self.config_grid:
            # Le multi-horizon enchaine deux normalisations glissantes
            # (price_vol_window PUIS signal_vol_window sur le resultat), le
            # warm-up reel est donc leur somme, pas juste l'horizon EMA le
            # plus lent - sinon ce filtre laisserait passer des configs qui
            # ne produiront en realite aucune valeur exploitable sur le fold.
            ema_component = (
                cfg.ema_multi_price_vol_window + cfg.ema_multi_signal_vol_window
                if cfg.ema_multi_horizon
                else cfg.ema_slow
            )
            max_window = max(ema_component, cfg.ema_vol_window, cfg.hurst_window, cfg.ou_window)
            if max_window + self.min_valid_periods > test_length:
                continue

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
