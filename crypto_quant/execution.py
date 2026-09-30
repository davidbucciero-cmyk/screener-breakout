"""Execution des ordres (etape 6) : la seule partie du projet qui touche a
de l'argent reel si dry_run=False.

Defense en profondeur volontaire : trois barrieres INDEPENDANTES sont
requises simultanement pour du live reel, precisement pour qu'un
dry_run=False accidentel (typo, config oubliee, copier-coller) ne suffise
jamais a lui seul a declencher des ordres reels :

1. dry_run=False explicite
2. la variable d'environnement CRYPTO_QUANT_CONFIRM_LIVE_TRADING positionnee
   a une valeur precise (pas juste "true"/"1")
3. des cles API valides en variables d'environnement (jamais en dur dans le
   code, jamais committees)

Limite de perimetre assumee : le coupe-circuit de drawdown (risk.py) a
besoin de suivre l'equity dans le temps. DrawdownCircuitBreaker.to_dict()/
from_dict() permettent de persister son etat entre deux executions d'un
processus relance periodiquement (cron, etc.), mais l'integration complete
dans une boucle de production (frequence, service systeme, alerting en cas
d'echec) reste a batir selon l'infra de deploiement - ce module fournit les
briques, pas un service cle en main.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from .data import build_exchange
from .risk import DrawdownCircuitBreaker


class LiveExecutionError(Exception):
    """Levee quand une tentative de trading live ne remplit pas toutes les
    conditions de securite - jamais attrapee silencieusement."""


@dataclass
class Order:
    symbol: str
    side: str  # "buy" ou "sell"
    amount: float  # quantite en devise de base (ex: BTC pour BTC/USD)
    order_type: str = "market"


class LiveExecutor:
    LIVE_CONFIRMATION_ENV_VAR = "CRYPTO_QUANT_CONFIRM_LIVE_TRADING"
    LIVE_CONFIRMATION_VALUE = "j-accepte-le-risque"

    def __init__(
        self,
        exchange_id: str = "kraken",
        dry_run: bool = True,
        min_notional: float = 10.0,
        api_key_env: str = "KRAKEN_API_KEY",
        api_secret_env: str = "KRAKEN_API_SECRET",
        exchange_client=None,
        initial_dry_run_cash: float = 10_000.0,
    ):
        self.dry_run = dry_run
        self.min_notional = min_notional
        self.exchange_id = exchange_id

        if exchange_client is not None:
            self.exchange = exchange_client
        elif dry_run:
            # Dry-run n'a besoin que de donnees publiques (prix), jamais de
            # cles API - c'est en soi une garantie de securite : impossible
            # de placer un ordre reel sans authentification.
            self.exchange = build_exchange(exchange_id)
        else:
            self._require_live_confirmation()
            api_key = os.environ.get(api_key_env)
            api_secret = os.environ.get(api_secret_env)
            if not api_key or not api_secret:
                raise LiveExecutionError(
                    f"Live trading demande mais {api_key_env}/{api_secret_env} absentes "
                    "de l'environnement. Les cles API ne doivent jamais etre codees en "
                    "dur ni committees - toujours via variables d'environnement."
                )
            self.exchange = build_exchange(exchange_id)
            self.exchange.apiKey = api_key
            self.exchange.secret = api_secret

        self.dry_run_log: List[dict] = []
        self.dry_run_holdings: Dict[str, float] = {}
        self.dry_run_cash = initial_dry_run_cash

    def dry_run_state_dict(self) -> dict:
        """Serialise l'etat du paper trading (cash, positions, journal des
        ordres) - pour persister entre deux executions d'un processus
        relance periodiquement (cf. save_dry_run_state/load_dry_run_state,
        meme besoin que DrawdownCircuitBreaker.to_dict/from_dict)."""
        return {
            "dry_run_cash": self.dry_run_cash,
            "dry_run_holdings": self.dry_run_holdings,
            "dry_run_log": self.dry_run_log,
        }

    def load_dry_run_state(self, state: dict) -> None:
        self.dry_run_cash = state["dry_run_cash"]
        self.dry_run_holdings = state["dry_run_holdings"]
        self.dry_run_log = state["dry_run_log"]

    def _require_live_confirmation(self) -> None:
        confirmation = os.environ.get(self.LIVE_CONFIRMATION_ENV_VAR)
        if confirmation != self.LIVE_CONFIRMATION_VALUE:
            raise LiveExecutionError(
                "Live trading refuse : dry_run=False seul ne suffit pas. Il faut aussi "
                f"positionner {self.LIVE_CONFIRMATION_ENV_VAR}='{self.LIVE_CONFIRMATION_VALUE}' "
                "dans l'environnement. C'est une protection en profondeur deliberee : un "
                "dry_run=False accidentel ne doit jamais, a lui seul, activer du reel."
            )

    def compute_rebalance_orders(
        self,
        current_holdings: Dict[str, float],
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        total_equity: float,
    ) -> List[Order]:
        """Calcule les ordres necessaires pour passer des positions actuelles
        aux poids cibles. Ignore les ecarts sous min_notional (evite le bruit
        de micro-rebalancements et les rejets pour montant sous le minimum
        de l'exchange)."""
        orders = []
        symbols = set(current_holdings) | set(target_weights) | set(prices)

        for symbol in sorted(symbols):
            price = prices.get(symbol)
            if price is None or price <= 0:
                continue

            current_value = current_holdings.get(symbol, 0.0) * price
            target_value = target_weights.get(symbol, 0.0) * total_equity
            delta_value = target_value - current_value

            if abs(delta_value) < self.min_notional:
                continue

            side = "buy" if delta_value > 0 else "sell"
            amount = abs(delta_value) / price
            orders.append(Order(symbol=symbol, side=side, amount=amount))

        return orders

    def execute_orders(self, orders: List[Order], prices: Optional[Dict[str, float]] = None) -> List[dict]:
        return [
            self._execute_dry_run(order, prices) if self.dry_run else self._execute_live(order)
            for order in orders
        ]

    def _execute_dry_run(self, order: Order, prices: Optional[Dict[str, float]]) -> dict:
        price = (prices or {}).get(order.symbol)
        record = {"symbol": order.symbol, "side": order.side, "amount": order.amount, "price": price, "dry_run": True}
        self.dry_run_log.append(record)

        signed_qty = order.amount if order.side == "buy" else -order.amount
        self.dry_run_holdings[order.symbol] = self.dry_run_holdings.get(order.symbol, 0.0) + signed_qty
        if price is not None:
            self.dry_run_cash -= signed_qty * price
        return record

    def _execute_live(self, order: Order) -> dict:
        try:
            raw = self.exchange.create_order(order.symbol, order.order_type, order.side, order.amount)
            return {"symbol": order.symbol, "side": order.side, "amount": order.amount, "dry_run": False, "raw": raw}
        except Exception as exc:  # noqa: BLE001 - un ordre en echec ne doit jamais planter le reste du rebalancement
            return {
                "symbol": order.symbol,
                "side": order.side,
                "amount": order.amount,
                "dry_run": False,
                "error": str(exc),
            }


def save_breaker_state(breaker: DrawdownCircuitBreaker, path: str) -> None:
    with open(path, "w") as f:
        json.dump(breaker.to_dict(), f)


def load_breaker_state(path: str, default: DrawdownCircuitBreaker) -> DrawdownCircuitBreaker:
    """Charge l'etat du coupe-circuit depuis un fichier s'il existe, sinon
    renvoie `default` tel quel (premiere execution : pas encore d'etat a
    charger)."""
    if not os.path.exists(path):
        return default
    with open(path) as f:
        state = json.load(f)
    return DrawdownCircuitBreaker.from_dict(state)


def save_dry_run_state(executor: LiveExecutor, path: str) -> None:
    with open(path, "w") as f:
        json.dump(executor.dry_run_state_dict(), f, indent=2)


def load_dry_run_state(executor: LiveExecutor, path: str) -> None:
    """Charge l'etat de paper trading dans `executor` depuis un fichier s'il
    existe (mutation en place, meme convention que load_breaker_state) -
    sinon ne fait rien (premiere execution : l'executor garde son etat
    initial, cash=initial_dry_run_cash, aucune position)."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        state = json.load(f)
    executor.load_dry_run_state(state)
