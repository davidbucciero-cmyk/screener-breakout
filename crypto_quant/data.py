"""Recuperation de donnees OHLCV crypto via ccxt, avec cache local sur disque.

Le client d'exchange est injectable (`exchange_client`) : en production on
passe un vrai `ccxt.kraken()`, dans les tests on passe un faux client qui
retourne des donnees synthetiques. Ca permet de tester toute la logique de
pagination/cache sans jamais toucher le reseau.
"""
from __future__ import annotations

import logging
import os
import time
from typing import List, Optional

import pandas as pd

log = logging.getLogger(__name__)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def _slugify(symbol: str) -> str:
    return symbol.replace("/", "").lower()


def build_exchange(exchange_id: str = "kraken"):
    """Construit un client ccxt reel pour l'exchange demande."""
    import ccxt

    exchange_class = getattr(ccxt, exchange_id)
    return exchange_class({"enableRateLimit": True})


class CCXTDataFeed:
    """Recupere et met en cache l'historique OHLCV d'une liste de paires."""

    def __init__(
        self,
        exchange_id: str = "kraken",
        cache_dir: str = "crypto_quant/data_cache",
        exchange_client=None,
    ):
        self.exchange_id = exchange_id
        self.cache_dir = cache_dir
        self.exchange = exchange_client if exchange_client is not None else build_exchange(exchange_id)
        os.makedirs(self.cache_dir, exist_ok=True)

    def _cache_path(self, symbol: str, timeframe: str) -> str:
        return os.path.join(self.cache_dir, f"{self.exchange_id}_{_slugify(symbol)}_{timeframe}.csv")

    def _load_cache(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        path = self._cache_path(symbol, timeframe)
        if not os.path.exists(path):
            return None
        df = pd.read_csv(path)
        if df.empty:
            return None
        return df

    def _save_cache(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        path = self._cache_path(symbol, timeframe)
        df.to_csv(path, index=False)

    def _fetch_ohlcv_paginated(
        self,
        symbol: str,
        timeframe: str,
        since_ms: int,
        until_ms: Optional[int] = None,
        limit: int = 720,
    ) -> List[list]:
        """Boucle sur fetch_ohlcv tant que l'exchange renvoie des donnees.

        ccxt limite chaque appel a `limit` bougies : il faut donc paginer en
        avancant `since` a chaque iteration jusqu'a atteindre `until_ms` (ou
        jusqu'a ce que l'exchange n'ait plus rien a renvoyer).
        """
        all_rows: List[list] = []
        cursor = since_ms
        tf_seconds = self.exchange.parse_timeframe(timeframe)
        tf_ms = tf_seconds * 1000

        while True:
            batch = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit)
            if not batch:
                break
            all_rows.extend(batch)
            last_ts = batch[-1][0]
            next_cursor = last_ts + tf_ms
            if next_cursor <= cursor:
                # Garde-fou anti boucle infinie si l'exchange renvoie
                # toujours la meme derniere bougie.
                break
            cursor = next_cursor
            if until_ms is not None and cursor >= until_ms:
                break
            if len(batch) < limit:
                # Moins de bougies que demande = on a atteint le present.
                break
            if getattr(self.exchange, "rateLimit", None):
                time.sleep(self.exchange.rateLimit / 1000)

        return all_rows

    def get_history(
        self,
        symbol: str,
        timeframe: str,
        history_days: int = 730,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Renvoie l'historique OHLCV complet demande, en completant le cache.

        Ne re-telecharge que les bougies manquantes : en avant depuis la
        derniere execution, ET en arriere si `history_days` demande remonte
        plus loin que ce que le cache couvre deja (sinon un premier appel
        avec un `history_days` petit plafonnerait silencieusement tous les
        appels suivants, meme avec un `history_days` plus grand).
        """
        now_ms = int(time.time() * 1000)
        earliest_wanted_ms = now_ms - history_days * 24 * 60 * 60 * 1000

        cached = None if force_refresh else self._load_cache(symbol, timeframe)

        new_frames = []
        if cached is not None and not cached.empty:
            first_cached_ts = int(cached["timestamp"].min())
            last_cached_ts = int(cached["timestamp"].max())

            if earliest_wanted_ms < first_cached_ts:
                backfill_rows = self._fetch_ohlcv_paginated(
                    symbol, timeframe, earliest_wanted_ms, until_ms=first_cached_ts
                )
                if backfill_rows:
                    new_frames.append(pd.DataFrame(backfill_rows, columns=OHLCV_COLUMNS))

            forward_rows = self._fetch_ohlcv_paginated(symbol, timeframe, last_cached_ts + 1)
            if forward_rows:
                new_frames.append(pd.DataFrame(forward_rows, columns=OHLCV_COLUMNS))
        else:
            all_rows = self._fetch_ohlcv_paginated(symbol, timeframe, earliest_wanted_ms)
            if all_rows:
                new_frames.append(pd.DataFrame(all_rows, columns=OHLCV_COLUMNS))

        if new_frames:
            combined = pd.concat(([cached] if cached is not None and not cached.empty else []) + new_frames, ignore_index=True)
        else:
            combined = cached if cached is not None else pd.DataFrame(columns=OHLCV_COLUMNS)

        combined = combined.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
        self._save_cache(symbol, timeframe, combined)

        result = combined[combined["timestamp"] >= earliest_wanted_ms].copy()
        result["datetime"] = pd.to_datetime(result["timestamp"], unit="ms", utc=True)
        result = result.set_index("datetime").drop(columns=["timestamp"])
        return result

    def get_universe_history(
        self,
        symbols: List[str],
        timeframe: str,
        history_days: int = 730,
    ) -> dict:
        """Renvoie {symbol: DataFrame} pour toute une liste de paires."""
        out = {}
        for symbol in symbols:
            log.info("Fetching %s %s (%d days)", symbol, timeframe, history_days)
            out[symbol] = self.get_history(symbol, timeframe, history_days)
        return out
