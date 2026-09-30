"""Socle de signaux statistiques (etape 2).

Quatre briques independantes, chacune capture une information differente :

- hurst_exponent / rolling_hurst : classificateur de regime (tendanciel vs
  retour a la moyenne), sert a arbitrer entre les deux signaux directionnels
  a l'etape 3.
- ema_trend_signal : force de la tendance, normalisee par la volatilite.
- ou_meanreversion_signal : force du retour a la moyenne, estimee par
  regression AR(1) (equivalent discret d'un processus d'Ornstein-Uhlenbeck).
  Expose aussi la demi-vie de retour a la moyenne (half_life) ;
  estimate_dominant_half_life/suggest_meanreversion_window s'en servent pour
  calibrer la fenetre d'estimation elle-meme (cf. Chan, "Algorithmic
  Trading", chap. 2) plutot que de la laisser uniquement a un grid search.
- ewma_volatility : volatilite pour le sizing (etape 4), pas un signal
  directionnel.

Toutes les fonctions travaillent sur des pandas.Series indexees par date
(sortie de data.py) et renvoient des pandas.Series de meme index (NaN sur
la periode de warm-up qui n'a pas assez d'historique).
"""
from __future__ import annotations

import warnings
from typing import Optional

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


def ema_trend_signal(
    close: pd.Series, fast: int = 12, slow: int = 48, vol_window: int = 48, skip: int = 0
) -> pd.Series:
    """Signal de tendance : ecart EMA rapide/lente, normalise par la volatilite.

    Positif = tendance haussiere, negatif = tendance baissiere. L'amplitude
    est comparable entre actifs car normalisee par l'ecart-type glissant du
    prix (evite qu'un actif plus volatil domine artificiellement le score
    composite a l'etape 3).

    skip : nombre de bougies les plus recentes exclues du calcul des EMA,
    analogue au "12-1 mois" du momentum academique (Jegadeesh-Titman 1993)
    qui exclut le mois le plus recent de la periode de formation pour
    eviter la contamination par le retournement a tres court terme (dont
    ou_meanreversion_signal s'occupe deja separement). Concretement, les
    EMA sont calculees sur close.shift(skip) : le signal a l'instant t
    reflete alors la tendance telle qu'elle etait a t-skip, pas celle des
    `skip` dernieres bougies. La normalisation par la volatilite reste sur
    la volatilite courante (le sizing doit reagir au risque present).
    """
    base = close.shift(skip) if skip > 0 else close
    ema_fast = base.ewm(span=fast, adjust=False).mean()
    ema_slow = base.ewm(span=slow, adjust=False).mean()
    rolling_vol = close.rolling(vol_window).std()

    signal = (ema_fast - ema_slow) / rolling_vol.replace(0, np.nan)
    return signal.rename("ema_trend")


def baz_response(z: pd.Series) -> pd.Series:
    """Fonction de reponse bornee de Baz et al. (2015), utilisee en production
    chez Man AHL et reprise par Rohrbach, Suremann & Osterrieder (2017) pour
    des signaux de tendance FX/crypto :

        u(z) = z * exp(-z^2/4) / (sqrt(2) * exp(-1/2))

    Le denominateur est choisi pour que u atteigne exactement +-1 en
    z = +-sqrt(2) (maximum/minimum global de la fonction - derivee nulle en
    z^2=2), pas une simple borne asymptotique.

    Important : ce n'est PAS une fonction de saturation classique (type
    sigmoide, qui plafonnerait a +-1 pour |z| grand). u(z) -> 0 quand
    |z| -> infini : un z-score tres extreme produit un signal PLUS FAIBLE
    qu'un z-score modere autour de sqrt(2). C'est intentionnel (Baz et al.,
    2015) - un z-score extreme vient souvent d'un denominateur de
    normalisation (vol) anormalement bas plutot que d'une tendance
    genuinement plus forte, donc la fonction reduit la confiance accordee
    aux lectures extremes au lieu de les amplifier lineairement.

    A appliquer sur un signal deja normalise (ex: ema_trend_signal, dont la
    normalisation par ewma_vol produit deja un z-score approximatif) plutot
    que sur un prix brut.
    """
    return z * np.exp(-z.pow(2) / 4) / (np.sqrt(2) * np.exp(-0.5))


