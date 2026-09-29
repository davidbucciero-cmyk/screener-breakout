"""Assimilation de donnees par ensemble (EnKF), la methode des centres meteo, appliquee a BTC 1h.

Etat latent par membre : mu (drift horaire) et h (log-variance horaire).
Observations a chaque bougie cloturee :
  - r_t     : rendement close-to-close        -> observe mu, bruit de variance exp(h)
  - lpk_t   : log de la variance de Parkinson  -> observe h (+ biais), bruit calibre sur 30 j
Chaque membre a ses propres parametres de dynamique (ensemble a parametres perturbes).
Sortie : distribution du rendement t+1 (melange des membres), dont P(hausse) et la dispersion.
"""
import logging
import math

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

_erf = np.vectorize(math.erf)
PARKINSON_K = 4 * math.log(2)
EPS = 1e-12


def _norm_cdf(x):
    return 0.5 * (1 + _erf(x / math.sqrt(2)))


class EnKFConfig:
    def __init__(self, n_members=100, inflation=1.05, calib_hours=720,
                 phi_h=(0.90, 0.99), h_std=0.6, phi_mu=(0.0, 0.8), mu_std_ratio=0.05, seed=42):
        self.n_members = n_members
        self.inflation = inflation          # inflation multiplicative des anomalies (anti-effondrement)
        self.calib_hours = calib_hours      # fenetre de calibration glissante (30 j)
        self.phi_h = phi_h                  # persistance de la log-variance, tiree par membre
        self.h_std = h_std                  # ecart-type stationnaire de h autour de son niveau 30 j
        self.phi_mu = phi_mu                # persistance du drift, tiree par membre
        self.mu_std_ratio = mu_std_ratio    # ecart-type stationnaire du drift, en fraction de la vol
        self.seed = seed


def _observations(df):
    close, high, low = df['close'].to_numpy(), df['high'].to_numpy(), df['low'].to_numpy()
    r = np.empty(len(close))
    r[0] = 0.0
    r[1:] = close[1:] / close[:-1] - 1
    pk = np.log(high / low) ** 2 / PARKINSON_K
    return r, np.log(np.maximum(pk, EPS))


def run_enkf(df, cfg=None, keep_last=False):
    """Filtre sequentiel sur tout l'historique. Ligne t = prevision de la bougie t -> t+1,
    calculee avec les seules bougies <= t. Les calib_hours premieres lignes (warm-up) sont retirees.
    keep_last : garde la derniere bougie (cible inconnue, pour la prevision live)."""
    cfg = cfg or EnKFConfig()
    rng = np.random.default_rng(cfg.seed)
    n, N = len(df), cfg.n_members
    r, lpk = _observations(df)

    # Calibration glissante sur 30 j (passe uniquement) : niveau de variance, biais et bruit de lpk.
    w = cfg.calib_hours
    r2_roll = pd.Series(r ** 2).rolling(w).mean().to_numpy()
    lpk_roll = pd.Series(lpk).rolling(w).mean().to_numpy()
    dlpk_var = pd.Series(np.diff(lpk, prepend=lpk[0])).rolling(w).var().to_numpy()

    phi_h = rng.uniform(*cfg.phi_h, N)
    phi_mu = rng.uniform(*cfg.phi_mu, N)
    sig_h = cfg.h_std * np.sqrt(1 - phi_h ** 2)
    # Etat initial (premiere heure calibree) : h autour du niveau 30 j, mu autour de 0.
    t0 = w
    h = np.log(r2_roll[t0]) + rng.normal(0, cfg.h_std, N)
    mu = rng.normal(0, cfg.mu_std_ratio * math.sqrt(r2_roll[t0]), N)

    cols = ['p_up', 'mu_mean', 'mu_spread', 'signal', 'var_forecast', 'h_spread']
    out = np.full((n, len(cols)), np.nan)
    for t in range(t0, n):
        h_bar = math.log(max(r2_roll[t - 1], EPS))  # niveau 30 j connu avant la bougie t
        bias = lpk_roll[t - 1] - h_bar  # lpk ~ h + biais (Jensen + ecart Parkinson/close-to-close)
        R_lpk = max(0.5 * dlpk_var[t - 1], 1e-4)

        # --- Analyse : correction de chaque membre par les observations de la bougie t ---
        X = np.vstack([mu, h])
        Xm = X.mean(axis=1, keepdims=True)
        X = Xm + cfg.inflation * (X - Xm)
        HX = np.vstack([X[0], X[1] + bias])
        R = np.diag([max(np.exp(X[1]).mean(), EPS), R_lpk])
        A = X - X.mean(axis=1, keepdims=True)
        HA = HX - HX.mean(axis=1, keepdims=True)
        P_xy = A @ HA.T / (N - 1)
        P_yy = HA @ HA.T / (N - 1) + R
        K = P_xy @ np.linalg.inv(P_yy)
        y = np.array([[r[t]], [lpk[t]]])
        y_pert = y + rng.multivariate_normal([0, 0], R, N).T  # EnKF stochastique (obs perturbees)
        X = X + K @ (y_pert - HX)
        mu, h = X[0], X[1]

        # --- Prevision t+1 : propagation de chaque membre par sa propre dynamique ---
        mu_std = cfg.mu_std_ratio * math.exp(h_bar / 2)
        mu = phi_mu * mu + mu_std * np.sqrt(1 - phi_mu ** 2) * rng.normal(size=N)
        h = h_bar + phi_h * (h - h_bar) + sig_h * rng.normal(size=N)

        vol = np.exp(h / 2)
        p_up = _norm_cdf(mu / vol).mean()
        mu_mean, mu_spread = mu.mean(), mu.std(ddof=1)
        var_fc = (np.exp(h) + mu ** 2).mean() - mu_mean ** 2
        out[t] = [p_up, mu_mean, mu_spread, mu_mean / mu_spread if mu_spread > 0 else 0.0, var_fc, h.std(ddof=1)]

    res = pd.DataFrame(out, index=df.index, columns=cols)
    res['close'] = df['close'].to_numpy()
    res['next_close'] = df['close'].shift(-1).to_numpy()
    res['ret'] = res['next_close'] / res['close'] - 1
    res['prev_ret'] = r
    res = res.dropna(subset=['p_up'])
    return res if keep_last else res.iloc[:-1]


def enkf_positions(preds, signal_scale=2.0, max_h_spread=None):
    """Sizing proportionnel au ratio moyenne/dispersion de l'ensemble, borne a [-1, 1].
    Si la dispersion de la vol (h_spread) depasse max_h_spread : pas de position (prevision peu fiable)."""
    pos = np.clip(preds['signal'] / signal_scale, -1, 1)
    if max_h_spread is not None:
        pos = pos.where(preds['h_spread'] <= max_h_spread, 0.0)
    return pos.to_numpy()
