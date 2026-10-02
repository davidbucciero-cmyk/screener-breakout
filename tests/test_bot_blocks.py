import pandas as pd

from bot.blocks import parse_fear_greed, parse_fred_csv, parse_stablecoins, parse_tvl


def test_fear_greed_parsed_daily_sorted():
    js = {'data': [{'value': '30', 'timestamp': '1704153600'}, {'value': '70', 'timestamp': '1704067200'}]}
    s = parse_fear_greed(js)
    assert list(s) == [70.0, 30.0] and str(s.index[0].date()) == '2024-01-01'


def test_defillama_parsers():
    st = parse_stablecoins([{'date': '1704067200', 'totalCirculatingUSD': {'peggedUSD': 1.5e11}}])
    tv = parse_tvl([{'date': 1704067200, 'tvl': 5e10}])
    assert st.iloc[0] == 1.5e11 and tv.iloc[0] == 5e10


def test_fred_csv_drops_missing_values():
    s = parse_fred_csv('observation_date,NASDAQCOM\n2024-01-01,.\n2024-01-02,14765.94\n', 'nasdaq')
    assert len(s) == 1 and s.iloc[0] == 14765.94 and s.index[0] == pd.Timestamp('2024-01-02', tz='UTC')
