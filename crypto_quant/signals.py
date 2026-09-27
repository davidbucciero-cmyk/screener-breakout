"""Socle de signaux statistiques (etape 2).

Quatre briques independantes, chacune capture une information differente :

- hurst_exponent / rolling_hurst : classificateur de regime (tendanciel vs
  retour a la moyenne), sert a arbitrer entre les deux signaux directionnels
  a l'etape 3.
- ema_trend_signal : force de la tendance, normalisee par la volatilite.
- ou_meanreversion_signal : force du retour a la moyenne, estimee par
  regression AR(1) (equivalent discret d'un processus d'Ornstein-Uhlenbeck).
- ewma_volatility : volatilite pour le sizing (etape 4), pas un signal
  directionnel.

Toutes les fonctions travaillent sur des pandas.Series indexees par date
(sortie de data.py) et renvoient des pandas.Series de meme index (NaN sur
la periode de warm-up qui n'a pas assez d'historique).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def hurst_exponent(log_prices: np.ndarray, min_lag: int = 2, max_lag: int = 20) -> float:
    """Exposant de Hurst par la methode de la variance des increments.

    Pour un mouvement brownien fractionnaire, std(X[t+lag] - X[t]) ~ lag^H.
    On estime H comme la pente de log(std) vs log(lag) sur une plage de lags.
    Retourne NaN si la fenetre est trop courte pour la plage de lags demandee.
    """
    n = len(log_prices)
    if n < max_lag + 5:
        return np.nan

    lags = np.arange(min_lag, max_lag)
    tau = np.array([np.std(log_prices[lag:] - log_prices[:-lag]) for lag in lags])

    valid = tau > 0
    if valid.sum() < 2:
        return np.nan

    slope, _intercept = np.polyfit(np.log(lags[valid]), np.log(tau[valid]), 1)
    return float(slope)


def rolling_hurst(close: pd.Series, window: int = 100, min_lag: int = 2, max_lag: int = 20) -> pd.Series:
    """Exposant de Hurst glissant, calcule sur le log-prix."""
    log_close = np.log(close.values)
    out = np.full(len(close), np.nan)
    for i in range(window, len(close) + 1):
        out[i - 1] = hurst_exponent(log_close[i - window : i], min_lag=min_lag, max_lag=max_lag)
    return pd.Series(out, index=close.index, name="hurst")


def ema_trend_signal(close: pd.Series, fast: int = 12, slow: int = 48, vol_window: int = 48) -> pd.Series:
    """Signal de tendance : ecart EMA rapide/lente, normalise par la volatilite.

    Positif = tendance haussiere, negatif = tendance baissiere. L'amplitude
    est comparable entre actifs car normalisee par l'ecart-type glissant du
    prix (evite qu'un actif plus volatil domine artificiellement le score
    composite a l'etape 3).
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    rolling_vol = close.rolling(vol_window).std()

    signal = (ema_fast - ema_slow) / rolling_vol.replace(0, np.nan)
    return signal.rename("ema_trend")


def _ar1_regression(x_prev: np.ndarray, x_curr: np.ndarray) -> tuple:
    """Regression OLS X_t = a + b*X_{t-1} + eps. Renvoie (a, b, residual_std, se_b).

    se_b est l'erreur-type de b (formule OLS standard), utilisee ensuite pour
    juger si b est *statistiquement* < 1, plutot que de se fier a l'estimation
    ponctuelle (bruitee sur petit echantillon).
    """
    b, a = np.polyfit(x_prev, x_curr, 1)
    residuals = x_curr - (a + b * x_prev)
    n = len(residuals)
    if n <= 2:
        return a, b, np.nan, np.nan

    residual_std = np.std(residuals, ddof=2)
    ss_x = np.sum((x_prev - np.mean(x_prev)) ** 2)
    se_b = residual_std / np.sqrt(ss_x) if ss_x > 0 else np.nan
    return a, b, residual_std, se_b


def ou_meanreversion_signal(
    close: pd.Series,
    window: int = 100,
    dt: float = 1.0,
    significance_t: float = 2.0,
) -> pd.DataFrame:
    """Signal de retour a la moyenne base sur un processus d'Ornstein-Uhlenbeck.

    Estime (theta, mu, sigma) par regression AR(1) sur une fenetre glissante
    du log-prix, puis calcule :

        signal = (mu - X_t) / sigma_equilibre        avec sigma_eq = sigma / sqrt(2*theta)

    Filtre de significativite : sur une fenetre courte, l'estimation OLS de b
    trouve b < 1 par pur bruit d'echantillonnage meme sur une marche aleatoire
    pure (biais bien documente, apparente a celui du test de Dickey-Fuller).
    On exige donc que b soit *significativement* < 1 :

        t_stat = (1 - b) / se_b  >  significance_t

    Ce n'est pas un vrai test de Dickey-Fuller (dont les valeurs critiques ne
    sont pas celles d'une loi normale standard), juste un seuil heuristique
    pragmatique pour rejeter le bruit d'estimation. Si le seuil n'est pas
    atteint, le signal est laisse a NaN plutot que d'inventer une reversion
    qui n'est pas etablie.

    Renvoie un DataFrame avec les colonnes: theta, mu, signal.
    """
    log_close = np.log(close.values)
    n = len(close)

    theta_arr = np.full(n, np.nan)
    mu_arr = np.full(n, np.nan)
    signal_arr = np.full(n, np.nan)

    for i in range(window, n + 1):
        segment = log_close[i - window : i]
        x_prev, x_curr = segment[:-1], segment[1:]

        a, b, residual_std, se_b = _ar1_regression(x_prev, x_curr)
        if not np.isfinite(residual_std) or not np.isfinite(se_b) or se_b == 0:
            continue

        t_stat = (1 - b) / se_b
        if t_stat < significance_t:
            continue

        theta = (1 - b) / dt
        mu = a / (1 - b)
        sigma = residual_std / np.sqrt(dt)
        sigma_eq = sigma / np.sqrt(2 * theta)

        idx = i - 1
        theta_arr[idx] = theta
        mu_arr[idx] = mu
        if sigma_eq > 0:
            signal_arr[idx] = (mu - log_close[idx]) / sigma_eq

    return pd.DataFrame(
        {"theta": theta_arr, "mu": mu_arr, "signal": signal_arr},
        index=close.index,
    )


def ewma_volatility(close: pd.Series, lam: float = 0.94) -> pd.Series:
    """Volatilite EWMA (RiskMetrics) des rendements log, pour le sizing.

    sigma_t^2 = lam * sigma_{t-1}^2 + (1-lam) * r_t^2
    """
    log_returns = np.log(close / close.shift(1))
    ewma_var = log_returns.pow(2).ewm(alpha=(1 - lam), adjust=False).mean()
    return np.sqrt(ewma_var).rename("ewma_vol")
