import logging
import os
import pandas as pd

from ou_signal import ENTRY_S, EXIT_S

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/pca_live_signals.log')
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

SIGNALS_PATH = os.path.join(DATA_DIR, 'pca_signals_today.csv')


def run(s_scores, half_lives, entry_s=ENTRY_S, exit_s=EXIT_S):
    """Signal actionnable du dernier jour disponible pour chaque action."""
    if s_scores.empty:
        return pd.DataFrame()

    last_date = s_scores.index[-1]
    last_s = s_scores.loc[last_date]
    last_hl = half_lives.loc[last_date]

    rows = []
    for ticker in s_scores.columns:
        s = last_s[ticker]
        if pd.isna(s):
            continue
        if s <= -entry_s:
            action = 'ENTER_LONG_RESIDUAL'
        elif s >= entry_s:
            action = 'ENTER_SHORT_RESIDUAL'
        elif abs(s) <= exit_s:
            action = 'FLAT_OR_EXIT'
        else:
            action = 'HOLD_NO_NEW_ENTRY'
        rows.append({
            'ticker': ticker,
            's_score': round(float(s), 3),
            'half_life_days': round(float(last_hl[ticker]), 1) if pd.notna(last_hl[ticker]) else None,
            'action': action,
        })

    df = pd.DataFrame(rows).sort_values('s_score')
    if not df.empty:
        df.to_csv(SIGNALS_PATH, index=False)
        actionable = df[df['action'].isin(['ENTER_LONG_RESIDUAL', 'ENTER_SHORT_RESIDUAL'])]
        log.info(f'{len(df)} actions evaluees ({last_date.date()}), {len(actionable)} signal(s) actionnable(s) '
                  f'-> {SIGNALS_PATH}')
    return df
