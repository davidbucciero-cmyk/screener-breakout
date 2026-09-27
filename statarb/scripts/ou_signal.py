import logging
import os
import numpy as np
import pandas as pd

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/ou_signal.log')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)

# Fenetre de re-cumulation du residu et seuils de trading (Velissaris, 2010 ;
# Avellaneda & Lee, 2010). Seuils legerement plus serres que Avellaneda-Lee (1.25/0.50)
# car on ferme les positions plus tot, ce qui reduit la volatilite (cf. Velissaris section II).
OU_WINDOW = 60
ENTRY_S = 1.25
EXIT_S = 0.75
MAX_HALF_LIFE_DAYS = 30
TRADING_DAYS_YEAR = 252


def _fit_ou_ar1(cum_resid):
    """AR(1) sur le residu cumule -> (kappa annualise, m, sigma_eq, half-life en jours)."""
    y = cum_resid[1:]
    x = cum_resid[:-1]
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    a, b = beta[0], beta[1]
    if not (0 < b < 1):
        return None
    resid_ar1 = y - X @ beta
    var_eps = np.var(resid_ar1, ddof=2)

    kappa = -np.log(b) * TRADING_DAYS_YEAR
    m = a / (1 - b)
    sigma2 = var_eps * 2 * kappa / (1 - b ** 2)
    if sigma2 <= 0 or kappa <= 0:
        return None
    sigma_eq = np.sqrt(sigma2 / (2 * kappa))
    half_life_days = np.log(2) / kappa * TRADING_DAYS_YEAR
    return kappa, m, sigma_eq, half_life_days


def compute_s_scores(residuals, window=OU_WINDOW, max_half_life_days=MAX_HALF_LIFE_DAYS):
    """Pour chaque jour et chaque action : s-score = (X_t - m) / sigma_eq (eq. 11, Velissaris),
    ou X_t est le residu cumule sur les `window` derniers jours. None/NaN si la vitesse de
    retour a la moyenne est trop lente (half-life > max_half_life_days) ou non estimable.
    """
    dates = residuals.index
    tickers = residuals.columns
    s_scores = pd.DataFrame(index=dates, columns=tickers, dtype=float)
    half_lives = pd.DataFrame(index=dates, columns=tickers, dtype=float)

    for ticker in tickers:
        series = residuals[ticker].dropna()
        if len(series) < window + 5:
            continue
        values = series.values
        idx = series.index
        for i in range(window, len(values)):
            cum_resid = np.cumsum(values[i - window:i])
            fit = _fit_ou_ar1(cum_resid)
            if fit is None:
                continue
            kappa, m, sigma_eq, hl = fit
            if hl > max_half_life_days:
                continue
            s_scores.loc[idx[i], ticker] = (cum_resid[-1] - m) / sigma_eq
            half_lives.loc[idx[i], ticker] = hl

    n_signals = s_scores.notna().sum().sum()
    log.info(f'{n_signals} s-scores calcules (fenetre={window}j, half-life max={max_half_life_days}j)')
    return s_scores, half_lives
