import logging
import os
import numpy as np
import pandas as pd

from ou_signal import ENTRY_S, EXIT_S, TRADING_DAYS_YEAR

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/pca_backtest.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)


def _positions_from_s_scores(s_scores, entry_s=ENTRY_S, exit_s=EXIT_S):
    """Position {-1,0,+1} par action avec hysteresis (entree a `entry_s`, sortie a `exit_s`),
    au sens du residu : +1 = long le residu (achete si s <= -entry_s, i.e. sous-evalue),
    -1 = short le residu (vendu si s >= +entry_s, i.e. sur-evalue)."""
    positions = pd.DataFrame(0.0, index=s_scores.index, columns=s_scores.columns)
    current = {ticker: 0 for ticker in s_scores.columns}
    values = s_scores.values
    for i in range(len(s_scores)):
        row = values[i]
        for j, ticker in enumerate(s_scores.columns):
            s = row[j]
            pos = current[ticker]
            if np.isnan(s):
                if pos != 0:
                    positions.iloc[i, j] = pos
                continue
            if pos == 0:
                if s <= -entry_s:
                    pos = 1
                elif s >= entry_s:
                    pos = -1
            else:
                if abs(s) <= exit_s:
                    pos = 0
            current[ticker] = pos
            positions.iloc[i, j] = pos
    return positions


def run_pca_backtest(residuals, s_scores, entry_s=ENTRY_S, exit_s=EXIT_S):
    """Simule le portefeuille d'arbitrage statistique : chaque action active recoit un poids
    egal en valeur absolue (les poids bruts sont normalises a somme|w|=1 chaque jour, comme
    dans Guijarro-Ordonez et al. 2024, eq. 3), et le rendement du jour est le rendement du
    residu (deja neutre au marche par construction, cf. section 2.1 du meme papier)."""
    positions = _positions_from_s_scores(s_scores, entry_s, exit_s)
    gross = positions.abs().sum(axis=1)
    weights = positions.div(gross.replace(0, np.nan), axis=0).fillna(0.0)

    daily_ret = (weights.shift(1).fillna(0.0) * residuals.fillna(0.0)).sum(axis=1)
    daily_ret = daily_ret[gross.shift(1).fillna(0) > 0]

    if daily_ret.empty:
        log.warning('Aucune position ouverte sur la periode de backtest')
        return {}, daily_ret, positions

    equity = (1 + daily_ret).cumprod()
    n_years = len(daily_ret) / TRADING_DAYS_YEAR
    total_return = equity.iloc[-1] - 1
    ann_return = equity.iloc[-1] ** (1 / n_years) - 1 if n_years > 0 and equity.iloc[-1] > 0 else np.nan
    ann_vol = daily_ret.std() * np.sqrt(TRADING_DAYS_YEAR)
    sharpe = (daily_ret.mean() * TRADING_DAYS_YEAR) / ann_vol if ann_vol > 0 else np.nan
    drawdown = equity / equity.cummax() - 1
    max_dd = drawdown.min()
    avg_n_positions = gross[gross > 0].mean()

    metrics = {
        'n_days': len(daily_ret),
        'total_return': round(float(total_return), 4),
        'annualized_return': round(float(ann_return), 4) if pd.notna(ann_return) else None,
        'annualized_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 3) if pd.notna(sharpe) else None,
        'max_drawdown': round(float(max_dd), 4),
        'avg_active_positions': round(float(avg_n_positions), 1),
    }
    log.info(f'Backtest PCA stat-arb : sharpe={metrics["sharpe"]} total_return={metrics["total_return"]} '
              f'max_dd={metrics["max_drawdown"]} positions_actives_moy={metrics["avg_active_positions"]}')
    return metrics, daily_ret, positions
