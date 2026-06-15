from openbb import obb
result = obb.equity.fundamental.income(symbol='HCSG', provider='yfinance', period='annual', limit=3)
df = result.to_df()
print(df.columns.tolist())
print(df.head())