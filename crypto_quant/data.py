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
from typing import Dict, List, Optional

import pandas as pd

log = logging.getLogger(__name__)

OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
TRADE_COLUMNS = ["id", "timestamp", "price", "amount"]


def _slugify(symbol: str) -> str:
    return symbol.replace("/", "").lower()


def build_exchange(exchange_id: str = "kraken"):
    """Construit un client ccxt reel pour l'exchange demande."""
    import ccxt

    exchange_class = getattr(ccxt, exchange_id)
    return exchange_class({"enableRateLimit": True})


def _call_with_retry(fn, max_retries: int = 5, base_delay: float = 2.0):
    """Reessaie un appel reseau avec backoff exponentiel sur une erreur
    reseau TRANSITOIRE (ccxt.NetworkError et sous-classes : proxy coupe,
    timeout, DNS...). Ne rattrape jamais une erreur applicative (mauvais
    symbole, auth, etc.) pour ne pas masquer un vrai bug derriere des
    reessais silencieux.

    Trouve en conditions reelles : un fetch d'historique profond (des
    heures d'appels sequentiels) a plante des le debut sur une coupure
    proxy transitoire (connexion refusee), perdant toute la progression en
    memoire faute de retry. Necessaire des qu'une boucle de pagination
    tourne assez longtemps pour croiser un incident reseau transitoire.
    """
    import ccxt

    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except ccxt.NetworkError:
            if attempt == max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            log.warning(
                "Erreur reseau transitoire (tentative %d/%d), nouvel essai dans %.0fs",
                attempt, max_retries, delay,
            )
            time.sleep(delay)


def resample_trades_to_ohlcv(trades: pd.DataFrame, timeframe_seconds: int) -> pd.DataFrame:
    """Reconstruit des bougies OHLCV a partir de trades individuels.

    Utilise pour contourner la limite de l'endpoint OHLC public de Kraken
    (~720 dernieres bougies seulement, quel que soit `since` demande - voir
    README etape 7) : l'endpoint Trades, lui, honore un `since` ancien, donc
    on peut reconstruire un historique de bougies bien plus profond a partir
    des trades bruts.

    Limite assumee : une bougie sans aucun trade (illiquidite totale sur la
    periode) est absente du resultat plutot que remplie a 0/forward-fill -
    coherent avec le reste du pipeline qui traite une bougie manquante comme
    une donnee absente, pas comme un volume nul.
    """
    if trades.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = trades.copy()
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("datetime").sort_index()

    freq = pd.Timedelta(seconds=timeframe_seconds)
    ohlc = df["price"].resample(freq, origin="epoch").ohlc()
    volume = df["amount"].resample(freq, origin="epoch").sum()
    bars = ohlc.join(volume.rename("volume"))
    return bars.dropna(subset=["open"])


