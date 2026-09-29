import json

import pandas as pd
import pytest

import btc_forecast.paper as P
from test_trend import synthetic_daily


@pytest.fixture
def fake_market(tmp_path, monkeypatch):
    """3 cryptos synthetiques ; `days` controle la date de la derniere bougie cloturee."""
    full = {s: synthetic_daily(900, seed=i) for i, s in enumerate(P.SYMBOLS)}
    days = {'n': 600}
    monkeypatch.setattr(P, 'DIR', str(tmp_path))
    monkeypatch.setattr(P, 'fetch_btc', lambda interval, bars, symbol: full[symbol].iloc[:days['n']].iloc[-bars:])
    return full, days, tmp_path


def test_paper_step_idempotent_and_consistent(fake_market):
    full, days, tmp = fake_market
    date, start, total, bench, lines = P.step()
    assert date == start == full['BTCUSDT'].index[599].strftime('%Y-%m-%d')
    assert P.step() is None  # meme journee : rien
    for _ in range(50):
        days['n'] += 1
        assert P.step() is not None

    state = json.load(open(tmp / 'state.json'))
    equity = pd.read_csv(tmp / 'equity.csv')
    assert len(equity) == 51 and equity['date'].is_unique
    for s, sl in state['sleeves'].items():
        assert sl['qty'] >= -1e-12 and sl['cash'] >= -1e-6  # jamais de levier ni de short
        assert 0 <= equity[f'{s}_exposure'].iloc[-1] <= 1 + 1e-9
    # La valeur totale = somme des poches, et les frais ne sont payes que sur les ordres.
    last = equity.iloc[-1]
    assert last['total'] == pytest.approx(sum(last[f'{s}_value'] for s in P.SYMBOLS), abs=0.05)
    trades = pd.read_csv(tmp / 'trades.csv')
    assert trades['fee'].to_numpy() == pytest.approx((trades['notional'] * P.FEE_BPS / 1e4).to_numpy(), abs=1e-3)
    assert len(trades) > 0


def test_target_matches_backtest_logic():
    df = synthetic_daily(600)
    target, ensemble, vol = P.target_exposure(df)
    assert 0 <= target <= 1
    assert ensemble in {0, 0.25, 0.5, 0.75, 1}
    if ensemble == 0:
        assert target == 0
