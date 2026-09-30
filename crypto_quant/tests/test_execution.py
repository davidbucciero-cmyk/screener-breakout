"""Tests du module d'execution (etape 6).

Priorite absolue : verifier que les 3 barrieres de securite pour le live
sont bien INDEPENDANTES et bloquent chacune a elles seules, avant meme de
tester la logique de calcul d'ordres.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from crypto_quant.execution import (
    LiveExecutionError,
    LiveExecutor,
    Order,
    load_breaker_state,
    load_dry_run_state,
    save_breaker_state,
    save_dry_run_state,
)
from crypto_quant.risk import DrawdownCircuitBreaker


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # S'assure qu'aucune variable d'environnement laissee par un test
    # precedent (ou par l'environnement reel) ne fausse ces tests de securite.
    monkeypatch.delenv("CRYPTO_QUANT_CONFIRM_LIVE_TRADING", raising=False)
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)


def test_dry_run_is_the_default():
    executor = LiveExecutor(exchange_client=object())  # dry_run implicite -> aucun besoin d'un vrai client fonctionnel
    assert executor.dry_run is True


def test_live_refused_without_confirmation_env_var_even_with_keys(monkeypatch):
    monkeypatch.setenv("KRAKEN_API_KEY", "fake_key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "fake_secret")
    # Pas de CRYPTO_QUANT_CONFIRM_LIVE_TRADING -> doit etre refuse malgre des cles valides.
    with pytest.raises(LiveExecutionError):
        LiveExecutor(dry_run=False)


def test_live_refused_without_api_keys_even_with_confirmation(monkeypatch):
    monkeypatch.setenv("CRYPTO_QUANT_CONFIRM_LIVE_TRADING", "j-accepte-le-risque")
    # Pas de cles API -> doit etre refuse malgre la confirmation.
    with pytest.raises(LiveExecutionError):
        LiveExecutor(dry_run=False)


def test_live_refused_with_wrong_confirmation_value(monkeypatch):
    monkeypatch.setenv("CRYPTO_QUANT_CONFIRM_LIVE_TRADING", "true")  # valeur generique, pas la phrase exacte
    monkeypatch.setenv("KRAKEN_API_KEY", "fake_key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "fake_secret")
    with pytest.raises(LiveExecutionError):
        LiveExecutor(dry_run=False)


def test_live_accepted_when_all_three_conditions_met(monkeypatch):
    monkeypatch.setenv("CRYPTO_QUANT_CONFIRM_LIVE_TRADING", "j-accepte-le-risque")
    monkeypatch.setenv("KRAKEN_API_KEY", "fake_key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "fake_secret")

    class DummyExchange:
        apiKey = None
        secret = None

    # On ne peut pas construire un vrai ccxt.kraken() sans reseau ici, donc
    # on verifie que le chemin "toutes conditions reunies" ne leve pas
    # d'erreur AVANT l'appel reseau, en patchant build_exchange.
    import crypto_quant.execution as execution_module

    original_build_exchange = execution_module.build_exchange
    execution_module.build_exchange = lambda exchange_id: DummyExchange()
    try:
        executor = LiveExecutor(dry_run=False)
        assert executor.dry_run is False
        assert executor.exchange.apiKey == "fake_key"
    finally:
        execution_module.build_exchange = original_build_exchange


def test_compute_rebalance_orders_ignores_dust_below_min_notional():
    executor = LiveExecutor(exchange_client=object(), min_notional=10.0)
    orders = executor.compute_rebalance_orders(
        current_holdings={"BTC/USD": 0.0},
        target_weights={"BTC/USD": 0.0001},  # ecart minuscule
        prices={"BTC/USD": 50_000.0},
        total_equity=10_000.0,
    )
    assert orders == []


def test_compute_rebalance_orders_buy_and_sell_sides():
    executor = LiveExecutor(exchange_client=object(), min_notional=10.0)
    orders = executor.compute_rebalance_orders(
        current_holdings={"BTC/USD": 0.1, "ETH/USD": 1.0},
        target_weights={"BTC/USD": 0.8, "ETH/USD": 0.0},
        prices={"BTC/USD": 50_000.0, "ETH/USD": 3_000.0},
        total_equity=10_000.0,
    )
    by_symbol = {o.symbol: o for o in orders}

    # BTC : detient 0.1*50000=5000, cible 0.8*10000=8000 -> achat de 3000/50000=0.06
    assert by_symbol["BTC/USD"].side == "buy"
    assert abs(by_symbol["BTC/USD"].amount - 0.06) < 1e-9

    # ETH : detient 1.0*3000=3000, cible 0 -> vente complete de 1.0
    assert by_symbol["ETH/USD"].side == "sell"
    assert abs(by_symbol["ETH/USD"].amount - 1.0) < 1e-9


def test_dry_run_execution_updates_virtual_ledger_and_never_calls_exchange():
    class ExplodingExchange:
        def create_order(self, *args, **kwargs):
            raise AssertionError("Le dry-run ne doit JAMAIS appeler create_order")

    executor = LiveExecutor(exchange_client=ExplodingExchange(), dry_run=True, initial_dry_run_cash=10_000.0)
    orders = [Order(symbol="BTC/USD", side="buy", amount=0.1)]

    results = executor.execute_orders(orders, prices={"BTC/USD": 50_000.0})

    assert results[0]["dry_run"] is True
    assert executor.dry_run_holdings["BTC/USD"] == 0.1
    assert executor.dry_run_cash == 10_000.0 - 0.1 * 50_000.0


def test_live_execution_failure_does_not_raise_and_is_recorded(monkeypatch):
    monkeypatch.setenv("CRYPTO_QUANT_CONFIRM_LIVE_TRADING", "j-accepte-le-risque")
    monkeypatch.setenv("KRAKEN_API_KEY", "fake_key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "fake_secret")

    class FailingExchange:
        apiKey = None
        secret = None

        def create_order(self, symbol, order_type, side, amount):
            raise RuntimeError("Solde insuffisant")

    import crypto_quant.execution as execution_module

    original_build_exchange = execution_module.build_exchange
    execution_module.build_exchange = lambda exchange_id: FailingExchange()
    try:
        executor = LiveExecutor(dry_run=False)
        results = executor.execute_orders([Order(symbol="BTC/USD", side="buy", amount=0.1)])
        assert "error" in results[0]
        assert "Solde insuffisant" in results[0]["error"]
    finally:
        execution_module.build_exchange = original_build_exchange


def test_breaker_state_roundtrip(tmp_path):
    breaker = DrawdownCircuitBreaker(halt_drawdown=0.25, resume_drawdown=0.05, cooldown_periods=10)
    breaker.step(100.0)
    breaker.step(70.0)  # declenche une halte (dd=-30% <= -25%)
    assert breaker._halted is True

    path = str(tmp_path / "breaker_state.json")
    save_breaker_state(breaker, path)

    restored = load_breaker_state(path, default=DrawdownCircuitBreaker())
    assert restored.halt_drawdown == 0.25
    assert restored.resume_drawdown == 0.05
    assert restored.cooldown_periods == 10
    assert restored._halted is True
    assert restored._running_max == 100.0


def test_load_breaker_state_returns_default_when_file_missing(tmp_path):
    default = DrawdownCircuitBreaker(halt_drawdown=0.15)
    restored = load_breaker_state(str(tmp_path / "does_not_exist.json"), default=default)
    assert restored is default


def test_dry_run_state_roundtrip(tmp_path):
    executor = LiveExecutor(exchange_client=object(), initial_dry_run_cash=5_000.0)
    orders = executor.compute_rebalance_orders(
        current_holdings={}, target_weights={"GOLD": 1.0}, prices={"GOLD": 2000.0}, total_equity=5_000.0
    )
    executor.execute_orders(orders, prices={"GOLD": 2000.0})
    assert executor.dry_run_holdings.get("GOLD", 0.0) > 0

    path = str(tmp_path / "dry_run_state.json")
    save_dry_run_state(executor, path)

    restored = LiveExecutor(exchange_client=object())
    load_dry_run_state(restored, path)
    assert restored.dry_run_cash == executor.dry_run_cash
    assert restored.dry_run_holdings == executor.dry_run_holdings
    assert restored.dry_run_log == executor.dry_run_log


def test_load_dry_run_state_is_noop_when_file_missing(tmp_path):
    executor = LiveExecutor(exchange_client=object(), initial_dry_run_cash=1_234.0)
    load_dry_run_state(executor, str(tmp_path / "does_not_exist.json"))
    assert executor.dry_run_cash == 1_234.0
    assert executor.dry_run_holdings == {}


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    print(f"{len(tests)} tests definis - lancer via pytest pour les fixtures (monkeypatch, tmp_path).")
