"""Tests du module data.py : pagination et cache, sans acces reseau.

Utilise FakeExchange (synthetic.py) a la place d'un vrai client ccxt pour
verifier que CCXTDataFeed pagine correctement et ne re-telecharge que les
bougies manquantes lors d'un second appel.
"""
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import patch

import ccxt
import pandas as pd

from crypto_quant.data import CCXTDataFeed, largest_contiguous_segment, resample_trades_to_ohlcv
from crypto_quant.synthetic import FakeExchange, FakeTradesExchange, generate_synthetic_ohlcv, generate_synthetic_trades

CACHE_DIR = os.path.join(os.path.dirname(__file__), "_tmp_cache")


def setup_function(_fn):
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)


def teardown_function(_fn):
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)


def test_get_history_paginates_and_caches():
    n = 2000  # > limite de pagination (720) pour forcer plusieurs appels
    rows = generate_synthetic_ohlcv(n, timeframe_seconds=3600, seed=42)
    fake_exchange = FakeExchange(rows)

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)
    df = feed.get_history("BTC/USD", "1h", history_days=n // 24 + 1)

    assert len(df) == n
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.is_monotonic_increasing
    assert not df.index.has_duplicates

    cache_path = feed._cache_path("BTC/USD", "1h")
    assert os.path.exists(cache_path)


def test_get_history_only_fetches_new_candles_on_second_call():
    n = 800
    rows = generate_synthetic_ohlcv(n, timeframe_seconds=3600, seed=7)
    fake_exchange = FakeExchange(rows)

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)
    feed.get_history("ETH/USD", "1h", history_days=n // 24 + 1)

    call_log = []
    original_fetch = fake_exchange.fetch_ohlcv

    def counting_fetch_ohlcv(symbol, timeframe, since, limit):
        call_log.append(since)
        return original_fetch(symbol, timeframe, since, limit)

    fake_exchange.fetch_ohlcv = counting_fetch_ohlcv

    df2 = feed.get_history("ETH/USD", "1h", history_days=n // 24 + 1)

    assert len(df2) == n
    # history_days (n//24+1 jours) demande legerement plus que ce que
    # l'exchange peut fournir (n heures) : le premier appel logue est donc
    # une tentative de backfill (avant le debut reel de l'historique, qui ne
    # renvoie rien - l'exchange n'a simplement rien de plus ancien). C'est le
    # dernier appel qui doit demarrer bien apres le debut de l'historique
    # deja en cache (on ne re-telecharge pas tout en avant).
    assert call_log[-1] > rows[0][0]


def test_get_history_backfills_when_more_history_requested_later():
    """Un premier appel avec un history_days petit ne doit pas plafonner
    silencieusement un appel ulterieur avec un history_days plus grand : le
    cache doit etre complete en arriere, pas seulement en avant.

    n=800 heures (~33.3 jours) de donnees disponibles cote exchange ; les deux
    appels demandent nettement moins que ca pour rester loin de la limite
    reelle de l'historique disponible (sinon le "manque" de donnees plus
    anciennes vient de l'exchange lui-meme, pas d'un cache incomplet)."""
    n = 800
    rows = generate_synthetic_ohlcv(n, timeframe_seconds=3600, seed=13)
    fake_exchange = FakeExchange(rows)

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)

    small = feed.get_history("BTC/USD", "1h", history_days=5)
    full = feed.get_history("BTC/USD", "1h", history_days=20)

    assert len(full) > len(small)
    assert full.index[0] < small.index[0]
    assert full.index.is_monotonic_increasing
    assert not full.index.has_duplicates


def test_get_universe_history_returns_all_symbols():
    n = 500
    rows_btc = generate_synthetic_ohlcv(n, timeframe_seconds=3600, seed=1)
    rows_eth = generate_synthetic_ohlcv(n, timeframe_seconds=3600, seed=2)

    class MultiSymbolFakeExchange(FakeExchange):
        def __init__(self):
            self.rateLimit = 0
            self._by_symbol = {"BTC/USD": sorted(rows_btc, key=lambda r: r[0]),
                                "ETH/USD": sorted(rows_eth, key=lambda r: r[0])}

        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            candidates = [r for r in self._by_symbol[symbol] if r[0] >= since]
            return candidates[:limit]

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=MultiSymbolFakeExchange())
    out = feed.get_universe_history(["BTC/USD", "ETH/USD"], "1h", history_days=n // 24 + 1)

    assert set(out.keys()) == {"BTC/USD", "ETH/USD"}
    assert len(out["BTC/USD"]) == n
    assert len(out["ETH/USD"]) == n


# ---------------------------------------------------------------------------
# Historique profond via les trades bruts (etape 7 bis) - voir README.
# ---------------------------------------------------------------------------


def test_fetch_trades_paginated_dedupes_and_covers_all_trades():
    """same_timestamp_every force des trades consecutifs a partager le meme
    timestamp : si la pagination avancait naivement le curseur par +1ms sans
    dedupliquer par id, elle sauterait ou dupliquerait des trades a la
    frontiere des pages. n_trades > limit force plusieurs pages."""
    n = 2500
    trades = generate_synthetic_trades(n, start_ms=1_700_000_000_000, seed=3, same_timestamp_every=7)
    fake_exchange = FakeTradesExchange(trades)

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)
    result = feed._fetch_trades_paginated("BTC/USD", since_ms=1_700_000_000_000, limit=500)

    ids = [t["id"] for t in result]
    assert len(ids) == n
    assert len(set(ids)) == n, "aucun trade duplique malgre des timestamps partages"
    assert set(ids) == {t["id"] for t in trades}, "aucun trade manquant"


