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


def _fit_ou_ar1_rolling(cum_resid, window):
    """AR(1) glissant sur le residu cumule, entierement vectorise par pandas.rolling.

    Le score AR(1) X_t = a + b*X_{t-1} + eps est invariant a une translation
    constante de X (a et b ne changent pas, m := a/(1-b) se translate avec X),
    donc on peut faire glisser la regression directement sur la somme cumulee
    globale du residu plutot que de la recalculer a chaque fenetre : seul le
    s-score final, qui est une difference (X_t - m), est physiquement correct.
    """
    x = cum_resid.shift(1)
    y = cum_resid
    pair_window = window - 1

    cov_xy = y.rolling(pair_window).cov(x)
    var_x = x.rolling(pair_window).var()
    var_y = y.rolling(pair_window).var()
    mean_x = x.rolling(pair_window).mean()
    mean_y = y.rolling(pair_window).mean()

    b = cov_xy / var_x
    a = mean_y - b * mean_x
    var_eps = var_y - b * cov_xy

    valid = (b > 0) & (b < 1) & (var_eps > 0)
    b = b.where(valid)

    kappa = -np.log(b) * TRADING_DAYS_YEAR
    m = a / (1 - b)
    sigma_eq = np.sqrt(var_eps / (1 - b ** 2))
    half_life_days = np.log(2) / kappa * TRADING_DAYS_YEAR
    s_score = (y - m) / sigma_eq
    return s_score, half_life_days


def compute_s_scores(residuals, window=OU_WINDOW, max_half_life_days=MAX_HALF_LIFE_DAYS):
    """Pour chaque jour et chaque action : s-score = (X_t - m) / sigma_eq (eq. 11, Velissaris),
    ou X_t est le residu cumule. None/NaN si la vitesse de retour a la moyenne est trop
    lente (half-life > max_half_life_days) ou non estimable.
    """
    s_scores = pd.DataFrame(index=residuals.index, columns=residuals.columns, dtype=float)
    half_lives = pd.DataFrame(index=residuals.index, columns=residuals.columns, dtype=float)

    for ticker in residuals.columns:
        series = residuals[ticker].dropna()
        if len(series) < window + 5:
            continue
        cum_resid = series.cumsum()
        s_score, half_life = _fit_ou_ar1_rolling(cum_resid, window)
        too_slow = half_life > max_half_life_days
        s_score = s_score.where(~too_slow)
        half_life = half_life.where(~too_slow)
        s_scores.loc[s_score.index, ticker] = s_score
        half_lives.loc[half_life.index, ticker] = half_life

    n_signals = s_scores.notna().sum().sum()
    log.info(f'{n_signals} s-scores calcules (fenetre={window}j, half-life max={max_half_life_days}j)')
    return s_scores, half_lives
