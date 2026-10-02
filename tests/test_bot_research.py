import numpy as np
import pandas as pd

import bot.research as rs


def _btc(n=2500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2018-01-01', periods=n, freq='D', tz='UTC')
    return pd.Series(10000 * np.exp(np.cumsum(rng.normal(0, 0.03, n))), index=idx)


def test_target_is_forward_7_days():
    c = _btc()
    y = rs.target(c)
    assert y.iloc[0] == np.log(c.iloc[7] / c.iloc[0])
    assert y.iloc[-7:].isna().all()


def test_ic_never_reads_out_of_sample(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, 'DATA', tmp_path)
    c = _btc()
    f = rs.build_features(c)
    y = rs.target(c)
    # Une feature "parfaite" uniquement hors echantillon ne doit rien changer a l'IC mesure.
    f['triche'] = 0.0
    f.loc[f.index >= rs.OOS_START - pd.Timedelta(days=7), 'triche'] = y
    rng = np.random.default_rng(1)
    f.loc[f.index < rs.OOS_START - pd.Timedelta(days=7), 'triche'] = rng.normal(size=(f.index < rs.OOS_START - pd.Timedelta(days=7)).sum())
    table = rs.information_coefficients(f, y).set_index('feature')
    assert abs(table.loc['triche', 'ic']) < 0.15


def test_publication_lag_shifts_onchain(monkeypatch, tmp_path):
    monkeypatch.setattr(rs, 'DATA', tmp_path)
    idx = pd.date_range('2020-01-01', periods=10, freq='D', tz='UTC')
    pd.DataFrame({'AdrActCnt': range(10)}, index=idx).to_csv(tmp_path / '8.csv')
    df = rs._load('8')
    assert df.loc[pd.Timestamp('2020-01-02', tz='UTC'), 'AdrActCnt'] == 0  # valeur du 1er connue le 2
