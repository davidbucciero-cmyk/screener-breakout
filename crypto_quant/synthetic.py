"""Generateur de donnees OHLCV synthetiques.

Sert a deux choses :
1. Tester tout le pipeline (cache, signaux, backtest) sans acces reseau.
2. Fournir un faux client "ccxt-like" injectable dans CCXTDataFeed pour
   tester la logique de pagination/cache de data.py.

Le prix est simule comme une marche aleatoire log-normale (mouvement
brownien geometrique) a laquelle on ajoute une composante de retour a la
moyenne (Ornstein-Uhlenbeck) : ca donne une serie qui a a la fois de la
tendance et du mean-reversion, utile pour tester les signaux des etapes
suivantes.
"""
from __future__ import annotations

import time
from typing import List, Optional

import numpy as np
import pandas as pd


def generate_synthetic_ohlcv(
    n_periods: int,
    timeframe_seconds: int,
    start_price: float = 100.0,
    drift: float = 0.0,
    gbm_vol: float = 0.01,
    ou_theta: float = 0.05,
    ou_sigma: float = 0.005,
    seed: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> List[list]:
    """Renvoie une liste de bougies au format ccxt : [ts_ms, o, h, l, c, v].

    log_price[t] = log_price[t-1] + drift + gbm_vol * N(0,1)      (tendance/bruit)
                   + ou_component[t]                               (retour a la moyenne)
    ou_component suit dX = -theta * X dt + sigma * dW (Ornstein-Uhlenbeck discretise).
    """
    rng = np.random.default_rng(seed)

    gbm_shocks = rng.normal(loc=drift, scale=gbm_vol, size=n_periods)
    log_price = np.cumsum(gbm_shocks) + np.log(start_price)

    ou = np.zeros(n_periods)
    for t in range(1, n_periods):
        ou[t] = ou[t - 1] - ou_theta * ou[t - 1] + rng.normal(0, ou_sigma)

    log_close = log_price + ou
    close = np.exp(log_close)

    # Bougies OHLC approximees a partir du close (suffisant pour tester la
    # logique de donnees/signaux, pas destine a etre un vrai simulateur de
    # microstructure de marche).
    open_ = np.concatenate([[start_price], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, gbm_vol / 2, n_periods)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, gbm_vol / 2, n_periods)))
    volume = rng.lognormal(mean=10, sigma=0.5, size=n_periods)

    if end_ms is None:
        end_ms = int(time.time() * 1000)
    tf_ms = timeframe_seconds * 1000
    timestamps = end_ms - (n_periods - 1 - np.arange(n_periods)) * tf_ms

    rows = [
        [int(ts), float(o), float(h), float(l), float(c), float(v)]
        for ts, o, h, l, c, v in zip(timestamps, open_, high, low, close, volume)
    ]
    return rows


class FakeExchange:
    """Faux client ccxt : sert des bougies synthetiques pre-generees.

    Reproduit juste assez de l'interface ccxt (fetch_ohlcv, parse_timeframe,
    rateLimit) pour que CCXTDataFeed puisse etre teste sans reseau.
    """

    TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}

    def __init__(self, all_rows: List[list]):
        # Tri par timestamp pour permettre une recherche par "since" fiable.
        self._rows = sorted(all_rows, key=lambda r: r[0])
        self.rateLimit = 0  # pas de sleep dans les tests

    def parse_timeframe(self, timeframe: str) -> int:
        return self.TIMEFRAME_SECONDS[timeframe]

    def fetch_ohlcv(self, symbol: str, timeframe: str, since: int, limit: int) -> List[list]:
        candidates = [r for r in self._rows if r[0] >= since]
        return candidates[:limit]


def synthetic_dataframe(n_periods: int, timeframe: str = "1h", seed: Optional[int] = None) -> pd.DataFrame:
    """Raccourci : genere directement un DataFrame OHLCV indexe par date."""
    tf_seconds = FakeExchange.TIMEFRAME_SECONDS[timeframe]
    rows = generate_synthetic_ohlcv(n_periods, tf_seconds, seed=seed)
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("datetime").drop(columns=["timestamp"])