def multi_horizon_trend_signal(
    close: pd.Series,
    horizons: tuple = ((8, 24), (16, 48), (32, 96)),
    price_vol_window: int = 63,
    signal_vol_window: int = 252,
    use_bounded_response: bool = False,
    skip: int = 0,
) -> pd.Series:
    """Signal de tendance multi-horizon (Baz et al., 2015 ; Rohrbach, Suremann
    & Osterrieder, 2017), combinaison de plusieurs croisements d'EMA plutot
    qu'un seul (`ema_trend_signal`).

    Pour chaque paire (fast, slow) de `horizons` :

        x_k = EMA(close, fast) - EMA(close, slow)
        y_k = x_k / sdmoving(price_vol_window)(close)          (1ere normalisation : par la vol du PRIX)
        z_k = y_k / sdmoving(signal_vol_window)(y_k)           (2eme normalisation : par la vol du SIGNAL lui-meme)
        u_k = baz_response(z_k) si use_bounded_response, sinon z_k

    Le signal final est la moyenne simple des u_k (poids egaux, comme dans
    les deux papiers - "on peut optimiser les poids par horizon, mais le
    risque de surapprentissage doit etre considere").

    Par defaut, les 3 paires (8,24)/(16,48)/(32,96) donnent une correlation
    croisee d'environ 85% entre horizons consecutifs (assez differents pour
    apporter de l'information distincte, pas au point d'etre redondants -
    cf. Rohrbach et al., section 4.3).

    Double normalisation DIFFERENTE du reste du pipeline (ema_trend_signal
    ne normalise qu'une fois, par une fenetre liee a chaque horizon) :
    ici la 1ere normalisation utilise une fenetre FIXE (63 jours, ~3 mois)
    identique pour tous les horizons, et la 2eme normalise chaque y_k par
    SA PROPRE volatilite glissante (1 an) - c'est la methode exacte des
    papiers de reference, gardee telle quelle plutot que reutilisee/adaptee
    a partir de ema_trend_signal pour rester fidele a la source.

    skip : meme semantique que ema_trend_signal.skip (EMA calculees sur
    close.shift(skip)), la normalisation par la vol reste sur la serie
    courante (le risque actuel, pas celui d'il y a `skip` bougies).

    Les `skip` + le plus long warm-up (EMA la plus lente + les deux fenetres
    de normalisation en cascade) produisent un NaN prolonge en debut de
    serie - attendu, pas un bug.
    """
    base = close.shift(skip) if skip > 0 else close
    price_vol = close.rolling(price_vol_window).std().replace(0, np.nan)

    u_signals = []
    for fast, slow in horizons:
        ema_fast = base.ewm(span=fast, adjust=False).mean()
        ema_slow = base.ewm(span=slow, adjust=False).mean()
        x_k = ema_fast - ema_slow
        y_k = x_k / price_vol
        z_k = y_k / y_k.rolling(signal_vol_window).std().replace(0, np.nan)
        u_k = baz_response(z_k) if use_bounded_response else z_k
        u_signals.append(u_k)

    combined = sum(u_signals) / len(u_signals)
    return combined.rename("ema_trend_multi")


