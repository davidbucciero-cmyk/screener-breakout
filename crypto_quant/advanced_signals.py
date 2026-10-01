"""Blocs quant avances (etape 21) : chaque fonction est un bloc INDEPENDANT,
testable isolement, adapte specifiquement a un contexte mono-actif (or) en
bougies journalieres plutot qu'une replication litterale de la version
academique (qui suppose souvent plusieurs actifs, de la vente a decouvert,
ou des donnees intrabougie qu'on n'a pas).

Quatre blocs (GARCH, cointegration, HMM, regression ML) partagent une meme
limite assumee et documentee individuellement : leurs parametres sont
ajustes sur TOUT l'echantillon passe en argument (MLE/EM/OLS plein-
echantillon), pas en fenetre glissante reentrainee a chaque fold - sauf le
bloc ML qui, lui, respecte la discipline train/test stricte du reste du
projet (rien ne justifiait de l'en exempter).

Adaptations deliberees de concepts qui ne s'appliquent pas tels quels a un
bot or mono-actif, long-only, en bougies journalieres :
- momentum cross-sectionnel academique (long gagnants/short perdants) ->
  cross_sectional_momentum_tilt, LONG-ONLY (tilt de poids, pas de vente a
  decouvert - infra absente de ce projet).
- VWAP intrajournalier (qui se reinitialise chaque jour sur des donnees
  tick) -> daily_vwap_approx, une moyenne mobile ponderee par le volume
  sur plusieurs jours - PAS le meme objet, limite documentee dans la
  fonction.
- option digitale / divergence KL-JS / agregation bayesienne (utilisees
  pour Polymarket dans cette session) -> appliquees ici a de VRAIES
  options sur l'or (chaine GLD) et a nos propres blocs de signaux entre
  eux, pas a des marches de prediction.
- paires de negation (deux marches Polymarket complementaires) ->
  cash_and_carry_consistency, l'equivalent gold reel : coherence
  sans-arbitrage entre futures front-month, futures suivant et ETF (GLD).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

from .signals import _require_positive_prices


# ---------------------------------------------------------------------------
# Volatilite et regime
# ---------------------------------------------------------------------------


def garch_volatility(close: pd.Series, p: int = 1, q: int = 1, dist: str = "normal") -> pd.Series:
    """Volatilite conditionnelle GARCH(p,q) (Bollerslev, 1986) sur les
    rendements log quotidiens - reagit plus vite aux chocs recents que
    ewma_volatility (lambda fixe a priori), au prix de parametres estimes
    sur les donnees plutot que fixes.

    LIMITE ASSUMEE (fuite d'information) : alpha/beta/omega sont estimes en
    maximum de vraisemblance sur TOUT l'echantillon passe en argument, pas
    en fenetre glissante reentrainee - la volatilite du jour 100 beneficie
    donc indirectement de donnees futures (jour 5000) via les parametres
    ajustes sur l'ensemble. Utilisable tel quel pour une estimation LIVE
    (reestimation reguliere sur l'historique disponible a ce jour-la), pas
    dans un backtest walk-forward sans reentrainement par fold.
    """
    from arch import arch_model

    _require_positive_prices(close, "garch_volatility")
    returns = np.log(close).diff().dropna() * 100.0  # echelle recommandee par arch pour la stabilite numerique
    if len(returns) < 100:
        raise ValueError(f"garch_volatility necessite au moins 100 rendements, {len(returns)} fournis")

    model = arch_model(returns, mean="Zero", vol="Garch", p=p, q=q, dist=dist)
    result = model.fit(disp="off")
    cond_vol = result.conditional_volatility / 100.0
    cond_vol.index = returns.index
    return cond_vol.reindex(close.index).rename("garch_vol")


def hmm_regime_signal(close: pd.Series, n_states: int = 2, n_iter: int = 100, random_state: int = 42) -> pd.Series:
    """Probabilite d'etre dans l'etat de plus haute volatilite, estimee par
    un modele de Markov cache gaussien a n_states sur les rendements log
    quotidiens - alternative statistique a Hurst/ADX pour moduler le signal
    de tendance selon le regime de marche detecte.

    LIMITE ASSUMEE (fuite d'information) : meme piege que garch_volatility -
    le modele (Baum-Welch/EM) est ajuste sur TOUT l'echantillon d'un coup,
    pas en fenetre glissante. Utilisable en live (reestimation reguliere),
    pas dans un backtest walk-forward sans reentrainement par fold.
    """
    from hmmlearn.hmm import GaussianHMM

    _require_positive_prices(close, "hmm_regime_signal")
    returns = np.log(close).diff().dropna()
    if len(returns) < 10 * n_states:
        raise ValueError(f"hmm_regime_signal necessite au moins {10 * n_states} rendements, {len(returns)} fournis")

    model = GaussianHMM(n_components=n_states, covariance_type="diag", n_iter=n_iter, random_state=random_state)
    model.fit(returns.values.reshape(-1, 1))
    posteriors = model.predict_proba(returns.values.reshape(-1, 1))

    high_vol_state = int(np.argmax(model.covars_.reshape(n_states, -1)[:, 0]))
    prob_high_vol = pd.Series(posteriors[:, high_vol_state], index=returns.index, name="hmm_high_vol_prob")
    return prob_high_vol.reindex(close.index)


# ---------------------------------------------------------------------------
# Structure de marche : courbe des futures, cross-actifs, macro
# ---------------------------------------------------------------------------


def carry_signal(front_price: pd.Series, next_price: pd.Series, days_to_next_expiry: float) -> pd.Series:
    """Signal de portage (carry) : ecart annualise entre le contrat
    front-month et le contrat suivant sur la courbe des futures de l'or.

        carry = -ln(next/front) / (days_to_next_expiry / 365)

    Positif en situation de BACKWARDATION (le contrat proche est plus cher
    que le suivant) - la pente de la courbe des futures contient une
    information independante du signal de momentum (prix contre son propre
    passe).

    days_to_next_expiry est un ecart FIXE approximatif entre les deux
    echeances (pas recalcule jour par jour a partir des dates de contrat
    reelles) - simplification assumee, suffisante pour un signal
    directionnel, pas pour une replication exacte du rendement de roll.
    """
    common_index = front_price.index.intersection(next_price.index)
    front = front_price.reindex(common_index)
    next_ = next_price.reindex(common_index)
    carry = -np.log(next_ / front) / (days_to_next_expiry / 365.0)
    return carry.rename("carry")


def cointegration_spread_signal(
    asset_a: pd.Series, asset_b: pd.Series, window: int = 100, significance_t: float = 2.0
) -> pd.DataFrame:
    """Signal de retour a la moyenne sur le spread de cointegration entre
    deux actifs lies (ex: or/argent) - meme logique que
    ou_meanreversion_signal (signals.py), mais appliquee a l'ECART entre
    deux series plutot qu'a une seule.

    Regresse log(asset_a) sur log(asset_b) en fenetre glissante (hedge
    ratio beta par OLS), calcule le residu (spread) et son z-score glissant
    (ecart-type des residus DANS la meme fenetre). Filtre de
    significativite : le signal n'est emis que si |z-score| > significance_t
    - memes raisons que pour OU, eviter d'inventer une reversion qui n'est
    pas etablie sur une fenetre bruitee.

    Renvoie beta, spread, zscore, signal (= -zscore la ou |zscore| depasse
    le seuil, NaN sinon - NaN traite comme "aucune contribution" partout
    ailleurs dans ce projet, meme convention ici).
    """
    _require_positive_prices(asset_a, "cointegration_spread_signal (asset_a)")
    _require_positive_prices(asset_b, "cointegration_spread_signal (asset_b)")

    common_index = asset_a.index.intersection(asset_b.index).sort_values()
    log_a = np.log(asset_a.reindex(common_index).values)
    log_b = np.log(asset_b.reindex(common_index).values)
    n = len(common_index)

    beta_arr = np.full(n, np.nan)
    spread_arr = np.full(n, np.nan)
    zscore_arr = np.full(n, np.nan)

    for i in range(window, n + 1):
        x = log_b[i - window : i]
        y = log_a[i - window : i]
        design = np.column_stack([np.ones(window), x])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        intercept, beta = coef
        residuals = y - (intercept + beta * x)
        beta_arr[i - 1] = beta
        spread_arr[i - 1] = residuals[-1]
        resid_std = residuals.std()
        zscore_arr[i - 1] = residuals[-1] / resid_std if resid_std > 0 else np.nan

    signal_arr = np.where(np.abs(zscore_arr) > significance_t, -zscore_arr, np.nan)

    return pd.DataFrame(
        {"beta": beta_arr, "spread": spread_arr, "zscore": zscore_arr, "signal": signal_arr},
        index=common_index,
    )


def cross_sectional_momentum_tilt(returns_by_asset: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """Tilt de force relative LONG-ONLY entre plusieurs actifs correles
    (ex: or/argent/cuivre) : classe les actifs par rendement cumule sur
    `lookback` jours, renvoie un poids proportionnel au RANG (toujours
    positif ou nul) - PAS une replication du momentum cross-sectionnel
    academique classique (Jegadeesh & Titman, 1993, qui va long les
    gagnants ET a decouvert les perdants) : ce projet n'a pas d'infra de
    vente a decouvert, l'adaptation se contente de SOUS-ponderer le moins
    performant plutot que de parier contre lui.
    """
    cum_returns = (1 + returns_by_asset).rolling(lookback).apply(lambda x: x.prod() - 1, raw=True)
    ranks = cum_returns.rank(axis=1, ascending=True, na_option="keep")
    weights = ranks.div(ranks.sum(axis=1), axis=0)
    return weights


def days_to_futures_month_end(index: pd.DatetimeIndex) -> pd.Series:
    """Jours restants jusqu'a la fin du mois calendaire courant - PROXY de
    l'echeance du contrat front-month (le COMEX negocie des contrats
    mensuels sur l'or, expirant generalement en fin de mois de livraison).

    APPROXIMATION ASSUMEE : pas la vraie date d'expiration du contrat
    precis actif a chaque instant (non disponible via nos sources sur
    l'historique - seul le contrat COURANT, ex. GCZ26.CMX, est interrogeable,
    cf. etape 21/21bis) - mais un cycle correct EN MOYENNE (0 a ~30 jours,
    jamais un horizon fixe arbitraire comme le 60 jours utilise avant ce
    correctif), suffisant pour une estimation de cout de portage.
    """
    idx = pd.DatetimeIndex(index)
    month_end = idx + pd.offsets.MonthEnd(0)
    days = (month_end - idx).days.to_series(index=idx).clip(lower=1)
    return days.rename("days_to_month_end")


def cash_and_carry_consistency(
    front_price: pd.Series,
    etf_price: pd.Series,
    risk_free_rate,
    days_to_next_expiry=None,
    normalization_window: int = 250,
) -> pd.DataFrame:
    """Verifie la coherence sans-arbitrage entre le contrat futures
    front-month et l'ETF physique (GLD) - l'equivalent gold reel du
    controle "paires de negation" explore sur Polymarket (deux instruments
    qui DEVRAIENT etre lies par une relation stricte plutot que deux
    marches complementaires).

    Theorie du cout de portage (cash-and-carry) :
        futures_theorique = spot_proxy * exp(taux_sans_risque * T)
    Un ecart important et persistant entre le futures observe et ce
    theorique signale soit un cout de portage implicite different de
    l'hypothese (ex: lease rate de l'or non nul - NON modelise ici, cf.
    limite ci-dessous), soit une vraie inefficience exploitable.

    risk_free_rate : float OU pd.Series. Doit etre un taux COURT TERME
    (ex: bon du Tresor 3 mois, ^IRX) coherent avec l'horizon du contrat -
    un taux 10 ans (ex: ^TNX) introduirait un biais systematique via les
    variations de la pente de la courbe des taux, sans rapport avec une
    vraie incoherence sur l'or (corrige a l'etape 21 ter : ^TNX -> ^IRX).

    days_to_next_expiry : float OU pd.Series OU None. None (par defaut)
    utilise days_to_futures_month_end(front_price.index) - une echeance
    DYNAMIQUE (0 a ~30 jours selon la date), plutot qu'une constante
    arbitraire (60 jours fixes utilises avant ce correctif, etape 21 ter).

    LIMITE NON CORRIGEE : le lease rate de l'or (taux de pret/emprunt
    physique, generalement different et plus bas que le taux sans risque
    nominal) n'est pas disponible depuis la fin de la publication du GOFO
    (2015) - cette fonction suppose implicitement un lease rate nul, une
    approximation, pas la vraie theorie du cout de portage sur l'or.

    BUG CORRIGE (etape 21 bis) : GLD ne represente PAS 1 once d'or (ratio
    observe ~10.5x, GLD cote en $/part, GC=F en $/once) - utiliser un
    niveau absolu comme reference rendait `deviation` dominee par cet
    ecart d'UNITE, pas par une vraie incoherence de marche. Fixe en
    normalisant le RATIO front/spot_proxy contre sa PROPRE moyenne/
    ecart-type glissants (z-score) plutot qu'un niveau absolu.
    """
    common_index = front_price.index.intersection(etf_price.index)
    front = front_price.reindex(common_index)
    spot_proxy = etf_price.reindex(common_index)

    if days_to_next_expiry is None:
        days_to_next_expiry = days_to_futures_month_end(common_index)
        if not isinstance(days_to_next_expiry, pd.Series):
            days_to_next_expiry = pd.Series(days_to_next_expiry, index=common_index)
    elif isinstance(days_to_next_expiry, pd.Series):
        days_to_next_expiry = days_to_next_expiry.reindex(common_index)
    if isinstance(risk_free_rate, pd.Series):
        risk_free_rate = risk_free_rate.reindex(common_index)

    T = days_to_next_expiry / 365.0
    theoretical_ratio = np.exp(risk_free_rate * T)  # ecart theorique MULTIPLICATIF attendu (cout de portage), independant de l'unite
    observed_ratio = front / spot_proxy
    normalized_ratio = observed_ratio / theoretical_ratio  # isole le cout de portage, retire le facteur d'unite GLD/once constant

    rolling_mean = normalized_ratio.rolling(normalization_window, min_periods=30).mean()
    rolling_std = normalized_ratio.rolling(normalization_window, min_periods=30).std()
    deviation = (normalized_ratio - rolling_mean) / rolling_std

    return pd.DataFrame(
        {"spot_proxy": spot_proxy, "front": front, "normalized_ratio": normalized_ratio, "deviation": deviation}
    )


def macro_factor_exposure(
    gold_returns: pd.Series,
    dxy_returns: pd.Series,
    real_yield_returns: pd.Series,
    vix_level: pd.Series,
    window: int = 250,
) -> pd.DataFrame:
    """Modele a facteurs macro pour l'or : regresse les rendements de l'or
    sur trois facteurs macro reconnus dans la litterature, en fenetre
    glissante, pour en extraire les sensibilites (betas) et un residu.

    Facteurs :
    - dxy_returns : rendement de l'indice dollar (DXY) - l'or est
      historiquement anti-correle au dollar.
    - real_yield_returns : variation des taux reels (proxy via un ETF type
      TIP, ou taux nominal moins anticipations d'inflation) - le cout
      d'opportunite de detenir un actif sans rendement comme l'or augmente
      avec les taux reels.
    - vix_level (NIVEAU, pas rendement) : facteur "risk-off" - l'or est
      parfois une valeur refuge en periode de stress de marche.

    Renvoie beta_dxy, beta_real_yield, beta_vix, residual (fenetre
    glissante `window`, NaN en warm-up). Le residu persistant est un
    signal en soi : la part du rendement de l'or que ces facteurs
    n'expliquent pas.
    """
    df = pd.DataFrame(
        {"gold": gold_returns, "dxy": dxy_returns, "real_yield": real_yield_returns, "vix": vix_level}
    ).dropna()
    n = len(df)
    betas = np.full((n, 3), np.nan)
    residual = np.full(n, np.nan)

    for i in range(window, n + 1):
        y = df["gold"].values[i - window : i]
        design = np.column_stack(
            [
                np.ones(window),
                df["dxy"].values[i - window : i],
                df["real_yield"].values[i - window : i],
                df["vix"].values[i - window : i],
            ]
        )
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        betas[i - 1] = coef[1:]
        residual[i - 1] = y[-1] - design[-1] @ coef

    return pd.DataFrame(
        {
            "beta_dxy": betas[:, 0],
            "beta_real_yield": betas[:, 1],
            "beta_vix": betas[:, 2],
            "residual": residual,
        },
        index=df.index,
    )


# ---------------------------------------------------------------------------
# Options, divergence entre sources, agregation
# ---------------------------------------------------------------------------


def implied_probability_from_options(
    calls: pd.DataFrame, spot: float, days_to_expiry: float, risk_free_rate: float = 0.0
) -> pd.DataFrame:
    """Probabilite implicite (risque-neutre) que l'or termine au-dessus de
    chaque strike a l'echeance, extraite d'une VRAIE chaine d'options sur
    l'or (GLD) - meme principe que l'option digitale utilisee pour
    Polymarket cette session (P(S_T>=K) via N(d2), Black & Scholes 1973),
    applique ici a un vrai marche d'options plutot qu'a un marche de
    prediction.

    calls : DataFrame au format yfinance `Ticker.option_chain().calls`
    (colonnes 'strike' et 'impliedVolatility' requises) - une ligne de
    sortie par strike dont l'IV est exploitable (>0).
    """
    T = days_to_expiry / 365.0
    if T <= 0:
        raise ValueError("days_to_expiry doit etre strictement positif")

    rows = []
    for _, row in calls.iterrows():
        strike = float(row["strike"])
        sigma = float(row["impliedVolatility"])
        if sigma <= 0 or strike <= 0:
            continue
        d2 = (np.log(spot / strike) + (risk_free_rate - 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        prob_above_strike = 0.5 * (1.0 + math.erf(d2 / np.sqrt(2)))
        rows.append({"strike": strike, "implied_vol": sigma, "prob_above_strike": prob_above_strike})

    return pd.DataFrame(rows).sort_values("strike").reset_index(drop=True)


def kl_divergence(p: np.ndarray, q: np.ndarray, eps: float = 1e-10) -> float:
    """Divergence de Kullback-Leibler D_KL(P||Q), en nats. p et q doivent
    etre des distributions de probabilite (memes bins).

    Lissage additif (eps) plutot que masquage des bacs ou p ou q est nul :
    masquer un bac avec p>0 et q=0 (deux distributions disjointes sur ce
    bac) EFFACERAIT precisement la contribution la plus informative - deux
    distributions completement separees masqueraient TOUS leurs bacs
    non-communs et ressortiraient a tort avec une divergence quasi nulle.
    Le lissage garde cette contribution (grande mais finie) au lieu de la
    faire disparaitre.
    """
    p = np.asarray(p, dtype=float) + eps
    q = np.asarray(q, dtype=float) + eps
    p, q = p / p.sum(), q / q.sum()
    return float(np.sum(p * np.log(p / q)))


def js_divergence(p: np.ndarray, q: np.ndarray) -> float:
    """Divergence de Jensen-Shannon : symetrique (contrairement a KL) et
    bornee dans [0, ln(2)] - cf. PolySwarm, section V.A."""
    p, q = np.asarray(p, dtype=float), np.asarray(q, dtype=float)
    m = 0.5 * (p + q)
    return float(0.5 * kl_divergence(p, m) + 0.5 * kl_divergence(q, m))


def signal_distribution_divergence(signal_a: pd.Series, signal_b: pd.Series, bins: int = 20) -> dict:
    """Divergence KL/JS entre les distributions empiriques de DEUX
    signaux/blocs de ce module (ex: la probabilite implicite des options
    vs celle derivee de garch_volatility+hmm_regime_signal) - mesure a
    quel point deux sources d'information sur l'or "voient" des choses
    differentes. Un ecart large et persistant peut signaler une
    inefficience a creuser - meme usage que PolySwarm en fait entre
    marches lies (section V.B), applique ici entre nos propres blocs.
    """
    common = pd.DataFrame({"a": signal_a, "b": signal_b}).dropna()
    if len(common) < bins * 5:
        raise ValueError(
            f"signal_distribution_divergence necessite au moins {bins * 5} observations communes, {len(common)} fournies"
        )

    lo = min(common["a"].min(), common["b"].min())
    hi = max(common["a"].max(), common["b"].max())
    edges = np.linspace(lo, hi, bins + 1)

    hist_a, _ = np.histogram(common["a"], bins=edges)
    hist_b, _ = np.histogram(common["b"], bins=edges)
    p = hist_a / hist_a.sum()
    q = hist_b / hist_b.sum()

    return {"kl_divergence": kl_divergence(p, q), "js_divergence": js_divergence(p, q), "n_observations": len(common)}


def bayesian_aggregate_probabilities(probabilities: pd.DataFrame, weights: Optional[pd.Series] = None) -> pd.Series:
    """Combine plusieurs estimations de probabilite (une colonne par bloc,
    ex: options-implied, HMM-based) en une seule, par moyenne ponderee en
    LOG-ODDS (pas en probabilite brute) - convention standard d'agregation
    bayesienne d'opinions independantes (chaque source apporte une preuve
    multiplicative, pas additive ; cf. PolySwarm, agregation bayesienne de
    l'essaim, Eq. 1-2).

    weights : poids de fiabilite par colonne (defaut : poids egaux). Les
    probabilites sont bornees a ]1e-6, 1-1e-6[ - une probabilite exactement
    0 ou 1 produirait un logit infini qui ecraserait les autres sources.
    """
    clipped = probabilities.clip(lower=1e-6, upper=1 - 1e-6)
    logits = np.log(clipped / (1 - clipped))

    if weights is None:
        weights = pd.Series(1.0, index=probabilities.columns)
    weights = weights.reindex(probabilities.columns).fillna(0.0)

    combined_logit = (logits * weights).sum(axis=1) / weights.sum()
    combined_prob = 1 / (1 + np.exp(-combined_logit))
    return combined_prob.rename("bayesian_aggregate_prob")


# ---------------------------------------------------------------------------
# Volume, portefeuille, apprentissage supervise
# ---------------------------------------------------------------------------


def daily_vwap_approx(df: pd.DataFrame, window: int = 20) -> pd.Series:
    """VWAP APPROXIME sur bougies journalieres : moyenne mobile du prix
    typique (H+L+C)/3 ponderee par le volume, sur `window` jours.

    LIMITE ASSUMEE ET IMPORTANTE : ce n'est PAS le VWAP intrajournalier
    classique (qui s'accumule et se reinitialise CHAQUE jour a partir de
    donnees tick/intrabougie) - avec une seule bougie par jour, cette
    notion n'existe pas telle quelle. Ceci est une moyenne mobile ponderee
    par le volume sur PLUSIEURS jours, un filtre de tendance de plus dans
    le meme esprit qu'EMA - pas le signal de reference des day traders.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical_price * df["volume"]
    vwap = pv.rolling(window).sum() / df["volume"].rolling(window).sum()
    return vwap.rename("vwap_approx")


def risk_parity_weights(cov_matrix: pd.DataFrame, max_iter: int = 200, tol: float = 1e-8) -> pd.Series:
    """Poids de parite des risques (equal risk contribution, Maillard et
    al. 2010 / Spinu 2013) : chaque actif contribue A PARTS EGALES au
    risque TOTAL du portefeuille (tient compte des correlations),
    contrairement a inverse_vol_weights (risk.py) qui les ignore.
    Algorithme iteratif standard, pas de solution fermee au-dela de 2
    actifs.

    Sur l'or SEUL (1 actif), ce bloc n'a aucun effet differenciant
    (poids=100% par construction) - utile uniquement combine avec d'autres
    metaux/actifs correles (ex: argent, cuivre).
    """
    n = len(cov_matrix)
    w = np.full(n, 1.0 / n)
    cov = cov_matrix.values

    for _ in range(max_iter):
        portfolio_var = w @ cov @ w
        marginal_contrib = cov @ w
        risk_contrib = w * marginal_contrib  # contribution au risque de l'actif i (PAS la contribution marginale seule)
        target = portfolio_var / n
        # Mise a jour multiplicative en racine carree (pas w*target/risk_contrib,
        # qui simplifie algebriquement le w_i courant et converge a tort vers
        # des contributions MARGINALES egales plutot que des contributions au
        # RISQUE egales - verifie par calcul direct sur un cas 2 actifs non
        # correles, cf. test_risk_parity_weights_equalizes_risk_contribution).
        w_new = w * np.sqrt(target / risk_contrib)
        w_new = w_new / w_new.sum()
        if np.max(np.abs(w_new - w)) < tol:
            w = w_new
            break
        w = w_new

    return pd.Series(w, index=cov_matrix.index, name="risk_parity_weight")


def min_variance_weights(cov_matrix: pd.DataFrame) -> pd.Series:
    """Poids de variance minimale (portefeuille le moins volatil possible
    pour la matrice de covariance donnee), sous contrainte somme=1,
    LONG-ONLY (poids negatifs ramenes a 0 puis renormalises - solution
    approximative, pas une vraie optimisation quadratique sous contrainte ;
    suffisant pour un bloc exploratoire, pas pour une implementation de
    production).
    """
    inv_cov = np.linalg.pinv(cov_matrix.values)
    ones = np.ones(len(cov_matrix))
    raw = inv_cov @ ones
    raw = np.clip(raw, 0, None)
    if raw.sum() == 0:
        raw = np.full(len(cov_matrix), 1.0 / len(cov_matrix))
    else:
        raw = raw / raw.sum()
    return pd.Series(raw, index=cov_matrix.index, name="min_variance_weight")


def ml_regularized_signal(
    features: pd.DataFrame, target: pd.Series, train_frac: float = 0.6, alpha: float = 1.0
) -> pd.Series:
    """Signal par regression logistique regularisee (Ridge/L2) sur un jeu
    de features (ex: les sorties des autres blocs de ce module - hurst,
    adx, garch_vol...), pour predire le SENS du rendement a l'horizon
    choisi par l'appelant.

    MEME DISCIPLINE QUE LE RESTE DU PROJET : parametres ajustes
    UNIQUEMENT sur les `train_frac` premiers pourcents de l'historique,
    jamais sur le test - contrairement a garch_volatility/
    hmm_regime_signal (ajustes plein-echantillon par nature de leur
    estimation MLE/EM), un modele supervise comme celui-ci n'a AUCUNE
    excuse a fuir cette discipline, vu que c'est exactement le risque de
    surapprentissage mis en evidence partout ailleurs dans ce projet.

    target : rendement futur BINARISE (1 si positif, 0 sinon), DEJA
    DECALE par l'appelant (pas de shift fait ici, pour que la
    responsabilite d'empecher le look-ahead soit sans ambiguite).

    Renvoie une Series de probabilites predites [0,1], NaN sur la portion
    d'entrainement (pas de prediction in-sample trompeuse).
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    common = features.join(target.rename("target"), how="inner").dropna()
    n = len(common)
    split = int(n * train_frac)
    if split < 20 or n - split < 20:
        raise ValueError("ml_regularized_signal necessite au moins 20 observations de chaque cote du split train/test")

    X = common.drop(columns="target")
    y = common["target"]

    scaler = StandardScaler().fit(X.iloc[:split])
    X_train_scaled = scaler.transform(X.iloc[:split])
    X_test_scaled = scaler.transform(X.iloc[split:])

    model = LogisticRegression(C=1.0 / alpha, max_iter=1000)
    model.fit(X_train_scaled, y.iloc[:split])

    predicted_prob = model.predict_proba(X_test_scaled)[:, 1]
    result = pd.Series(np.nan, index=common.index)
    result.iloc[split:] = predicted_prob
    return result.rename("ml_signal")