def test_get_trades_history_caches_and_backfills():
    """Couvre aussi un bug reel trouve ici : les id de trade "ressemblant" a
    des nombres (ex: "0", "74968999") sont lus comme int64 par pandas au
    rechargement du cache CSV, alors que ccxt les renvoie en str - sans
    dtype={"id": str} force a la lecture, drop_duplicates(subset="id") ne
    matche jamais le cache relu contre les trades fraichement recuperes
    (meme trade, deux types differents) et duplique silencieusement a
    chaque appel."""
    n = 3000
    trades = generate_synthetic_trades(n, start_ms=1_700_000_000_000, seed=4)
    fake_exchange = FakeTradesExchange(trades)

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)

    small = feed.get_trades_history("BTC/USD", history_days=1_000_000)  # tout l'historique dispo, borne large
    assert len(small) == n

    cache_path = feed._trades_cache_path("BTC/USD")
    assert os.path.exists(cache_path)

    # Deuxieme appel : pas de nouveau trade cote exchange -> pas de duplication,
    # meme apres un aller-retour par le cache CSV sur disque.
    again = feed.get_trades_history("BTC/USD", history_days=1_000_000)
    assert len(again) == n, "duplication silencieuse a la frontiere de pagination (voir docstring)"
    assert not again["id"].duplicated().any()

    # Troisieme appel, pour bonne mesure (la duplication, si elle existait,
    # s'accumulerait a chaque appel plutot que de rester stable).
    third = feed.get_trades_history("BTC/USD", history_days=1_000_000)
    assert len(third) == n


def test_resample_trades_to_ohlcv_matches_manual_computation():
    base_ms = 1_700_000_000_000
    trades = pd.DataFrame(
        [
            {"id": "1", "timestamp": base_ms + 0, "price": 100.0, "amount": 1.0},
            {"id": "2", "timestamp": base_ms + 1000, "price": 105.0, "amount": 2.0},
            {"id": "3", "timestamp": base_ms + 2000, "price": 95.0, "amount": 1.5},
            # bougie suivante (+1h), un seul trade
            {"id": "4", "timestamp": base_ms + 3600_000, "price": 110.0, "amount": 0.5},
        ]
    )
    bars = resample_trades_to_ohlcv(trades, timeframe_seconds=3600)

    assert len(bars) == 2
    first, second = bars.iloc[0], bars.iloc[1]
    assert first["open"] == 100.0
    assert first["high"] == 105.0
    assert first["low"] == 95.0
    assert first["close"] == 95.0
    assert first["volume"] == 1.0 + 2.0 + 1.5
    assert second["open"] == second["close"] == 110.0
    assert second["volume"] == 0.5


