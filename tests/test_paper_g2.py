import numpy as np
import pandas as pd
import pytest

from bot import g2_live as L
from bot import paper_g2 as P


class FakeBroker:
    def __init__(self):
        self.pos, self.orders = {}, []

    def positions(self):
        return dict(self.pos)

    def market(self, pair, qty):
        sym = pair.replace('/', '')
        self.pos[sym] = self.pos.get(sym, 0.0) + qty * (1 - L.FEE if qty > 0 else 1)
        self.orders.append((pair, qty))
        return {'status': 'filled', 'filled_qty': qty, 'price': 100.0, 'id': str(len(self.orders))}


class FakeGitHub:
    def __init__(self, approve=False):
        self.asked, self.approve = [], approve

    def approved(self, sleeve, symbol):
        return 1 if self.approve else None

    def ask(self, sleeve, symbol, qty, price):
        self.asked.append((sleeve, symbol))

    def close(self, n):
        pass


@pytest.fixture
def market(monkeypatch, tmp_path):
    monkeypatch.setattr(P, 'DIR', tmp_path)
    idx = pd.date_range('2025-01-01', periods=400, freq='D', tz='UTC')
    up = pd.Series(np.linspace(50, 100, 400), index=idx)  # BTC en hausse reguliere : au-dessus de sa moyenne 200 j
    frames = {'BTCUSDT': up, 'ETHUSDT': up * 0 + 100.0, 'SOLUSDT': up * 0 + 100.0}
    monkeypatch.setattr(P, 'fetch_btc', lambda interval, bars, symbol: pd.DataFrame({'close': frames[symbol]}))
    return idx[-1] + pd.Timedelta(days=1, minutes=10)


def test_first_day_buys_without_approval_and_is_idempotent(market):
    broker, gh = FakeBroker(), FakeGitHub(approve=False)
    st, lines = P.run(broker, gh, now=market)
    assert len(broker.orders) == 3 and all(o[0] == 'BTC/USD' and o[1] > 0 for o in broker.orders)  # un ordre par enveloppe
    assert not gh.asked
    total_virtual = sum(sl['qty']['BTCUSDT'] for sl in st['sleeves'].values())
    assert total_virtual == pytest.approx(broker.pos['BTCUSD'])  # comptes virtuels = position reelle
    n = len(broker.orders)
    P.run(broker, gh, now=market)  # meme jour : rien de plus
    assert len(broker.orders) == n


def test_large_order_waits_for_approval(market, monkeypatch):
    monkeypatch.setattr(L, 'APPROVAL_USD', 100.0)
    broker, gh = FakeBroker(), FakeGitHub(approve=False)
    st, lines = P.run(broker, gh, now=market)
    assert not broker.orders and len(gh.asked) == 3 and all(a[1] == 'BTCUSDT' for a in gh.asked)
    assert any('attente de validation' in l for l in lines)


def test_stale_data_raises_without_orders(market):
    broker = FakeBroker()
    with pytest.raises(RuntimeError):
        P.run(broker, FakeGitHub(), now=market + pd.Timedelta(days=3))
    assert not broker.orders


def test_dashboard_renders_after_a_trading_day(market, monkeypatch, tmp_path):
    from bot import dashboard_g2 as Dsh
    monkeypatch.setattr(Dsh, 'DIR', tmp_path)
    P.run(FakeBroker(), FakeGitHub(), now=market)
    html = Dsh.build().read_text()
    assert 'G2-19' in html and 'const D = {' in html and '__DATA__' not in html
    import json
    data = json.loads((tmp_path / 'dashboard.json').read_text())
    assert [e['nom'] for e in data['enveloppes']] == ['G2-19', 'G2-25', 'G2-40']


def test_dashboard_renders_before_first_day(monkeypatch, tmp_path):
    from bot import dashboard_g2 as Dsh
    monkeypatch.setattr(Dsh, 'DIR', tmp_path)
    assert 'pas encore' in Dsh.build().read_text().lower()
