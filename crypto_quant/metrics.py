"""Metriques de performance calculees a partir d'une courbe d'equity (etape 5).

Toutes les fonctions prennent soit une courbe d'equity (valeur du portefeuille
dans le temps), soit une serie de rendements par periode, et un parametre
periods_per_year pour annualiser correctement (8760 pour du 1h, 365 pour du
1d, etc. - depend du timeframe choisi dans la config).

sharpe_significance/permutation_test_sharpe (cf. Chan, "Algorithmic Trading",
chap. 1) repondent a une question que le Sharpe seul ne dit pas : un Sharpe
de 0.35 sur 360 periodes est-il distinguable du bruit ? Un Sharpe annualise
impressionnant sur un petit echantillon peut tres bien ne pas l'etre.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


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


def sharpe_significance(returns: pd.Series) -> dict:
    """Test de significativite du Sharpe (test gaussien ferme, cf. Chan,
    "Algorithmic Trading", chap. 1) : sous l'hypothese nulle "rendement
    moyen vrai = 0", la statistique t = mean(ret)/std(ret)*sqrt(n) suit
    approximativement une loi normale standard. On en tire une p-value
    bilaterale.

    C'est une statistique PAR PERIODE (pas annualisee) : contrairement au
    Sharpe annualise, qui peut sembler impressionnant sur un tout petit
    echantillon, ce test integre explicitement la taille d'echantillon n -
    c'est precisement ce qui manquait pour juger un resultat comme le Sharpe
    OOS de 0.35 sur 360 periodes de l'etape 7 (voir README).

    Limite assumee : suppose des rendements independants et identiquement
    distribues. De l'autocorrelation dans les rendements (frequente en
    pratique) biaiserait ce test - un signal utile, pas une preuve absolue.
    """
    valid = returns.dropna()
    n = len(valid)
    std = valid.std()
    if n < 2 or std == 0 or np.isnan(std):
        return {"t_stat": np.nan, "p_value": np.nan, "n": n}

    t_stat = float(valid.mean() / std * np.sqrt(n))
    p_value = float(2 * stats.norm.sf(abs(t_stat)))
    return {"t_stat": t_stat, "p_value": p_value, "n": n}


def permutation_test_sharpe(
    weights_history: pd.DataFrame,
    asset_returns: pd.DataFrame,
    n_simulations: int = 2000,
    seed: Optional[int] = None,
) -> dict:
    """Test de significativite par permutation temporelle des positions (cf.
    Chan, "Algorithmic Trading", chap. 1, methode 3 - adaptee d'un portefeuille
    a trades discrets a un portefeuille a poids continus comme le notre).

    Hypothese nulle : le TIMING des positions n'ajoute aucune valeur - le
    meme jeu de poids (weights_history) aurait pu etre applique a n'importe
    quel autre moment avec un resultat tout aussi bon. On permute l'ordre
    temporel des LIGNES de poids (quel jour recoit quel poids), on
    reapplique ces poids permutes aux VRAIS rendements d'actifs (non
    permutes) pour obtenir un P&L simule, et on repete. p_value = fraction
    des permutations dont le Sharpe est >= au Sharpe observe : une p_value
    proche de 0 indique que le TIMING reel des positions (pas seulement leur
    distribution/frequence) capture quelque chose de reel.

    weights_history et asset_returns doivent partager le meme index de
    dates et les memes colonnes (symboles) ; les colonnes qui ne
    correspondent pas de part et d'autre sont ignorees.

    Limite assumee : ignore les couts de transaction (le turnover change
    sous permutation, donc les couts aussi - approximation deliberee pour
    rester un test rapide, pas un vrai second backtest complet). N'est donc
    pas directement comparable au Sharpe NET rapporte par summarize_performance
    (qui inclut les couts) - comparer le Sharpe observe ici (brut) a la
    distribution permutee (brute egalement), pas au Sharpe net du backtest.
    """
    common_cols = weights_history.columns.intersection(asset_returns.columns)
    if len(common_cols) == 0:
        return {"observed_sharpe": np.nan, "p_value": np.nan, "n_simulations": 0}

    w = weights_history[common_cols].shift(1).fillna(0.0).values
    r = asset_returns[common_cols].reindex(weights_history.index).fillna(0.0).values
    n = len(w)
    if n < 2:
        return {"observed_sharpe": np.nan, "p_value": np.nan, "n_simulations": 0}

    def _sharpe(port_returns: np.ndarray) -> float:
        std = port_returns.std()
        return float(port_returns.mean() / std) if std > 0 else np.nan

    observed_returns = (w * r).sum(axis=1)
    observed_sharpe = _sharpe(observed_returns)
    if np.isnan(observed_sharpe):
        return {"observed_sharpe": np.nan, "p_value": np.nan, "n_simulations": 0}

    rng = np.random.default_rng(seed)
    count_as_good = 0
    valid_sims = 0
    for _ in range(n_simulations):
        permuted_returns = (w[rng.permutation(n)] * r).sum(axis=1)
        sim_sharpe = _sharpe(permuted_returns)
        if np.isnan(sim_sharpe):
            continue
        valid_sims += 1
        if sim_sharpe >= observed_sharpe:
            count_as_good += 1

    p_value = float(count_as_good / valid_sims) if valid_sims > 0 else np.nan
    return {"observed_sharpe": observed_sharpe, "p_value": p_value, "n_simulations": valid_sims}


def spa_test(
    strategy_returns: pd.DataFrame,
    benchmark_returns: pd.Series,
    n_bootstrap: int = 1000,
    block_size: int = 10,
    seed: Optional[int] = None,
) -> dict:
    """Test de Superior Predictive Ability (Hansen, 2005) : corrige la
    p-value du MEILLEUR backtest parmi plusieurs strategies testees pour le
    nombre de configurations essayees - la limite reconnue de notre propre
    methodologie walk-forward depuis la lecture de Baur et al. (2018) sur
    l'or (cf. README, etape 17 bis) : choisir la meilleure config sur train
    protege du data-snooping LOCAL a chaque fold, mais pas du fait d'avoir
    essaye plusieurs GRILLES de config au fil de la session.

    Hypothese nulle : aucune des strategies testees ne bat le benchmark en
    esperance, UNE FOIS pris en compte qu'on a cherche parmi
    strategy_returns.shape[1] candidates, pas une seule choisie a l'avance.

    Methode (version simplifiee de Hansen 2005) : bootstrap PAR BLOCS
    (prefere a un bootstrap i.i.d. a cause de l'autocorrelation des
    rendements financiers) de l'exces de rendement de chaque strategie sur
    le benchmark, recentre sous l'hypothese nulle, puis compare la
    meilleure statistique observee (type t-stat) a la distribution
    bootstrap du MAXIMUM sur toutes les strategies - une strategie peut
    sembler significative isolement (p<0.05 au sens de sharpe_significance)
    tout en ne l'etant plus une fois cette correction appliquee.

    strategy_returns : DataFrame, une colonne par strategie/config testee
    (memes dates que benchmark_returns, non necessairement alignees -
    l'alignement est fait ici).
    """
    excess = strategy_returns.sub(benchmark_returns, axis=0).dropna()
    n, k = excess.shape
    if n < block_size * 5:
        raise ValueError(f"spa_test necessite au moins {block_size * 5} observations, {n} fournies")

    mean_excess = excess.mean()
    std_excess = excess.std()
    observed_stats = (mean_excess / std_excess * np.sqrt(n)).fillna(-np.inf)
    observed_max_stat = float(observed_stats.max())
    best_strategy = observed_stats.idxmax()

    rng = np.random.default_rng(seed)
    centered = excess - mean_excess  # recentre sous H0 (Hansen 2005)

    n_blocks = int(np.ceil(n / block_size))
    boot_max_stats = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        block_starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in block_starts])[:n]
        sample = centered.values[idx]
        boot_mean = sample.mean(axis=0)
        boot_std = sample.std(axis=0)
        boot_stats = np.where(boot_std > 0, boot_mean / boot_std * np.sqrt(n), -np.inf)
        boot_max_stats[b] = boot_stats.max()

    p_value = float(np.mean(boot_max_stats >= observed_max_stat))

    return {
        "best_strategy": best_strategy,
        "observed_statistic": observed_max_stat,
        "p_value": p_value,
        "n_strategies_tested": k,
        "n_bootstrap": n_bootstrap,
    }


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

    significance = sharpe_significance(returns)

    summary = {
        "cagr": c,
        "sharpe": sharpe_ratio(returns, periods_per_year, risk_free),
        "sharpe_p_value": significance["p_value"],
        "sortino": sortino_ratio(returns, periods_per_year, risk_free),
        "max_drawdown": mdd,
        "calmar": calmar_ratio(c, mdd),
        "hit_rate": hit_rate(returns),
        "n_periods": len(equity),
    }
    if weights_history is not None:
        summary["avg_turnover"] = average_turnover(weights_history)
    return summary
