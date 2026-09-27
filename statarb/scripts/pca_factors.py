import logging
import os
import numpy as np
import pandas as pd

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/pca_factors.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

# Parametres de la methode Avellaneda & Lee (2010) / Velissaris (2010) :
# PCA glissante sur 252j (~1 an) pour extraire les facteurs de risque systematique,
# puis regression glissante sur 60j pour estimer l'exposition (beta) de chaque action
# a ces facteurs. Le residu du jour t est calcule hors-echantillon (out-of-sample) :
# aucune information posterieure a t-1 n'entre dans son calcul.
PCA_WINDOW = 252
LOADING_WINDOW = 60
N_FACTORS = 5


def compute_daily_residuals(returns, n_factors=N_FACTORS, pca_window=PCA_WINDOW, loading_window=LOADING_WINDOW):
    """Residus idiosyncratiques quotidiens hors-echantillon (Avellaneda & Lee, 2010).

    Pour chaque jour t : PCA sur les rendements standardises des `pca_window` jours
    precedant la fenetre de regression, eigenportefeuilles Q_j(i) = v_j(i)/sigma_i (eq. 5),
    rendements des facteurs F_j, puis regression OLS de chaque action sur ces facteurs
    sur les `loading_window` derniers jours pour obtenir le residu du jour t.
    """
    dates = returns.index
    tickers = returns.columns
    resid = pd.DataFrame(index=dates, columns=tickers, dtype=float)

    start = pca_window + loading_window
    if len(dates) <= start:
        log.error(f'Historique insuffisant : {len(dates)}j disponibles, {start}j requis')
        return resid

    for t in range(start, len(dates)):
        pca_block = returns.iloc[t - pca_window - loading_window:t - loading_window]
        std = pca_block.std()
        valid = std[std > 0].index
        pca_block = pca_block[valid]
        if pca_block.shape[1] < n_factors + 1:
            continue

        standardized = (pca_block - pca_block.mean()) / pca_block.std()
        corr = standardized.corr().values
        eigvals, eigvecs = np.linalg.eigh(corr)
        order = np.argsort(eigvals)[::-1][:n_factors]
        eigvecs = eigvecs[:, order]

        sigma = pca_block.std().values
        Q = eigvecs / sigma[:, None]  # eigenportfolio weights, eq. (5)

        loading_block = returns[valid].iloc[t - loading_window:t]
        factor_rets = loading_block.values @ Q  # (loading_window, n_factors)

        X = np.column_stack([np.ones(loading_window), factor_rets])
        Y = loading_block.values  # (loading_window, n_stocks)
        beta, *_ = np.linalg.lstsq(X, Y, rcond=None)  # (1+n_factors, n_stocks)

        today_rets = returns[valid].iloc[t].values
        factor_rets_today = today_rets @ Q
        x_today = np.concatenate([[1.0], factor_rets_today])
        pred_today = x_today @ beta
        resid.loc[dates[t], valid] = today_rets - pred_today

    n_days = resid.notna().any(axis=1).sum()
    log.info(f'Residus calcules pour {n_days} jours (K={n_factors} facteurs, '
              f'fenetre PCA={pca_window}j, fenetre loadings={loading_window}j)')
    return resid
