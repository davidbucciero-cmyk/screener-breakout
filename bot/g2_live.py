"""Bot G2 : decision, enveloppes virtuelles, limites de risque et execution (Alpaca paper).

Couches separees : `decide` (signal, meme fonction que le backtest), `RiskBook` (limites dures, en code,
sans aucune sortie de modele), `Broker` (execution). Les limites sont verifiees avant chaque ordre.
"""
import logging
import math
import time

import pandas as pd
import requests

from bot.g_variants import btc_below_sma200_daily
from bot.multi import rotation_weights

log = logging.getLogger(__name__)

SYMBOLS = {'BTCUSDT': 'BTC/USD', 'ETHUSDT': 'ETH/USD', 'SOLUSDT': 'SOL/USD'}
ENVELOPE = 10_000.0
SLEEVES = {'G2-19': {'target_vol': 0.19, 'kill_dd': 0.20},
           'G2-25': {'target_vol': 0.25, 'kill_dd': 0.20},
           'G2-40': {'target_vol': 0.40, 'kill_dd': 0.35}}
APPROVAL_USD = 5_000.0      # au-dessus : validation manuelle (label `approved` sur l'issue GitHub)
MIN_ORDER_USD = 10.0
FEE = 0.0025                # frais taker Alpaca crypto, imputes aux enveloppes
MAX_DATA_AGE = pd.Timedelta(hours=26)
ALPACA_PAPER = 'https://paper-api.alpaca.markets'  # en dur : impossible de viser le compte reel par erreur


def decide(daily, target_vol):
    """Poids cibles pour aujourd'hui, decides a la cloture d'hier. daily : clotures quotidiennes."""
    risk_off = btc_below_sma200_daily(daily['BTCUSDT'])
    return rotation_weights(daily, risk_off=risk_off, target_vol=target_vol).iloc[-1]


def check_fresh(daily, now):
    """Derniere bougie quotidienne = celle d'hier (cloturee a minuit UTC), sinon aucun ordre."""
    last_close = daily.index[-1] + pd.Timedelta(days=1)
    age = now - last_close
    if age > MAX_DATA_AGE or age < pd.Timedelta(0):
        raise RuntimeError(f'Donnees perimees : derniere cloture {last_close}, maintenant {now}')


def new_sleeve():
    return {'cash': ENVELOPE, 'qty': {s: 0.0 for s in SYMBOLS}, 'peak': ENVELOPE, 'prev_equity': ENVELOPE,
            'halted': False}


def equity(sleeve, prices):
    return sleeve['cash'] + sum(q * prices[s] for s, q in sleeve['qty'].items())


class RiskBook:
    """Limites dures par enveloppe. Aucune n'est contournable par un modele."""

    def __init__(self, name, cfg):
        self.name, self.kill_dd = name, cfg['kill_dd']
        self.daily_loss = cfg['kill_dd'] / 4

    def assess(self, sleeve, prices):
        """Met a jour le pic ; renvoie (kill, no_buy, raison)."""
        eq = equity(sleeve, prices)
        sleeve['peak'] = max(sleeve['peak'], eq)
        dd = eq / sleeve['peak'] - 1
        day = eq / sleeve['prev_equity'] - 1
        if sleeve['halted']:
            return True, True, 'enveloppe arretee (kill switch deja declenche)'
        if dd <= -self.kill_dd:
            return True, True, f'KILL SWITCH : drawdown {dd:.1%} <= -{self.kill_dd:.0%}'
        if day <= -self.daily_loss:
            return False, True, f'perte du jour {day:.1%} : aucun achat aujourd\'hui'
        return False, False, ''

    @staticmethod
    def clip_targets(target_qty, sleeve, prices, no_buy):
        """Sans levier, pas d'achat si bloque : la cible ne peut qu'etre reduite."""
        eq = equity(sleeve, prices)
        out = {}
        for s, q in target_qty.items():
            q = max(q, 0.0)
            if no_buy:
                q = min(q, sleeve['qty'][s])
            out[s] = q
        gross = sum(q * prices[s] for s, q in out.items())
        if gross > eq > 0:
            out = {s: q * eq / gross for s, q in out.items()}
        return out


def plan_orders(state, daily, prices):
    """Cibles par enveloppe -> ordres nets par crypto. Renvoie (ordres, deltas par enveloppe, evenements)."""
    deltas, events = {}, []
    for name, cfg in SLEEVES.items():
        sl = state['sleeves'][name]
        kill, no_buy, why = RiskBook(name, cfg).assess(sl, prices)
        if why:
            events.append((name, why))
        if kill:
            sl['halted'] = True
            target = {s: 0.0 for s in SYMBOLS}
        else:
            w = decide(daily, cfg['target_vol'])
            eq = equity(sl, prices)
            target = RiskBook.clip_targets({s: w.get(s, 0.0) * eq / prices[s] for s in SYMBOLS}, sl, prices, no_buy)
        deltas[name] = {s: target[s] - sl['qty'][s] for s in SYMBOLS}
    net = {s: sum(d[s] for d in deltas.values()) for s in SYMBOLS}
    orders = {s: q for s, q in net.items() if abs(q) * prices[s] >= MIN_ORDER_USD}
    return orders, deltas, events


def apply_fill(state, deltas, symbol, fill_price, executed_fraction=1.0):
    """Repartit une execution entre enveloppes, au prix d'execution.

    Frais comme chez Alpaca crypto : preleves sur l'actif recu (crypto a l'achat, dollars a la vente).
    """
    for name, d in deltas.items():
        q = d[symbol] * executed_fraction
        if abs(q) * fill_price < 1e-9:
            continue
        sl = state['sleeves'][name]
        if q > 0:
            sl['qty'][symbol] += q * (1 - FEE)
            sl['cash'] -= q * fill_price
        else:
            sl['qty'][symbol] += q
            sl['cash'] += -q * fill_price * (1 - FEE)


class AlpacaPaper:
    def __init__(self, key, secret):
        self.h = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}

    def _req(self, method, path, **kw):
        r = requests.request(method, ALPACA_PAPER + path, headers=self.h, timeout=30, **kw)
        r.raise_for_status()
        return r.json() if r.text else {}

    def positions(self):
        return {p['symbol'].replace('/', ''): float(p['qty']) for p in self._req('GET', '/v2/positions')}

    def market(self, pair, qty):
        side = 'buy' if qty > 0 else 'sell'
        o = self._req('POST', '/v2/orders', json={'symbol': pair, 'qty': f'{abs(qty):.8f}', 'side': side,
                                                  'type': 'market', 'time_in_force': 'gtc'})
        for _ in range(30):
            o = self._req('GET', f"/v2/orders/{o['id']}")
            if o['status'] in ('filled', 'canceled', 'rejected', 'expired'):
                break
            time.sleep(1)
        filled = float(o.get('filled_qty') or 0)
        price = float(o.get('filled_avg_price') or 'nan')
        return {'status': o['status'], 'filled_qty': filled * (1 if qty > 0 else -1), 'price': price, 'id': o['id']}


def needs_approval(qty, price):
    return abs(qty) * price > APPROVAL_USD


def realized_vol_ok(daily):
    """Garde-fou : pas d'ordre si une crypto a des donnees manquantes sur les 30 derniers jours."""
    tail = daily.tail(30)
    return bool(tail.notna().all().all()) and all(math.isfinite(v) for v in tail.iloc[-1])
