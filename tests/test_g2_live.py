import numpy as np
import pandas as pd
import pytest

from bot import g2_live as L
from bot.g_variants import btc_below_sma200_daily
from bot.multi import rotation_weights


def _daily(n=500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2025-01-01', periods=n, freq='D', tz='UTC')
    return pd.DataFrame({s: 100 * (k + 1) * np.exp(np.cumsum(rng.normal(0.002, 0.03, n)))
                         for k, s in enumerate(L.SYMBOLS)}, index=idx)


def test_live_decision_equals_backtest_decision_day_by_day():
    d = _daily()
    full = rotation_weights(d, risk_off=btc_below_sma200_daily(d['BTCUSDT']), target_vol=0.19)
    for day in d.index[250::7]:
        live = L.decide(d.loc[:day], 0.19)
        pd.testing.assert_series_equal(live, full.loc[day], check_names=False)


def test_stale_data_blocks_orders():
    d = _daily()
    now = d.index[-1] + pd.Timedelta(days=1, minutes=10)
    L.check_fresh(d, now)
    with pytest.raises(RuntimeError):
        L.check_fresh(d, now + pd.Timedelta(days=2))


def _state():
    return {'sleeves': {n: L.new_sleeve() for n in L.SLEEVES}}


def test_kill_switch_flattens_and_halts():
    st = _state()
    prices = {s: 100.0 for s in L.SYMBOLS}
    sl = st['sleeves']['G2-19']
    sl['cash'], sl['qty']['BTCUSDT'], sl['peak'] = 0.0, 50.0, 5_000.0   # 5 000 $ investis
    crash = dict(prices, BTCUSDT=75.0)                                  # -25 % > kill 20 %
    orders, events = L.plan_orders(st, _daily(), crash)
    assert sl['halted']
    assert ('G2-19', 'BTCUSDT', pytest.approx(-50.0)) in [(n, s, q) for n, s, q in orders]
    assert any('KILL SWITCH' in e[1] for e in events)
    L.apply_fill(sl, 'BTCUSDT', -50.0, 75.0)
    # Le lendemain, meme si le marche remonte, l'enveloppe reste a l'arret et ne rachete rien.
    orders2, _ = L.plan_orders(st, _daily(), prices)
    assert not [o for o in orders2 if o[0] == 'G2-19']


def test_daily_loss_blocks_buys_but_allows_sells():
    sl = L.new_sleeve()
    sl['prev_equity'] = 12_000.0
    prices = {s: 100.0 for s in L.SYMBOLS}
    kill, no_buy, why = L.RiskBook('G2-19', L.SLEEVES['G2-19']).assess(sl, prices)
    assert not kill and no_buy
    sl['qty']['ETHUSDT'] = 10.0
    out = L.RiskBook.clip_targets({'BTCUSDT': 5.0, 'ETHUSDT': 2.0, 'SOLUSDT': 0.0}, sl, prices, no_buy=True)
    assert out['BTCUSDT'] == 0.0 and out['ETHUSDT'] == 2.0


def test_no_leverage():
    sl = L.new_sleeve()
    prices = {s: 100.0 for s in L.SYMBOLS}
    out = L.RiskBook.clip_targets({'BTCUSDT': 300.0, 'ETHUSDT': 0.0, 'SOLUSDT': 0.0}, sl, prices, no_buy=False)
    assert out['BTCUSDT'] * 100 == pytest.approx(L.ENVELOPE)


def test_fill_accounting_with_fees():
    buyer, seller = L.new_sleeve(), L.new_sleeve()
    seller['qty']['BTCUSDT'] = 2.0
    L.apply_fill(buyer, 'BTCUSDT', 10.0, 100.0)
    L.apply_fill(seller, 'BTCUSDT', -2.0, 100.0)
    assert buyer['cash'] == pytest.approx(L.ENVELOPE - 1000)
    assert buyer['qty']['BTCUSDT'] == pytest.approx(10 * (1 - L.FEE))   # frais en crypto a l'achat
    assert seller['cash'] == pytest.approx(L.ENVELOPE + 200 * (1 - L.FEE))  # frais en dollars a la vente
    assert seller['qty']['BTCUSDT'] == pytest.approx(0.0)


def test_each_envelope_orders_separately_and_stays_under_approval_threshold():
    st = _state()
    d = _daily()
    prices = d.iloc[-1].to_dict()
    orders, _ = L.plan_orders(st, d, prices)
    assert {o[0] for o in orders} <= set(L.SLEEVES)
    assert all(not L.needs_approval(q, prices[s]) for _, s, q in orders)  # 5 000 $ max sans levier


def test_approval_threshold():
    assert L.needs_approval(60, 100.0) and not L.needs_approval(40, 100.0)


def test_replay_and_bands_on_synthetic_data():
    from bot.run_g2_check import bands, daily_returns, report, replay
    d = _daily(n=800)
    hourly = {s: pd.DataFrame({'open': d[s], 'high': d[s], 'low': d[s], 'close': d[s], 'volume': 0.0}) for s in d}
    rep, start = replay(d, hourly, days=120)
    assert (rep['decisions_differentes'] == 0).all()
    cm = d.copy()
    cm.index = pd.date_range('2015-09-01', periods=len(d), freq='D', tz='UTC')
    b = bands(cm)
    text, ok = report(rep, start, b)
    assert ok and 'G2-40' in text
    assert b['G2-19']['3 mois']['rendement']['p5'] <= b['G2-19']['3 mois']['rendement']['p95']
