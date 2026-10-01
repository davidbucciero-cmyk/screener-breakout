"""Carry BTC : spread neutre au marche entre le perpetuel et le spot
Kraken (etape 22). Parie sur la convergence du basis (ecart perpetuel/
spot) vers sa propre moyenne glissante, pas sur le sens du BTC - long
spot/short perpetuel quand le perpetuel est cher, l'inverse quand il
est bon marche.

Pourquoi Kraken pour les DEUX jambes : une premiere version comparant le
spot Binance.US au perpetuel Deribit (deux exchanges differents) etait
dominee par du bruit inter-exchange (ecart-type ~159 bps/jour, signe qui
change chaque annee) plutot que par le vrai basis - en restant sur UN
SEUL exchange pour les deux jambes, l'ecart-type tombe a ~14 bps/jour et
la relation (z-score du basis -> rendement du spread du lendemain) est
stable et forte (correlation ~-0.6, verifiee stable sur un split en deux
moities independantes et sur plusieurs fenetres de z-score de 10 a 90
jours).

Pourquoi le PERPETUEL et pas les futures trimestriels dates : teste et
explicitement ecarte - le volume quotidien median des trimestriels Kraken
(0.6 a 13.5 BTC) est 150 000x a 3 000 000x plus faible que celui du
perpetuel (~2 100 000 BTC), au point que leurs cloture journalieres ne
sont pas des prix de marche fiables (un Sharpe backtest ~4-5 sur les
trimestriels s'est revele etre un artefact d'illiquidite, pas un edge
reel).

Limites assumees (detaillees dans README.md, etape 22) :
- Fenetre reelle ~2 ans seulement : l'API publique Kraken (spot ET
  futures) plafonne a ~720-ish bougies quel que soit `since` demande
  (meme limite deja documentee pour le spot a l'etape 7) - pas les 6+
  folds dont beneficie l'or (25 ans).
- Strategie sensible au cout de transaction : bascule nette (Sharpe
  >0 -> <0) entre 5 et 8 bps de cout aller-retour SANS la bande
  sans-trade ; avec elle, reste positive meme a 8 bps sur 2 folds/3.
- Necessite une infra de vente a decouvert (comme le spread or de
  l'etape 21 quater) - mais Kraken Futures supporte nativement le short
  (pas d'emprunt de titres comme pour un ETF), donc c'est un chantier
  d'execution, pas un obstacle structurel.
- Walk-forward 3 folds seulement : fold 1 (periode de basis
  particulierement calme) reste inconclusif (p-value SPA 0.625-0.737
  selon la config) meme apres la porte de volatilite - pas un echec du
  signal (correlease stable dans ce fold aussi), mais un regime ou le
  cout fixe de turnover a depasse l'edge disponible.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .risk import DrawdownCircuitBreaker


@dataclass
class BTCCarryConfig:
    z_window: int = 30
    clip_z: float = 3.0
    vol_threshold_bps: float = 12.0
    vol_gate_window: int = 20
    no_trade_band: float = 0.5
    # Frais reels verifies separement par jambe (etape 22 quinquies) - PAS le
    # meme taux des deux cotes : Kraken Futures (PI_XBTUSD) facture 0.02%
    # maker / 0.05% taker, mais le Kraken SPOT CLASSIQUE facture 0.16%
    # maker / 0.26% taker - 5x plus cher. Une premiere version de ce module
    # appliquait a tort le taux futures aux DEUX jambes (round-trip modelise
    # a 10bps) - corrige : round-trip reel = spot_fee + perp_fee.
    # Defauts = MAKER des deux cotes (18bps round-trip) car c'est le SEUL
    # regime qui reste rentable (Sharpe walk-forward ~0.49, contre -1.85 en
    # taker/taker a 31bps) - voir README etape 22 quinquies pour le detail
    # par scenario. Le bot de paper trading ne genere jamais d'ordre reel,
    # donc ce choix documente surtout la condition de viabilite d'un futur
    # passage au reel, pas un comportement observe.
    spot_fee_bps: float = 16.0
    perp_fee_bps: float = 2.0


def basis_bps(spot: pd.Series, perp: pd.Series) -> pd.Series:
    """Ecart perpetuel/spot en points de base, memes exchange/devise des
    deux cotes - voir docstring module sur l'importance de la meme
    venue."""
    return (perp / spot - 1) * 10000


def basis_zscore(spot: pd.Series, perp: pd.Series, window: int = 30) -> pd.Series:
    """Z-score glissant du basis (moyenne/ecart-type sur `window` jours
    PASSES, aucune fuite vers le futur)."""
    b = basis_bps(spot, perp)
    mean = b.rolling(window, min_periods=10).mean()
    std = b.rolling(window, min_periods=10).std()
    return (b - mean) / std


def basis_vol_gate(spot: pd.Series, perp: pd.Series, vol_threshold_bps: float, window: int = 20) -> pd.Series:
    """Porte binaire : n'autorise le trading que si la volatilite RECENTE
    du basis (ecart-type glissant, bps) depasse un seuil.

    Diagnostic (etape 22 bis) : le turnover de l'exposition continue
    -z/clip_z est quasi fixe quel que soit le regime de marche (pilote
    par le bruit jour-a-jour du z-score), alors que le profit brut est
    proportionnel a la volatilite REELLE du basis - dans un regime de
    basis trop calme, le cout fixe depasse l'edge disponible. Mieux vaut
    rester plat que de continuer a trader a perte."""
    recent_vol = basis_bps(spot, perp).rolling(window, min_periods=10).std()
    return (recent_vol > vol_threshold_bps).astype(float)


def carry_spread_equity(spot: pd.Series, perp: pd.Series, config: BTCCarryConfig = BTCCarryConfig()) -> pd.Series:
    """Backtest du spread neutre au marche (long spot/short perpetuel ou
    l'inverse selon le signe du basis). `spot` et `perp` doivent partager
    le meme index (deja aligne par l'appelant - voir
    `crypto_quant/data.py:CCXTDataFeed` pour la recuperation).

    Position = exposition continue bornee a [-1,1] proportionnelle a
    -z/clip_z (pas un seuil+levier cible de vol - une premiere version
    avec levier cible de vol a 5x detruisait completement le signal par
    sur-cout de turnover sur une vol de spread tres faible), filtree par
    la porte de volatilite, puis lissee par une bande sans-trade (ne
    rebalance que si l'exposition cible s'ecarte de la position courante
    de plus que `no_trade_band` - reduit le turnover de dithering
    quotidien ~7x sans detruire l'edge, etape 22 ter)."""
    z = basis_zscore(spot, perp, config.z_window)
    gate = (
        basis_vol_gate(spot, perp, config.vol_threshold_bps, config.vol_gate_window)
        if config.vol_threshold_bps > 0
        else 1.0
    )
    target_exposure = (-z.clip(-config.clip_z, config.clip_z) / config.clip_z).clip(-1, 1) * gate
    spread_return = perp.pct_change() - spot.pct_change()
    target = target_exposure.shift(1).fillna(0.0)

    # Round-trip = somme des DEUX frais reels (pas le meme taux double -
    # cf. docstring BTCCarryConfig, correction etape 22 quinquies).
    round_trip_bps = config.spot_fee_bps + config.perp_fee_bps

    breaker = DrawdownCircuitBreaker(halt_drawdown=0.20, resume_drawdown=0.10, cooldown_periods=5)
    equity = np.empty(len(spot))
    cash_equity = 10_000.0
    prev_pos = 0.0
    for i in range(len(spot)):
        allowed = breaker.step(cash_equity)
        tgt = target.iloc[i] if allowed else 0.0
        pos = tgt if abs(tgt - prev_pos) > config.no_trade_band else prev_pos
        turnover = abs(pos - prev_pos)
        cost = turnover * round_trip_bps / 10_000
        ret = pos * spread_return.iloc[i] if np.isfinite(spread_return.iloc[i]) else 0.0
        cash_equity *= 1 + ret - cost
        equity[i] = cash_equity
        prev_pos = pos

    return pd.Series(equity, index=spot.index, name="equity")
