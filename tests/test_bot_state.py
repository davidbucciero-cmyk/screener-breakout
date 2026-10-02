import numpy as np
import pandas as pd

from bot.state import FEATURES, build_snapshots, snapshot_at


def _candles(n=24 * 200, seed=0):
    rng = np.random.default_rng(seed)
    close = 30000 * np.exp(np.cumsum(rng.normal(0, 0.005, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n))
    volume = rng.uniform(10, 100, n)
    idx = pd.date_range('2024-01-01', periods=n, freq='h', tz='UTC')
    return pd.DataFrame({'open': open_, 'high': high, 'low': low, 'close': close,
                         'volume': volume, 'taker_buy_volume': volume * rng.uniform(0.3, 0.7, n)}, index=idx)


def test_snapshot_indexed_at_decision_time():
    df = _candles()
    snap = build_snapshots(df)
    # La bougie ouverte a 10:00 cloture a 11:00 : son snapshot sert a la decision de 11:00.
    assert snap.index[0] == df.index[0] + pd.Timedelta(hours=1)
    assert list(snap.columns) == FEATURES


def test_no_lookahead_future_candles_do_not_change_past_snapshots():
    df = _candles()
    snap = build_snapshots(df)
    cut = len(df) - 500
    decision = df.index[cut]  # decision a l'ouverture de la bougie `cut`, qui n'est pas encore cloturee
    tampered = df.copy()
    tampered.iloc[cut:, :] *= 3.0  # on falsifie la bougie en cours et tout le futur
    snap2 = build_snapshots(tampered)
    pd.testing.assert_series_equal(snap.loc[decision], snap2.loc[decision])
    assert not snap.iloc[-1].equals(snap2.iloc[-1])


def test_snapshot_at_uses_only_closed_candles():
    df = _candles()
    decision = df.index[-100]
    expected = build_snapshots(df).loc[decision]
    live = snapshot_at(df, decision)  # df contient le futur : snapshot_at doit l'ignorer
    pd.testing.assert_series_equal(live, expected)


def test_snapshot_is_compact_and_numeric():
    snap = build_snapshots(_candles()).dropna()
    assert len(snap) > 0
    assert all(np.issubdtype(t, np.floating) for t in snap.dtypes)
    assert snap['taker_buy_24h'].between(0, 1).all()
    assert (snap['flag_range_12h'] >= 0).all()
