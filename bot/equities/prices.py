"""Prix quotidiens ajustes (Yahoo) par lots, et historique des splits.

Les prix Yahoo sont ajustes des splits passes : pour calculer une capitalisation historique, le nombre
d'actions declare a la SEC doit etre ramene sur la meme base (voir features.to_price_basis).
Les tickers sans historique sont listes, pas inventes."""
import logging

import pandas as pd

log = logging.getLogger(__name__)


def download(tickers, start='2008-06-01', chunk=150):
    import yfinance as yf
    closes, volumes, splits, missing = [], [], [], []
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        df = yf.download(batch, start=start, auto_adjust=True, actions=True, progress=False, threads=True,
                         group_by='column')
        if df.empty:
            missing += batch
            continue
        c, v = df['Close'], df['Volume']
        if isinstance(c, pd.Series):
            c, v = c.to_frame(batch[0]), v.to_frame(batch[0])
        got = c.columns[c.notna().any()]
        missing += [t for t in batch if t not in got]
        if 'Stock Splits' in df:
            sp = df['Stock Splits']
            sp = sp.to_frame(batch[0]) if isinstance(sp, pd.Series) else sp
            sp = sp[got].stack()
            sp = sp[(sp > 0) & (sp != 1)]
            splits.append(pd.DataFrame({'date': sp.index.get_level_values(0), 'ticker': sp.index.get_level_values(1),
                                        'ratio': sp.to_numpy(dtype=float)}))
        closes.append(c[got].astype('float32'))
        volumes.append(v[got].astype('float32'))
        log.info(f'Prix : {min(i + chunk, len(tickers))}/{len(tickers)} tickers')
    close = pd.concat(closes, axis=1)
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    volume = pd.concat(volumes, axis=1).reindex(close.index)
    split_df = pd.concat(splits, ignore_index=True) if splits else pd.DataFrame(columns=['date', 'ticker', 'ratio'])
    split_df['date'] = pd.to_datetime(split_df['date']).dt.tz_localize(None)
    return close, volume, missing, split_df
