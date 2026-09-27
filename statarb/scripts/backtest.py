import logging
import os
import numpy as np
import pandas as pd

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/backtest.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

ENTRY_Z = 2.0       # ouverture de position quand |z| >= ENTRY_Z
EXIT_Z = 0.5        # cloture quand |z| <= EXIT_Z (retour vers la moyenne)
STOP_Z = 4.0        # cloture forcee si |z| >= STOP_Z (rupture de la relation, cf. "limits of arbitrage")
ZSCORE_WINDOW = 20
TRADING_DAYS_YEAR = 252
MAX_PAIRS = 10


def _positions_from_zscore(z, entry_z, exit_z, stop_z):
    pos = np.zeros(len(z))
    current = 0
    z_vals = z.values
    for i in range(1, len(z_vals)):
        zi = z_vals[i]
        if np.isnan(zi):
            pos[i] = current
            continue
        if current == 0:
            if zi <= -entry_z:
                current = 1     # long le spread : long A, short hedge_ratio*B
            elif zi >= entry_z:
                current = -1    # short le spread
        else:
            if abs(zi) <= exit_z or abs(zi) >= stop_z:
                current = 0
        pos[i] = current
    return pd.Series(pos, index=z.index)


def backtest_pair(prices, ticker_a, ticker_b, hedge_ratio_val,
                   entry_z=ENTRY_Z, exit_z=EXIT_Z, stop_z=STOP_Z, window=ZSCORE_WINDOW):
    pa = prices[ticker_a]
    pb = prices[ticker_b]
    spread = pa - hedge_ratio_val * pb
    mean = spread.rolling(window).mean()
    std = spread.rolling(window).std()
    z = (spread - mean) / std

    position = _positions_from_zscore(z, entry_z, exit_z, stop_z)

    # Rendement journalier de la position, normalise par le capital brut engage
    # (valeur absolue des deux jambes), pour rester comparable entre paires.
    capital_base = (pa.abs() + abs(hedge_ratio_val) * pb.abs()).shift(1)
    pnl = position.shift(1) * spread.diff()
    ret = (pnl / capital_base).fillna(0)

    equity = (1 + ret).cumprod()
    n_years = len(ret) / TRADING_DAYS_YEAR
    total_return = equity.iloc[-1] - 1 if len(equity) else np.nan
    ann_return = equity.iloc[-1] ** (1 / n_years) - 1 if n_years > 0 and equity.iloc[-1] > 0 else np.nan
    ann_vol = ret.std() * np.sqrt(TRADING_DAYS_YEAR)
    sharpe = (ret.mean() * TRADING_DAYS_YEAR) / ann_vol if ann_vol > 0 else np.nan
    drawdown = equity / equity.cummax() - 1
    max_dd = drawdown.min() if len(drawdown) else np.nan
    n_trades = int((position.diff().abs() > 0).sum())

    metrics = {
        'ticker_a': ticker_a, 'ticker_b': ticker_b,
        'total_return': round(total_return, 4) if pd.notna(total_return) else None,
        'annualized_return': round(ann_return, 4) if pd.notna(ann_return) else None,
        'annualized_vol': round(ann_vol, 4) if pd.notna(ann_vol) else None,
        'sharpe': round(sharpe, 3) if pd.notna(sharpe) else None,
        'max_drawdown': round(max_dd, 4) if pd.notna(max_dd) else None,
        'n_trades': n_trades,
    }
    return metrics, ret


def run_portfolio_backtest(prices, pairs_df, max_pairs=MAX_PAIRS):
    """Backteste chaque paire (out-of-sample sur `prices`, hedge_ratio fixe depuis
    la periode de formation) et agrege un portefeuille equipondere."""
    selected = pairs_df.head(max_pairs)
    if selected.empty:
        log.warning('Aucune paire a backtester')
        return pd.DataFrame(), pd.Series(dtype=float)

    all_metrics = []
    returns = {}
    for _, row in selected.iterrows():
        a, b, beta = row['ticker_a'], row['ticker_b'], row['hedge_ratio']
        if a not in prices.columns or b not in prices.columns:
            continue
        metrics, ret = backtest_pair(prices, a, b, beta)
        all_metrics.append(metrics)
        returns[f'{a}_{b}'] = ret
        log.info(f'{a}/{b} : sharpe={metrics["sharpe"]} total_return={metrics["total_return"]} '
                  f'max_dd={metrics["max_drawdown"]} trades={metrics["n_trades"]}')

    metrics_df = pd.DataFrame(all_metrics)
    returns_df = pd.DataFrame(returns)
    portfolio_ret = returns_df.mean(axis=1) if not returns_df.empty else pd.Series(dtype=float)

    if not portfolio_ret.empty:
        equity = (1 + portfolio_ret).cumprod()
        ann_vol = portfolio_ret.std() * np.sqrt(TRADING_DAYS_YEAR)
        sharpe = (portfolio_ret.mean() * TRADING_DAYS_YEAR) / ann_vol if ann_vol > 0 else np.nan
        max_dd = (equity / equity.cummax() - 1).min()
        log.info(f'PORTEFEUILLE ({len(returns)} paires) : sharpe={round(sharpe, 3)} '
                  f'total_return={round(equity.iloc[-1] - 1, 4)} max_dd={round(max_dd, 4)}')

    return metrics_df, portfolio_ret
