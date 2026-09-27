"""Configuration centrale du systeme de trading quant crypto.

Toutes les valeurs par defaut sont volontairement prudentes : petit univers
liquide, timeframe 1h (pas de HFT), execution en dry-run.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class UniverseConfig:
    exchange: str = "kraken"
    pairs: List[str] = field(
        default_factory=lambda: ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "XRP/USD"]
    )
    timeframe: str = "1h"


@dataclass
class DataConfig:
    cache_dir: str = "crypto_quant/data_cache"
    history_days: int = 730  # ~2 ans d'historique par defaut


@dataclass
class Config:
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    data: DataConfig = field(default_factory=DataConfig)
