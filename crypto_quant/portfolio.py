"""Combinaison des signaux en score composite, et allocation cross-actifs
(etape 3).

Le regime (exposant de Hurst) arbitre entre le signal de tendance (EMA) et
le signal de retour a la moyenne (OU) : jamais les deux a poids egal sur un
meme actif, puisqu'ils sont concus pour des regimes opposes. Quand H est
proche de 0.5 (pas d'edge statistique detectable), les deux poids sont
proches de 0 et le score composite est attenue en consequence - c'est le
comportement recherche, pas un defaut.

L'allocation finale suppose du spot long-only (compte Kraken standard, pas
de vente a decouvert) : seuls les actifs a score positif recoivent un poids,
proportionnel a leur score.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd


def _gate(diff_from_half: pd.Series) -> pd.Series:
    """Transforme (H-0.5) ou (0.5-H) en poids dans [0,1], sature a H=0 ou H=1."""
    return diff_from_half.clip(lower=0.0, upper=0.5) / 0.5


def composite_score(hurst: pd.Series, ema_trend: pd.Series, ou_signal: pd.Series) -> pd.DataFrame:
    """Fusionne les signaux d'un actif en un score composite unique.

    Renvoie un DataFrame avec les colonnes : trend_gate, meanrev_gate,
    raw_score. Un signal NaN (ex: OU non significatif, ou warm-up EMA) est
    traite comme "pas de contribution" (0), pas comme une valeur manquante a
    propager - l'absence de signal doit reduire la conviction, pas invalider
    tout le score.
    """
    trend_gate = _gate(hurst - 0.5)
    meanrev_gate = _gate(0.5 - hurst)

    raw_score = trend_gate * ema_trend.fillna(0.0) + meanrev_gate * ou_signal.fillna(0.0)

    return pd.DataFrame(
        {
            "trend_gate": trend_gate,
            "meanrev_gate": meanrev_gate,
            "raw_score": raw_score,
        }
    )


def build_universe_scores(signals_by_symbol: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Assemble les scores composites de tous les actifs en un seul DataFrame.

    signals_by_symbol[symbol] doit avoir les colonnes 'hurst', 'ema_trend',
    'ou_signal', indexees par date. Renvoie un DataFrame indexe par date,
    une colonne par symbole (raw_score).
    """
    scores = {}
    for symbol, df in signals_by_symbol.items():
        comp = composite_score(df["hurst"], df["ema_trend"], df["ou_signal"])
        scores[symbol] = comp["raw_score"]
    return pd.DataFrame(scores)


def target_weights_row(scores_row: pd.Series, top_n: Optional[int] = None) -> pd.Series:
    """Poids d'allocation a un instant donne, long-only.

    Seuls les actifs a score strictement positif recoivent un poids,
    proportionnel a leur score et normalise a somme 1. top_n limite le
    nombre d'actifs retenus (les plus forts scores) pour concentrer le
    capital plutot que le disperser sur un signal marginal.
    """
    positive = scores_row[scores_row > 0].dropna()

    if top_n is not None and len(positive) > top_n:
        positive = positive.sort_values(ascending=False).head(top_n)

    weights = pd.Series(0.0, index=scores_row.index)
    if not positive.empty:
        weights.loc[positive.index] = positive / positive.sum()
    return weights


def compute_target_weights_history(raw_scores: pd.DataFrame, top_n: Optional[int] = None) -> pd.DataFrame:
    """Applique target_weights_row a chaque instant de l'historique."""
    return raw_scores.apply(lambda row: target_weights_row(row, top_n=top_n), axis=1)
