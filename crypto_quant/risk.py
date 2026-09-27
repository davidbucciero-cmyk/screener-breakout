"""Risque et sizing (etape 4).

Transforme les poids relatifs de l'etape 3 (bases sur le score, somme=1) en
tailles de position reelles, avec plusieurs garde-fous :

- tilt par volatilite inverse : equilibre la contribution au risque entre
  actifs, pas seulement au score.
- ciblage de volatilite : determine combien de capital total deployer,
  plafonne a 1.0 (spot, pas de levier possible/souhaite).
- Kelly fractionnaire : plafond de securite par position, a partir de
  statistiques de trades REELS (win rate, payoff ratio) - pas invente a
  partir du score, calcule en walk-forward a l'etape 5.
- stop-loss ATR : distance de stop adaptee a la volatilite recente de
  chaque actif.
- coupe-circuit de drawdown : suspend les nouvelles positions apres une
  perte importante, avec hysteresis pour eviter les allers-retours.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def inverse_vol_weights(score_weights: pd.Series, vol_estimates: pd.Series) -> pd.Series:
    """Retilte des poids (somme=1) par l'inverse de la volatilite de chaque actif.

    Un actif deux fois plus volatil qu'un autre a poids-score egal recoit
    deux fois moins de capital, pour egaliser sa contribution au risque du
    portefeuille plutot que sa contribution au score brut.
    """
    active = score_weights[score_weights > 0]
    if active.empty:
        return pd.Series(0.0, index=score_weights.index)

    vols = vol_estimates.reindex(active.index)
    inv_vol = 1.0 / vols.replace(0, np.nan)

    tilted = active * inv_vol
    tilted = tilted.dropna()
    if tilted.empty or tilted.sum() == 0:
        return pd.Series(0.0, index=score_weights.index)

    result = pd.Series(0.0, index=score_weights.index)
    result.loc[tilted.index] = tilted / tilted.sum()
    return result


def portfolio_volatility_estimate(weights: pd.Series, vol_estimates: pd.Series) -> float:
    """Estimation CONSERVATRICE de la volatilite du portefeuille.

    Somme ponderee des vols individuelles (equivaut a supposer une
    correlation de +1 entre tous les actifs). Ignore le benefice de
    diversification, donc surestime le risque reel si les actifs ne sont
    pas parfaitement correles - un biais prudent plutot qu'optimiste, choisi
    volontairement pour eviter de sous-estimer le risque en l'absence d'une
    matrice de correlation fiable.
    """
    vols = vol_estimates.reindex(weights.index).fillna(0.0)
    return float((weights * vols).sum())


def volatility_target_leverage(
    weights: pd.Series,
    vol_estimates: pd.Series,
    target_vol: float,
    max_leverage: float = 1.0,
) -> float:
    """Facteur de levier a appliquer aux poids pour cibler une vol de portefeuille.

    Plafonne a max_leverage (1.0 par defaut : jamais plus de 100% du capital
    en spot, impossible d'emprunter pour lever un compte Kraken standard).
    """
    portfolio_vol = portfolio_volatility_estimate(weights, vol_estimates)
    if portfolio_vol <= 0:
        return 0.0
    return float(min(max_leverage, target_vol / portfolio_vol))


def kelly_fraction(win_rate: float, payoff_ratio: float, kelly_cap: float = 0.25) -> float:
    """Fraction de Kelly, plafonnee (Kelly fractionnaire) pour la robustesse.

    f* = p - (1-p)/b     avec p=win_rate, b=payoff_ratio (gain moyen / perte moyenne)

    Le Kelly plein est tres sensible aux erreurs d'estimation de p et b (des
    estimations legerement optimistes suffisent a produire un f* qui ruine le
    compte). kelly_cap borne le resultat a une fraction du Kelly plein (0.25
    = quart de Kelly, pratique standard). Renvoie 0 si l'edge est negatif ou
    payoff_ratio invalide, jamais une fraction negative.
    """
    if payoff_ratio <= 0:
        return 0.0
    full_kelly = win_rate - (1 - win_rate) / payoff_ratio
    if full_kelly <= 0:
        return 0.0
    return float(full_kelly * kelly_cap)


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Average True Range : amplitude de bougie moyenne, tient compte des gaps.

    True Range = max(high-low, |high-close_precedent|, |low-close_precedent|)
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean().rename("atr")


def atr_stop_loss_price(entry_price: float, atr_value: float, direction: int = 1, atr_mult: float = 2.0) -> float:
    """Prix de stop-loss a partir de l'ATR. direction=1 (long) ou -1 (short, non utilise en spot)."""
    return entry_price - direction * atr_mult * atr_value


