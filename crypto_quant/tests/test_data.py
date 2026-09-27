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

from crypto_quant.data import CCXTDataFeed
from crypto_quant.synthetic import FakeExchange, generate_synthetic_ohlcv

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
    # Le "since" du premier appel doit demarrer bien apres le debut de
    # l'historique deja en cache (on ne re-telecharge pas tout).
    assert call_log[0] > rows[0][0]


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


if __name__ == "__main__":
    setup_function(None)
    test_get_history_paginates_and_caches()
    teardown_function(None)

    setup_function(None)
    test_get_history_only_fetches_new_candles_on_second_call()
    teardown_function(None)

    setup_function(None)
    test_get_universe_history_returns_all_symbols()
    teardown_function(None)

    print("Tous les tests data.py passent.")