def largest_contiguous_segment(
    price_data: Dict[str, pd.DataFrame], max_gap_multiple: float = 3.0
) -> Dict[str, pd.DataFrame]:
    """Detecte les trous de calendrier dans l'univers (ex: suspension du
    trading USD sur Binance.US, 14 juillet 2023 -> 19 fevrier 2025 suite au
    proces SEC de juin 2023) et renvoie UNIQUEMENT le plus grand segment
    continu commun a tous les actifs.

    Sans ce filtre, backtest.run_backtest (qui itere par POSITION, pas par
    date - cf. sa docstring) traiterait un ecart de plusieurs mois entre
    deux bougies consecutives comme le rendement d'une SEULE periode : un
    trou de 586 bougies entre deux cloture de BTC/USD separees de 285% dans
    les faits deviendrait un "rendement d'une bougie" de +285%, contaminant
    silencieusement tous les calculs de signaux et de P&L autour de ce point
    (cf. README, etape 13 bis - c'est exactement ce qui s'est produit avant
    detection).

    max_gap_multiple : un ecart entre deux bougies consecutives de l'index
    COMMUN (intersection de tous les actifs fournis) est considere comme un
    "trou" s'il depasse ce multiple du pas le plus frequent (le mode des
    ecarts, robuste aux quelques irregularites mineures qui ne signalent pas
    un vrai probleme).

    Renvoie toujours les actifs alignes sur un index COMMUN (intersection),
    meme quand aucun trou n'est detecte - ne pas le faire renverrait les
    DataFrames bruts non alignes (chaque actif gardant sa propre plage de
    dates), pas juste "la meme chose sans trou".
    """
    common_index = None
    for df in price_data.values():
        common_index = df.index if common_index is None else common_index.intersection(df.index)
    common_index = common_index.sort_values()

    if len(common_index) < 3:
        return {symbol: df.loc[common_index] for symbol, df in price_data.items()}

    gaps = common_index[1:] - common_index[:-1]
    modal_step = pd.Series(gaps).mode().iloc[0]
    gap_threshold = modal_step * max_gap_multiple

    break_positions = [i + 1 for i, g in enumerate(gaps) if g > gap_threshold]
    if not break_positions:
        return {symbol: df.loc[common_index] for symbol, df in price_data.items()}

    boundaries = [0] + break_positions + [len(common_index)]
    segments = [common_index[boundaries[i] : boundaries[i + 1]] for i in range(len(boundaries) - 1)]
    largest = max(segments, key=len)

    log.warning(
        "largest_contiguous_segment : %d trou(s) de calendrier detecte(s) (seuil=%s, pas typique=%s) - "
        "segment retenu : %s -> %s (%d bougies sur %d au total dans l'intersection)",
        len(segments) - 1,
        gap_threshold,
        modal_step,
        largest[0],
        largest[-1],
        len(largest),
        len(common_index),
    )

    return {symbol: df.loc[largest] for symbol, df in price_data.items()}


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
            batch = _call_with_retry(lambda: self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=limit))
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

    # -----------------------------------------------------------------
    # Historique profond via les trades bruts (etape 7 bis) : l'endpoint
    # OHLC public de Kraken ne sert que les ~720 dernieres bougies quel que
    # soit `since` (verifie manuellement), mais son endpoint Trades honore
    # un `since` ancien. On pagine sur les trades et on reconstruit les
    # bougies localement (resample_trades_to_ohlcv) pour obtenir un
    # historique bien plus profond que via fetch_ohlcv.
    # -----------------------------------------------------------------

    def _trades_cache_path(self, symbol: str) -> str:
        return os.path.join(self.cache_dir, f"{self.exchange_id}_{_slugify(symbol)}_trades.csv")

    def _load_trades_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self._trades_cache_path(symbol)
        if not os.path.exists(path):
            return None
        # dtype={"id": str} est essentiel : ccxt renvoie des id de trade en
        # str (ex: "74968999"), mais pandas infererait sinon un int64 a la
        # lecture du CSV (l'id "ressemble" a un nombre). Sans ca, drop_duplicates
        # sur "id" ne matche jamais le cache relu (int) contre les trades
        # fraichement recuperes (str) - meme trade, deux types differents,
        # duplique silencieusement a chaque appel (trouve via les tests).
        df = pd.read_csv(path, dtype={"id": str})
        if df.empty:
            return None
        return df

    def _save_trades_cache(self, symbol: str, df: pd.DataFrame) -> None:
        df.to_csv(self._trades_cache_path(symbol), index=False)

    def _fetch_trades_paginated(
        self,
        symbol: str,
        since_ms: int,
        until_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[dict]:
        """Pagine fetch_trades en avancant sur le timestamp du dernier trade.

        Limite connue et assumee : pour Kraken, ccxt tronque `since` a la
        seconde avant l'envoi (le vrai curseur natif de pagination de
        Kraken est un nonce en nanosecondes, non expose par ccxt). On ne
        peut donc pas avancer le curseur en toute confiance avec un simple
        `+1ms` sans risquer de sauter des trades partageant la meme
        seconde a la frontiere d'une page. A la place, on re-interroge a
        partir du timestamp EXACT du dernier trade recu (pas +1) et on
        deduplique par `id` - au prix de quelques trades redemandes en
        double a chaque page (filtres via `seen_ids`), pour ne jamais rien
        sauter. Si deux pages consecutives renvoient exactement les memes
        trades (aucun trade au-dela), on force une avance minimale pour
        eviter une boucle infinie - au risque, tres rare, de sauter les
        tout derniers trades d'une seconde extremement active.

        Important : contrairement a l'OHLC (bougies a intervalle fixe, donc
        un batch plus petit que `limit` signifie sans ambiguite "on a
        atteint le present"), un batch de trades plus petit que `limit` ne
        le signifie PAS forcement - verifie sur Kraken reel : un appel peut
        renvoyer beaucoup moins de trades que demande tout en etant a des
        jours du present (la reponse peut etre bornee autrement que par le
        compte demande). On ne s'arrete donc QUE sur un batch reellement
        vide ou sur `until_ms` atteint, jamais sur `len(batch) < limit`.
        """
        all_trades: List[dict] = []
        seen_ids = set()
        cursor = since_ms

        while True:
            batch = _call_with_retry(lambda: self.exchange.fetch_trades(symbol, since=cursor, limit=limit))
            if not batch:
                break
            new_trades = [t for t in batch if t["id"] not in seen_ids]
            if not new_trades:
                break
            all_trades.extend(new_trades)
            seen_ids.update(t["id"] for t in new_trades)

            last_ts = new_trades[-1]["timestamp"]
            if until_ms is not None and last_ts >= until_ms:
                break

            next_cursor = last_ts if last_ts > cursor else cursor + 1
            cursor = next_cursor
            if getattr(self.exchange, "rateLimit", None):
                time.sleep(self.exchange.rateLimit / 1000)

        return all_trades

    def get_trades_history(
        self,
        symbol: str,
        history_days: int,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Renvoie les trades individuels sur la fenetre demandee, en
        completant le cache (meme logique de backfill/extension qu'a
        get_history, voir README etape 7 pour le bug historique corrige)."""
        now_ms = int(time.time() * 1000)
        earliest_wanted_ms = now_ms - history_days * 24 * 60 * 60 * 1000

        cached = None if force_refresh else self._load_trades_cache(symbol)

        new_frames = []
        if cached is not None and not cached.empty:
            first_cached_ts = int(cached["timestamp"].min())
            last_cached_ts = int(cached["timestamp"].max())

            if earliest_wanted_ms < first_cached_ts:
                backfill = self._fetch_trades_paginated(symbol, earliest_wanted_ms, until_ms=first_cached_ts)
                if backfill:
                    new_frames.append(pd.DataFrame(backfill)[TRADE_COLUMNS])

            forward = self._fetch_trades_paginated(symbol, last_cached_ts)
            if forward:
                new_frames.append(pd.DataFrame(forward)[TRADE_COLUMNS])
        else:
            all_new = self._fetch_trades_paginated(symbol, earliest_wanted_ms)
            if all_new:
                new_frames.append(pd.DataFrame(all_new)[TRADE_COLUMNS])

        if new_frames:
            combined = pd.concat(([cached] if cached is not None and not cached.empty else []) + new_frames, ignore_index=True)
        else:
            combined = cached if cached is not None else pd.DataFrame(columns=TRADE_COLUMNS)

        combined = combined.drop_duplicates(subset="id").sort_values("timestamp").reset_index(drop=True)
        self._save_trades_cache(symbol, combined)

        return combined[combined["timestamp"] >= earliest_wanted_ms].reset_index(drop=True)

    def get_history_from_trades(
        self,
        symbol: str,
        timeframe: str,
        history_days: int,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Comme get_history, mais reconstruit les bougies a partir des
        trades bruts pour depasser la limite ~720 bougies de l'endpoint
        OHLC de Kraken. Meme format de sortie (index datetime, colonnes
        OHLCV) que get_history, donc utilisable de facon interchangeable
        partout ailleurs dans le pipeline (backtest, signaux, etc.)."""
        trades = self.get_trades_history(symbol, history_days, force_refresh=force_refresh)
        tf_seconds = self.exchange.parse_timeframe(timeframe)
        return resample_trades_to_ohlcv(trades, tf_seconds)

    def get_universe_history_from_trades(
        self,
        symbols: List[str],
        timeframe: str,
        history_days: int,
    ) -> dict:
        """Equivalent de get_universe_history, via les trades bruts."""
        out = {}
        for symbol in symbols:
            log.info("Fetching %s %s from trades (%d days)", symbol, timeframe, history_days)
            out[symbol] = self.get_history_from_trades(symbol, timeframe, history_days)
        return out