class DrawdownCircuitBreaker:
    """Coupe-circuit avec hysteresis : suspend les nouvelles positions apres
    une perte importante, ne reprend qu'apres recuperation partielle OU un
    delai de reprise (cooldown_periods).

    Le cooldown est necessaire : une fois totalement en cash, l'equity ne
    bouge plus du tout (aucune position = aucun gain/perte), donc la
    condition "drawdown remonte au-dessus de -resume_drawdown" ne peut
    JAMAIS se declencher toute seule (le drawdown reste fige a sa valeur de
    declenchement pour toujours). Sans cooldown, la strategie resterait
    plate indefiniment des le premier coupe-circuit, meme si le marche se
    redresse completement pendant qu'on est a l'ecart.

    A la reprise (recuperation ou cooldown), le pic de reference est
    reinitialise au niveau d'equity courant : on ne exige pas de rattraper
    l'ancien pic historique (potentiellement tres eloigne, voire jamais
    rattrapable apres une perte importante), on repart avec un nouveau
    plus-haut a partir de la reprise.
    """

    def __init__(self, halt_drawdown: float = 0.20, resume_drawdown: float = 0.10, cooldown_periods: int = 24):
        if resume_drawdown >= halt_drawdown:
            raise ValueError("resume_drawdown doit etre strictement inferieur a halt_drawdown")
        self.halt_drawdown = halt_drawdown
        self.resume_drawdown = resume_drawdown
        self.cooldown_periods = cooldown_periods
        self.reset()

    def reset(self) -> None:
        """Reinitialise l'etat interne (a appeler avant une nouvelle simulation)."""
        self._running_max = None
        self._halted = False
        self._periods_since_halt = 0

    def step(self, equity_value: float) -> bool:
        """Usage incremental (backtest pas-a-pas) : met a jour l'etat avec une
        nouvelle valeur d'equity, renvoie True si le trading est autorise."""
        if self._running_max is None or equity_value > self._running_max:
            self._running_max = equity_value

        drawdown = (equity_value - self._running_max) / self._running_max

        if not self._halted and drawdown <= -self.halt_drawdown:
            self._halted = True
            self._periods_since_halt = 0
        elif self._halted:
            self._periods_since_halt += 1
            recovered = drawdown >= -self.resume_drawdown
            cooldown_elapsed = self._periods_since_halt >= self.cooldown_periods
            if recovered or cooldown_elapsed:
                self._halted = False
                self._running_max = equity_value

        return not self._halted

    def evaluate(self, equity_curve: pd.Series) -> pd.Series:
        """Usage vectorise (analyse a posteriori) : renvoie une Series
        booleenne 'trading_allowed', meme index que equity_curve."""
        self.reset()
        allowed = [self.step(v) for v in equity_curve.values]
        return pd.Series(allowed, index=equity_curve.index, name="trading_allowed")

    def to_dict(self) -> dict:
        """Serialise l'etat interne (pour persistance entre executions live,
        cf. execution.py : un processus relance periodiquement doit retrouver
        son etat de coupe-circuit, pas repartir a zero a chaque fois)."""
        return {
            "halt_drawdown": self.halt_drawdown,
            "resume_drawdown": self.resume_drawdown,
            "cooldown_periods": self.cooldown_periods,
            "running_max": self._running_max,
            "halted": self._halted,
            "periods_since_halt": self._periods_since_halt,
        }

    @classmethod
    def from_dict(cls, state: dict) -> "DrawdownCircuitBreaker":
        breaker = cls(
            halt_drawdown=state["halt_drawdown"],
            resume_drawdown=state["resume_drawdown"],
            cooldown_periods=state["cooldown_periods"],
        )
        breaker._running_max = state["running_max"]
        breaker._halted = state["halted"]
        breaker._periods_since_halt = state["periods_since_halt"]
        return breaker
