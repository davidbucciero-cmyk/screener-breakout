"""Prix quotidiens ajustes (Yahoo) par lots. Les tickers sans historique sont listes, pas inventes."""
import logging

import pandas as pd

log = logging.getLogger(__name__)


def download(tickers, start='2008-06-01', chunk=150):
    import yfinance as yf
    closes, volumes, missing = [], [], []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        df = yf.download(batch, start=start, auto_adjust=True, progress=False, threads=True, group_by='column')
        if df.empty:
            missing += batch
            continue
        c, v = df['Close'], df['Volume']
        if isinstance(c, pd.Series):
            c, v = c.to_frame(batch[0]), v.to_frame(batch[0])
        got = c.columns[c.notna().any()]
        missing += [t for t in batch if t not in got]
        closes.append(c[got].astype('float32'))
        volumes.append(v[got].astype('float32'))
        log.info(f'Prix : {min(i + chunk, len(tickers))}/{len(tickers)} tickers')
    close = pd.concat(closes, axis=1)
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    volume = pd.concat(volumes, axis=1).reindex(close.index)
    return close, volume, missing
