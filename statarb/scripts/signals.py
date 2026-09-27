import logging
import os
import pandas as pd

from backtest import ZSCORE_WINDOW, ENTRY_Z, EXIT_Z

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/signals.log')
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

SIGNALS_PATH = os.path.join(DATA_DIR, 'signals_today.csv')


def compute_live_signal(prices, ticker_a, ticker_b, hedge_ratio_val, alloc_usd,
                         window=ZSCORE_WINDOW, entry_z=ENTRY_Z, exit_z=EXIT_Z):
    pa = prices[ticker_a]
    pb = prices[ticker_b]
    spread = pa - hedge_ratio_val * pb
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    z = (spread - mean) / std

    z_last = z.iloc[-1]
    price_a_last = pa.iloc[-1]
    price_b_last = pb.iloc[-1]

    if pd.isna(z_last):
        return None

    if z_last <= -entry_z:
        action = 'ENTER_LONG_SPREAD'   # BUY ticker_a, SELL ticker_b
    elif z_last >= entry_z:
        action = 'ENTER_SHORT_SPREAD'  # SELL ticker_a, BUY ticker_b
    elif abs(z_last) <= exit_z:
        action = 'FLAT_OR_EXIT'
    else:
        action = 'HOLD_NO_NEW_ENTRY'

    # Dimensionnement neutre au ratio de couverture : qty_a : qty_b = 1 : hedge_ratio,
    # de sorte que la position reste insensible aux mouvements communs des deux titres
    # (seul l'ecart entre A et hedge_ratio*B est trade).
    denom = price_a_last + abs(hedge_ratio_val) * price_b_last
    qty_a = alloc_usd / denom if denom > 0 else 0
    qty_b = qty_a * hedge_ratio_val

    return {
        'ticker_a': ticker_a, 'ticker_b': ticker_b,
        'zscore': round(float(z_last), 3),
        'action': action,
        'hedge_ratio': round(float(hedge_ratio_val), 4),
        'price_a': round(float(price_a_last), 2),
        'price_b': round(float(price_b_last), 2),
        'side_a': 'BUY' if action == 'ENTER_LONG_SPREAD' else ('SELL' if action == 'ENTER_SHORT_SPREAD' else '-'),
        'side_b': 'SELL' if action == 'ENTER_LONG_SPREAD' else ('BUY' if action == 'ENTER_SHORT_SPREAD' else '-'),
        'qty_a': round(float(qty_a)),
        'qty_b': round(float(abs(qty_b))),
    }


def run(prices, pairs_df, alloc_usd, max_pairs):
    rows = []
    for _, row in pairs_df.head(max_pairs).iterrows():
        a, b, beta = row['ticker_a'], row['ticker_b'], row['hedge_ratio']
        if a not in prices.columns or b not in prices.columns:
            continue
        sig = compute_live_signal(prices, a, b, beta, alloc_usd)
        if sig:
            rows.append(sig)

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(SIGNALS_PATH, index=False)
        actionable = df[df['action'].isin(['ENTER_LONG_SPREAD', 'ENTER_SHORT_SPREAD'])]
        log.info(f'{len(df)} paires evaluees, {len(actionable)} signal(s) actionnable(s) -> {SIGNALS_PATH}')
    return df