def test_resample_trades_to_ohlcv_skips_bars_with_no_trades():
    base_ms = 1_700_000_000_000
    trades = pd.DataFrame(
        [
            {"id": "1", "timestamp": base_ms, "price": 100.0, "amount": 1.0},
            # trou de 3h sans aucun trade avant le suivant
            {"id": "2", "timestamp": base_ms + 3 * 3600_000, "price": 100.0, "amount": 1.0},
        ]
    )
    bars = resample_trades_to_ohlcv(trades, timeframe_seconds=3600)

    assert len(bars) == 2, "les bougies vides intermediaires doivent etre absentes, pas forward-fillees"


def test_fetch_trades_paginated_retries_on_transient_network_error():
    """Bug reel trouve en lancant un fetch d'historique profond : une simple
    coupure reseau transitoire (proxy coupe un instant) faisait planter tout
    le processus, perdant des heures de progression en memoire faute de
    retry. _call_with_retry doit absorber quelques erreurs transitoires
    (ccxt.NetworkError) avant de reussir."""
    n = 50
    trades = generate_synthetic_trades(n, start_ms=1_700_000_000_000, seed=6, same_timestamp_every=0)
    fake_exchange = FakeTradesExchange(trades)

    call_count = {"n": 0}
    original_fetch = fake_exchange.fetch_trades

    def flaky_fetch_trades(symbol, since, limit):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            raise ccxt.NetworkError("coupure reseau simulee")
        return original_fetch(symbol, since=since, limit=limit)

    fake_exchange.fetch_trades = flaky_fetch_trades

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)
    with patch("crypto_quant.data.time.sleep"):  # pas d'attente reelle du backoff dans les tests
        result = feed._fetch_trades_paginated("BTC/USD", since_ms=1_700_000_000_000, limit=500)

    assert len(result) == n
    assert call_count["n"] > 2, "doit avoir reessaye apres les erreurs simulees"


def test_fetch_trades_paginated_gives_up_after_max_retries():
    def always_fails(symbol, since, limit):
        raise ccxt.NetworkError("coupure reseau simulee, permanente")

    fake_exchange = FakeTradesExchange([])
    fake_exchange.fetch_trades = always_fails

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)
    with patch("crypto_quant.data.time.sleep"):
        try:
            feed._fetch_trades_paginated("BTC/USD", since_ms=1_700_000_000_000, limit=500)
            assert False, "aurait du finir par relever ccxt.NetworkError"
        except ccxt.NetworkError:
            pass


def test_get_history_from_trades_returns_ohlcv_like_format():
    n = 5000
    trades = generate_synthetic_trades(n, start_ms=1_700_000_000_000, avg_gap_ms=500, seed=5)
    fake_exchange = FakeTradesExchange(trades)

    feed = CCXTDataFeed(exchange_id="kraken", cache_dir=CACHE_DIR, exchange_client=fake_exchange)
    bars = feed.get_history_from_trades("BTC/USD", "1h", history_days=1_000_000)

    assert list(bars.columns) == ["open", "high", "low", "close", "volume"]
    assert bars.index.name == "datetime"
    assert bars.index.is_monotonic_increasing
    assert not bars.isna().any().any()
    assert len(bars) > 0


