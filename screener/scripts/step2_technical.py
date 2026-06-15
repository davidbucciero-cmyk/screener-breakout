import pandas as pd
import numpy as np
import sqlite3
import logging
import os
from datetime import datetime
import yfinance as yf

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data/screener.db')
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/technical.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

def load_universe():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql('SELECT ticker FROM universe', conn)
    conn.close()
    log.info(f'Univers charge : {len(df)} tickers')
    return df['ticker'].tolist()

def compute_obv(close, volume):
    obv = [0]
    for i in range(1, len(close)):
        if close.iloc[i] > close.iloc[i-1]:
            obv.append(obv[-1] + volume.iloc[i])
        elif close.iloc[i] < close.iloc[i-1]:
            obv.append(obv[-1] - volume.iloc[i])
        else:
            obv.append(obv[-1])
    return pd.Series(obv, index=close.index)

def compute_signals(ticker, data):
    try:
        close = data['Close'].dropna()
        volume = data['Volume'].dropna()
        high = data['High'].dropna()
        low = data['Low'].dropna()
        if len(close) < 50:
            return None
        obv = compute_obv(close, volume)
        obv_sma20 = obv.rolling(20).mean()
        obv_trend = 1 if obv.iloc[-1] > obv_sma20.iloc[-1] else 0
        vol_ratio = volume.iloc[-1] / volume.rolling(20).mean().iloc[-1] if volume.rolling(20).mean().iloc[-1] > 0 else 0
        vol_dryup = 1 if volume.tail(5).mean() < volume.rolling(20).mean().iloc[-1] * 0.7 else 0
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_width = (bb_upper - bb_lower) / sma20
        bb_width_min = bb_width.rolling(125).min()
        bb_squeeze = 1 if bb_width.iloc[-1] <= bb_width_min.iloc[-1] * 1.05 else 0
        tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()
        atr_declining = 1 if atr14.iloc[-1] > atr14.iloc[-10] else 0
        recent_high = close.tail(20).max()
        recent_low = close.tail(20).min()
        flat_base = 1 if (recent_high - recent_low) / recent_low < 0.15 else 0
        lows = low.tail(60)
        local_lows = lows[lows == lows.rolling(5, center=True).min()].tail(3)
        higher_lows = 1 if len(local_lows) >= 2 and local_lows.is_monotonic_increasing else 0
        clv = ((close - low) - (high - close)) / (high - low + 1e-9)
        ad = (clv * volume).cumsum()
        ad_trend = 1 if ad.iloc[-1] > ad.rolling(20).mean().iloc[-1] else 0
        score = obv_trend + (1 if vol_ratio > 1.5 else 0) + vol_dryup + bb_squeeze + atr_declining + flat_base + (higher_lows * 2) + (ad_trend * 2)
        return {'ticker': ticker, 'obv_trend': obv_trend, 'vol_ratio': round(vol_ratio, 2), 'vol_dryup': vol_dryup, 'bb_squeeze': bb_squeeze, 'atr_declining': atr_declining, 'flat_base': flat_base, 'higher_lows': higher_lows, 'ad_trend': ad_trend, 'rs_line': 0, 'technical_score': score, 'updated_at': datetime.now().isoformat()}
    except Exception as e:
        log.debug(f'Erreur {ticker} : {e}')
        return None

def run():
    log.info('=' * 60)
    log.info('STEP 2 - SIGNAUX TECHNIQUES')
    log.info('=' * 60)
    tickers = load_universe()
    log.info('Download IWM...')
    iwm_data = yf.download('IWM', period='6mo', interval='1d', auto_adjust=True, progress=False)
    iwm_close = iwm_data['Close'].dropna()
    results = []
    batch_size = 50
    total_batches = (len(tickers) + batch_size - 1) // batch_size
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i+batch_size]
        log.info(f'Batch {i//batch_size+1}/{total_batches}')
        try:
            data = yf.download(batch, period='1y', interval='1d', group_by='ticker', auto_adjust=True, threads=True, progress=False)
            for ticker in batch:
                try:
                    t_data = data[ticker] if ticker in data.columns.get_level_values(0) else None
                    if t_data is None or t_data.empty:
                        continue
                    signals = compute_signals(ticker, t_data)
                    if signals:
                        try:
                            t_close = t_data['Close'].dropna()
                            common = t_close.index.intersection(iwm_close.index)
                            if len(common) >= 20:
                                rs = t_close[common] / iwm_close[common]
                                rs_trend = 1 if rs.iloc[-1] > rs.rolling(20).mean().iloc[-1] else 0
                                signals['rs_line'] = rs_trend
                                signals['technical_score'] += rs_trend
                        except Exception:
                            pass
                        results.append(signals)
                except Exception as e:
                    log.debug(f'Erreur {ticker} : {e}')
        except Exception as e:
            log.error(f'Erreur batch : {e}')
    df = pd.DataFrame(results)
    if df.empty:
        log.warning('Aucun signal calcule')
        return
    conn = sqlite3.connect(DB_PATH)
    df.to_sql('technical_signals', conn, if_exists='replace', index=False)
    conn.close()
    log.info(f'Signaux sauvegardes : {len(df)} tickers')
    log.info(f'Score moyen : {df["technical_score"].mean():.1f}/10')
    top10 = df.nlargest(10, 'technical_score')[['ticker', 'technical_score', 'flat_base', 'bb_squeeze', 'obv_trend', 'ad_trend', 'higher_lows']]
    log.info(f'Top 10 :\n{top10.to_string()}')
    return df

if __name__ == '__main__':
    run()