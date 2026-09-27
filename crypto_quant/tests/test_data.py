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

import pandas as pd

from crypto_quant.data import CCXTDataFeed, resample_trades_to_ohlcv
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