def _daily_frame(dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame({"close": range(len(dates))}, index=dates)


def test_largest_contiguous_segment_returns_unchanged_when_no_gap():
    dates = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
    price_data = {"BTC/USD": _daily_frame(dates), "ETH/USD": _daily_frame(dates)}

    result = largest_contiguous_segment(price_data)

    assert len(result["BTC/USD"]) == 100
    assert len(result["ETH/USD"]) == 100


def test_largest_contiguous_segment_aligns_different_ranges_without_internal_gap():
    # Cas reel rencontre en pratique (univers elargi, README etape 13 bis) :
    # certains actifs (ex: DASH/NEO/ZRX/BAT, delistes de Binance.US en juin
    # 2023) s'arretent plus tot que d'autres (BTC/ETH, qui continuent) sans
    # qu'il y ait de TROU partage - l'intersection commune est deja continue,
    # juste plus courte que la plage individuelle de chaque actif. Meme sans
    # trou a corriger, la fonction doit renvoyer des actifs ALIGNES sur cette
    # intersection, pas les DataFrames bruts avec leurs plages divergentes.
    long_asset_dates = pd.date_range("2019-09-17", "2026-09-30", freq="D", tz="UTC")
    short_asset_dates = pd.date_range("2019-11-01", "2023-06-27", freq="D", tz="UTC")
    price_data = {
        "BTC/USD": _daily_frame(long_asset_dates),
        "DASH/USD": _daily_frame(short_asset_dates),
    }

    result = largest_contiguous_segment(price_data)

    assert list(result["BTC/USD"].index) == list(result["DASH/USD"].index)
    assert result["BTC/USD"].index[0] == short_asset_dates[0]
    assert result["BTC/USD"].index[-1] == short_asset_dates[-1]
    assert len(result["BTC/USD"]) == len(short_asset_dates)


def test_largest_contiguous_segment_drops_suspended_trading_gap():
    # Reproduit le cas reel (README, etape 13 bis) : suspension du trading
    # USD sur Binance.US, juillet 2023 a fevrier 2025 - un trou de plusieurs
    # mois partage par TOUS les actifs, pas juste un ecart isole sur un seul.
    before_gap = pd.date_range("2019-09-17", "2023-07-14", freq="D", tz="UTC")
    after_gap = pd.date_range("2025-02-19", "2026-09-30", freq="D", tz="UTC")
    dates = before_gap.append(after_gap)
    price_data = {"BTC/USD": _daily_frame(dates), "ETH/USD": _daily_frame(dates)}

    result = largest_contiguous_segment(price_data)

    # Le segment avant le trou (~1400 jours) est plus grand que celui d'apres
    # (~588 jours) : c'est lui qui doit etre retenu, en entier et sans trou.
    assert len(result["BTC/USD"]) == len(before_gap)
    assert result["BTC/USD"].index[0] == before_gap[0]
    assert result["BTC/USD"].index[-1] == before_gap[-1]
    assert (result["BTC/USD"].index.to_series().diff().dropna() == pd.Timedelta(days=1)).all()


def test_largest_contiguous_segment_keeps_symbols_aligned():
    before_gap = pd.date_range("2020-01-01", "2020-06-01", freq="D", tz="UTC")
    after_gap = pd.date_range("2021-01-01", "2021-01-10", freq="D", tz="UTC")
    dates = before_gap.append(after_gap)
    price_data = {"BTC/USD": _daily_frame(dates), "ETH/USD": _daily_frame(dates)}

    result = largest_contiguous_segment(price_data)

    assert list(result["BTC/USD"].index) == list(result["ETH/USD"].index)


if __name__ == "__main__":
    setup_function(None)
    test_get_history_paginates_and_caches()
    teardown_function(None)

    setup_function(None)
    test_get_history_only_fetches_new_candles_on_second_call()
    teardown_function(None)

    setup_function(None)
    test_get_history_backfills_when_more_history_requested_later()
    teardown_function(None)

    setup_function(None)
    test_get_universe_history_returns_all_symbols()
    teardown_function(None)

    setup_function(None)
    test_fetch_trades_paginated_dedupes_and_covers_all_trades()
    teardown_function(None)

    setup_function(None)
    test_get_trades_history_caches_and_backfills()
    teardown_function(None)

    test_resample_trades_to_ohlcv_matches_manual_computation()
    test_resample_trades_to_ohlcv_skips_bars_with_no_trades()

    setup_function(None)
    test_get_history_from_trades_returns_ohlcv_like_format()
    teardown_function(None)

    print("Tous les tests data.py passent.")