def _ar1_regression(x_prev: np.ndarray, x_curr: np.ndarray) -> tuple:
    """Regression OLS X_t = a + b*X_{t-1} + eps. Renvoie (a, b, residual_std, se_b).

    se_b est l'erreur-type de b (formule OLS standard), utilisee ensuite pour
    juger si b est *statistiquement* < 1, plutot que de se fier a l'estimation
    ponctuelle (bruitee sur petit echantillon).

    Renvoie des NaN si x_prev est (quasi) constant (ex: prix plat sur toute
    la fenetre) : la regression n'a alors aucune information exploitable, et
    np.polyfit deviendrait numeriquement mal conditionne (RankWarning).
    """
    n = len(x_prev)
    if n <= 2 or np.std(x_prev) == 0:
        return np.nan, np.nan, np.nan, np.nan

    with warnings.catch_warnings():
        # Un segment quasi-lineaire/quasi-constant peut mal conditionner
        # numeriquement le polyfit (RankWarning) sans que le resultat soit
        # incorrect ; le filtre ci-dessous evite le bruit dans les logs sans
        # masquer d'autres avertissements potentiellement utiles.
        warnings.filterwarnings("ignore", category=np.exceptions.RankWarning)
        b, a = np.polyfit(x_prev, x_curr, 1)
    residuals = x_curr - (a + b * x_prev)

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

    La colonne half_life (-log(2)/theta, cf. Chan, "Algorithmic Trading",
    chap. 2) est le temps caracteristique de retour a la moyenne : utile
    pour calibrer la fenetre d'estimation elle-meme (voir
    estimate_dominant_half_life/suggest_meanreversion_window ci-dessous)
    plutot que de la chercher uniquement par grid search.

    Renvoie un DataFrame avec les colonnes: theta, mu, signal, half_life.
    """
    log_close = np.log(close.values)
    n = len(close)

    theta_arr = np.full(n, np.nan)
    mu_arr = np.full(n, np.nan)
    signal_arr = np.full(n, np.nan)
    half_life_arr = np.full(n, np.nan)

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
        if theta > 0:
            half_life_arr[idx] = np.log(2) / theta
        if sigma_eq > 0:
            signal_arr[idx] = (mu - log_close[idx]) / sigma_eq

    return pd.DataFrame(
        {"theta": theta_arr, "mu": mu_arr, "signal": signal_arr, "half_life": half_life_arr},
        index=close.index,
    )


def estimate_dominant_half_life(
    close: pd.Series,
    window: int = 100,
    dt: float = 1.0,
    significance_t: float = 2.0,
) -> float:
    """Estimation robuste (mediane) de la demi-vie de retour a la moyenne
    sur toute la serie fournie (typiquement un segment TRAIN), a partir de
    la meme regression AR(1) glissante que ou_meanreversion_signal.

    Sert a calibrer une fenetre d'estimation (voir
    suggest_meanreversion_window) plutot qu'a produire un signal de trading -
    d'ou la mediane (robuste aux quelques fenetres bruitees) plutot que la
    derniere valeur seule. Renvoie NaN si aucune fenetre glissante n'a
    detecte de retour a la moyenne significatif (voir significance_t).
    """
    half_lives = ou_meanreversion_signal(close, window=window, dt=dt, significance_t=significance_t)["half_life"]
    valid = half_lives.dropna()
    if valid.empty:
        return float("nan")
    return float(valid.median())


def suggest_meanreversion_window(
    close: pd.Series,
    window: int = 100,
    dt: float = 1.0,
    significance_t: float = 2.0,
    multiplier: float = 3.0,
    min_window: int = 20,
    max_window: int = 300,
) -> Optional[int]:
    """Suggere une fenetre d'estimation (ou_window) a partir de la demi-vie
    de retour a la moyenne dominante, plutot que de la laisser uniquement a
    un grid search aveugle (cf. Chan, "Algorithmic Trading", chap. 2 : "setting
    the look-back to equal a small multiple of the half-life is close to
    optimal" - moins de parametres libres optimises en force brute, donc
    moins de risque de data-snooping, cf. chap. 1 du meme livre).

    A appeler UNE FOIS sur un segment TRAIN pour calibrer BacktestConfig.ou_window
    avant un run/fold - pas concu pour varier bougie par bougie en cours de
    backtest (fenetre glissante de taille fixe partout ailleurs dans le
    pipeline, cf. _align_universe).

    Renvoie None si aucune demi-vie exploitable n'a ete trouvee (serie pas
    mean-revertante sur cette fenetre) - a l'appelant de garder une valeur
    par defaut dans ce cas plutot que d'en inventer une.
    """
    half_life = estimate_dominant_half_life(close, window=window, dt=dt, significance_t=significance_t)
    if not np.isfinite(half_life) or half_life <= 0:
        return None
    suggested = round(half_life * multiplier)
    return int(min(max_window, max(min_window, suggested)))


def ewma_volatility(close: pd.Series, lam: float = 0.94) -> pd.Series:
    """Volatilite EWMA (RiskMetrics) des rendements log, pour le sizing.

    sigma_t^2 = lam * sigma_{t-1}^2 + (1-lam) * r_t^2
    """
    log_returns = np.log(close / close.shift(1))
    ewma_var = log_returns.pow(2).ewm(alpha=(1 - lam), adjust=False).mean()
    return np.sqrt(ewma_var).rename("ewma_vol")
