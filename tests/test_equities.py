import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from bot.equities.features import FEATURES, build_panel, information_coefficients, insider_cluster_spread
from bot.equities.insiders import parse_quarter

N = 40


def _data(years=4, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2015-01-01', periods=252 * years)
    tick = [f'T{i}' for i in range(N)]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, (len(idx), N)), axis=0)), index=idx, columns=tick)
    tickers = pd.DataFrame({'cik': range(N), 'ticker': tick})
    ends = pd.date_range('2014-12-31', idx[-1], freq='QE')
    shares = pd.DataFrame([(c, e, 1e8 * (1 + 0.01 * c)) for c in range(N) for e in ends], columns=['cik', 'end', 'val'])
    fund = pd.DataFrame([(c, y, 1e9 + c * 1e7 + y, 4e8, 1e8, 1.2e8, 5e9, pd.Timestamp(f'{y}-12-31'))
                         for c in range(N) for y in range(2014, 2015 + years)],
                        columns=['cik', 'year', 'revenue', 'gross_profit', 'net_income', 'cfo', 'assets', 'period_end'])
    fund['available'] = fund['period_end'] + pd.Timedelta(days=90)
    purch = pd.DataFrame({'filing_date': [pd.Timestamp('2017-03-10'), pd.Timestamp('2017-03-20'), pd.Timestamp('2017-04-05')],
                          'cik': [3, 3, 3], 'owner': ['a', 'b', 'c'], 'value': [1e5, 2e5, 3e5]})
    return close, tickers, shares, fund, purch


def test_panel_ignores_future_prices():
    close, tickers, shares, fund, purch = _data()
    p1 = build_panel(close, tickers, shares, fund, purch).set_index(['date', 'ticker'])
    cut = pd.Timestamp('2017-06-30')
    tampered = close.copy()
    tampered.loc[tampered.index > cut] *= 3
    p2 = build_panel(tampered, tickers, shares, fund, purch).set_index(['date', 'ticker'])
    d = p1.index.get_level_values('date')
    past = p1[d <= cut].index
    pd.testing.assert_frame_equal(p1.loc[past, FEATURES], p2.loc[past, FEATURES])


def test_insider_counts_by_filing_date():
    close, tickers, shares, fund, purch = _data()
    p = build_panel(close, tickers, shares, fund, purch).set_index(['date', 'ticker'])
    march = p.loc[(pd.Timestamp('2017-03-31'), 'T3')]
    april = p.loc[(pd.Timestamp('2017-04-28'), 'T3')]
    assert march['A1_initie_acheteurs_90j'] == 2   # le 3e initié publie le 5 avril
    assert april['A1_initie_acheteurs_90j'] == 3
    assert p.loc[(pd.Timestamp('2017-03-31'), 'T4'), 'A1_initie_acheteurs_90j'] == 0


def test_fundamentals_only_after_availability():
    close, tickers, shares, fund, purch = _data()
    p = build_panel(close, tickers, shares, fund, purch).set_index(['date', 'ticker'])
    # Comptes 2016 disponibles le 31/03/2017 : fin fevrier, on voit encore 2015.
    feb = p.loc[(pd.Timestamp('2017-02-28'), 'T0'), 'A2_croissance_ca_1an']
    apr = p.loc[(pd.Timestamp('2017-04-28'), 'T0'), 'A2_croissance_ca_1an']
    assert feb == pytest.approx((1e9 + 2015) / (1e9 + 2014) - 1)
    assert apr == pytest.approx((1e9 + 2016) / (1e9 + 2015) - 1)


def test_ic_detects_planted_signal_only_in_dev():
    close, tickers, shares, fund, purch = _data()
    p = build_panel(close, tickers, shares, fund, purch)
    p['B4_rendement_1m'] = p['fwd_ret']  # signal parfait
    ic = information_coefficients(p, end_dev='2017-12-31').set_index('feature')
    assert ic.loc['B4_rendement_1m', 'ic_moyen'] > 0.99
    assert ic.loc['B4_rendement_1m', 'mois'] <= 36


def test_insider_spread_runs():
    close, tickers, shares, fund, purch = _data()
    s = insider_cluster_spread(build_panel(close, tickers, shares, fund, purch), end_dev='2018-06-30')
    assert s['mois'] >= 1


def _zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def test_parse_form345_keeps_open_market_purchases():
    raw = _zip({
        'SUBMISSION.tsv': 'ACCESSION_NUMBER\tFILING_DATE\tISSUERCIK\tISSUERTRADINGSYMBOL\nA1\t05-JAN-2023\t320193\taapl\nA2\t06-JAN-2023\t320193\tAAPL\n',
        'NONDERIV_TRANS.tsv': 'ACCESSION_NUMBER\tTRANS_CODE\tTRANS_SHARES\tTRANS_PRICEPERSHARE\nA1\tP\t100\t150\nA2\tS\t50\t150\n',
        'REPORTINGOWNER.tsv': 'ACCESSION_NUMBER\tRPTOWNERCIK\nA1\t999\nA2\t998\n',
    })
    df = parse_quarter(raw)
    assert len(df) == 1
    r = df.iloc[0]
    assert r['ticker'] == 'AAPL' and r['value'] == 15000 and r['filing_date'] == pd.Timestamp('2023-01-05')


def test_audit_flags_extremes_and_yearly_compounding():
    from bot.equities.audit import yearly_from_monthly
    m = pd.Series([0.1, 0.1], index=pd.to_datetime(['2020-11-30', '2020-12-31']))
    y = yearly_from_monthly(m)
    assert y.loc[2020] == pytest.approx(0.1) and y.loc[2021] == pytest.approx(0.1)  # mois de rendement = mois suivant


def test_reverse_split_does_not_inflate_market_cap_or_fake_buybacks():
    close, tickers, shares, fund, purch = _data()
    # T7 : penny stock a 1 $ avec 1 Md d'actions (cap 1 Md$), regroupement 1 pour 100 le 2017-01-03.
    split_day = pd.Timestamp('2017-01-03')
    raw = pd.Series(1.0, index=close.index)
    raw[close.index >= split_day] = 100.0
    close['T7'] = raw / np.where(close.index < split_day, 0.01, 1.0)  # prix Yahoo : passe ajuste (x100)
    rows = shares['cik'] == 7
    shares.loc[rows, 'val'] = np.where(shares.loc[rows, 'end'] < split_day, 1e9, 1e7)
    splits = pd.DataFrame({'date': [split_day], 'ticker': ['T7'], 'ratio': [0.01]})
    without = build_panel(close, tickers, shares, fund, purch).set_index(['date', 'ticker'])
    fixed = build_panel(close, tickers, shares, fund, purch, splits).set_index(['date', 'ticker'])
    d = pd.Timestamp('2016-06-30')
    assert (d, 'T7') in without.index            # sans correction : cap fictive 100 Md$, entre dans l'univers
    assert (d, 'T7') not in fixed.index          # avec correction : 1 Md$, hors univers
    assert without.loc[(d, 'T7'), 'mcap'] == pytest.approx(1e11)
