import itertools
import logging
import os
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

from universe import SECTOR_UNIVERSE

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/cointegration.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

PVALUE_THRESHOLD = 0.05
MIN_HALF_LIFE = 3
MAX_HALF_LIFE = 90
MIN_COMMON_DAYS = 250


def hedge_ratio(y, x):
    """Regression OLS y = alpha + beta*x (methode Engle-Granger, 1e etape)."""
    model = OLS(y.values, add_constant(x.values)).fit()
    alpha, beta = model.params[0], model.params[1]
    return beta, alpha


def half_life(spread):
    """Demi-vie de retour a la moyenne via AR(1) sur le spread (Ornstein-Uhlenbeck discret)."""
    spread = spread.dropna()
    lag = spread.shift(1)
    delta = spread.diff()
    df = pd.concat([lag, delta], axis=1).dropna()
    df.columns = ['lag', 'delta']
    if len(df) < 30:
        return np.inf
    model = OLS(df['delta'].values, add_constant(df['lag'].values)).fit()
    theta = model.params[1]
    if theta >= 0:
        return np.inf
    return -np.log(2) / theta


def find_cointegrated_pairs(prices, sector_universe=None, pvalue_threshold=PVALUE_THRESHOLD,
                             min_half_life=MIN_HALF_LIFE, max_half_life=MAX_HALF_LIFE):
    """Teste la cointegration Engle-Granger sur chaque paire intra-secteur.

    prices : DataFrame de prix ajustes (colonnes = tickers), typiquement restreint
    a la periode de formation pour eviter le look-ahead lors du backtest.
    """
    sector_universe = sector_universe or SECTOR_UNIVERSE
    results = []
    n_tested = 0
    for sector, tickers in sector_universe.items():
        avail = [t for t in tickers if t in prices.columns]
        for a, b in itertools.combinations(avail, 2):
            n_tested += 1
            pa, pb = prices[a].dropna(), prices[b].dropna()
            common = pa.index.intersection(pb.index)
            if len(common) < MIN_COMMON_DAYS:
                continue
            pa, pb = pa.loc[common], pb.loc[common]
            try:
                _, pvalue, _ = coint(pa, pb)
            except Exception as e:
                log.debug(f'coint() echoue {a}/{b} : {e}')
                continue
            if pvalue > pvalue_threshold:
                continue
            beta, alpha = hedge_ratio(pa, pb)
            spread = pa - beta * pb
            hl = half_life(spread)
            if not (min_half_life <= hl <= max_half_life):
                continue
            results.append({
                'ticker_a': a, 'ticker_b': b, 'sector': sector,
                'coint_pvalue': round(pvalue, 5), 'hedge_ratio': round(beta, 4),
                'alpha': round(alpha, 4), 'half_life_days': round(hl, 1),
                'correlation': round(pa.corr(pb), 3),
            })

    log.info(f'{n_tested} paires testees, {len(results)} retenues (p<{pvalue_threshold}, '
              f'half-life in [{min_half_life},{max_half_life}]j)')
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values('coint_pvalue').reset_index(drop=True)
    return df
