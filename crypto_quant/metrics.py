"""Metriques de performance calculees a partir d'une courbe d'equity (etape 5).

Toutes les fonctions prennent soit une courbe d'equity (valeur du portefeuille
dans le temps), soit une serie de rendements par periode, et un parametre
periods_per_year pour annualiser correctement (8760 pour du 1h, 365 pour du
1d, etc. - depend du timeframe choisi dans la config).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def returns_from_equity(equity: pd.Series) -> pd.Series:
    return equity.pct_change().dropna()


def cagr(equity: pd.Series, periods_per_year: float) -> float:
    """Taux de croissance annualise entre le premier et le dernier point."""
    n_periods = len(equity) - 1
    if n_periods <= 0 or equity.iloc[0] <= 0:
        return np.nan
    total_return = equity.iloc[-1] / equity.iloc[0]
    if total_return <= 0:
        return -1.0
    years = n_periods / periods_per_year
    return float(total_return ** (1 / years) - 1)


def sharpe_ratio(returns: pd.Series, periods_per_year: float, risk_free: float = 0.0) -> float:
    """Sharpe annualise : (moyenne - taux sans risque) / ecart-type, x sqrt(periodes/an).

    Renvoie NaN si l'ecart-type est nul (serie constante) plutot qu'une
    division par zero silencieuse.
    """
    excess = returns - risk_free
    std = excess.std()
    if std == 0 or np.isnan(std):
        return np.nan
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: float, risk_free: float = 0.0) -> float:
    """Comme Sharpe, mais ne penalise que la volatilite des rendements negatifs."""
    excess = returns - risk_free
    downside = excess[excess < 0]
    downside_std = downside.std()
    if downside_std == 0 or np.isnan(downside_std):
        return np.nan
    return float(excess.mean() / downside_std * np.sqrt(periods_per_year))


def max_drawdown(equity: pd.Series) -> float:
    """Pire drawdown observe (valeur negative, ex: -0.25 = -25%)."""
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return float(drawdown.min())


def calmar_ratio(cagr_value: float, max_dd: float) -> float:
    """CAGR / |max drawdown|. Renvoie NaN si max_dd est nul."""
    if max_dd == 0 or np.isnan(max_dd):
        return np.nan
    return float(cagr_value / abs(max_dd))


def hit_rate(returns: pd.Series) -> float:
    """Fraction de periodes a rendement strictement positif."""
    if len(returns) == 0:
        return np.nan
    return float((returns > 0).mean())


def average_turnover(weights_history: pd.DataFrame) -> float:
    """Turnover moyen par periode : somme des variations absolues de poids.

    min_count=1 est essentiel : sans lui, DataFrame.sum(axis=1) traite une
    ligne entierement NaN (la toute premiere periode, sans poids precedent
    pour calculer une variation) comme 0 par defaut (skipna), ce qui biaise
    la moyenne vers le bas en comptant une periode indefinie comme "turnover
    nul" au lieu de l'exclure.
    """
    turnover_per_period = weights_history.diff().abs().sum(axis=1, min_count=1)
    return float(turnover_per_period.mean())


def summarize_performance(
    equity: pd.Series,
    periods_per_year: float,
    weights_history: pd.DataFrame = None,
    risk_free: float = 0.0,
) -> dict:
    """Rassemble toutes les metriques en un seul dict, pratique pour reporting."""
    returns = returns_from_equity(equity)
    mdd = max_drawdown(equity)
    c = cagr(equity, periods_per_year)

    summary = {
        "cagr": c,
        "sharpe": sharpe_ratio(returns, periods_per_year, risk_free),
        "sortino": sortino_ratio(returns, periods_per_year, risk_free),
        "max_drawdown": mdd,
        "calmar": calmar_ratio(c, mdd),
        "hit_rate": hit_rate(returns),
        "n_periods": len(equity),
    }
    if weights_history is not None:
        summary["avg_turnover"] = average_turnover(weights_history)
    return summary
