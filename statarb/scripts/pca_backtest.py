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

# Stop de securite : si le s-score continue de diverger au lieu de revenir vers 0,
# on force la sortie plutot que d'attendre indefiniment un retour a la moyenne qui
# peut ne jamais survenir (rupture structurelle de la relation factorielle).
STOP_S = 3.5

# Regles complementaires de Caldeira & Moura (2013) : stop-loss en % de perte
# (ils ont teste 3/5/7% ; 7% s'est avere le meilleur compromis, un stop trop
# serre coupe des positions qui auraient fini par revenir) et duree de
# detention maximale (au-dela, la rentabilite in-sample se degrade fortement
# dans leur etude, la position est cloturee qu'elle soit gagnante ou non).
PCT_STOP_LOSS = 0.07
MAX_HOLDING_DAYS = 50

# Nombre maximum de positions simultanees. Sans ce plafond, le nombre de
# positions actives peut largement depasser TARGET_N_POSITIONS (observe :
# ~115 en moyenne pour une cible de 50), ce qui sur-levier le portefeuille et
# gonfle les couts de transaction. Aligne par defaut sur TARGET_N_POSITIONS
# pour que l'exposition brute reste proche de 1x. Quand plus de candidats
# se presentent que de place disponible, priorite aux signaux les plus
# extremes et a la reversion la plus rapide (Caldeira & Moura montrent une
# rentabilite liee a la vitesse de convergence, pas seulement a l'ecart).
MAX_CONCURRENT_POSITIONS = 50

# Frais IBKR (grille "Fixed Pricing", https://www.interactivebrokers.com/en/pricing/commissions-stocks.php) :
# 0.005 $/action, minimum 1 $ par ordre, plafonne a 1% de la valeur notionnelle.
IBKR_RATE_PER_SHARE = 0.005
IBKR_MIN_COMMISSION = 1.0
IBKR_MAX_PCT_NOTIONAL = 0.01
DEFAULT_CAPITAL_USD = 100_000

# Allocation fixe par position (capital / TARGET_N_POSITIONS), plutot qu'une
# renormalisation quotidienne a somme|w|=1 sur le nombre courant de positions
# actives. Avec une renormalisation dynamique, l'ouverture ou la fermeture
# d'UNE SEULE position modifie legerement le poids de TOUTES les autres deja
# en portefeuille, ce qui se traduit par un "retrade" fantome (et la commission
# minimum IBKR) chaque jour sur des positions qui n'ont pourtant pas bouge.
# Avec une taille fixe par slot, le poids d'une position ne change qu'a son
# ouverture ou sa fermeture : le cout de transaction reflete alors le vrai
# trading. L'exposition brute du portefeuille flotte avec le nombre de
# positions actives (plus de levier si plus de signaux sont actifs que prevu).
TARGET_N_POSITIONS = 50


def _positions_from_s_scores(s_scores, residuals, half_lives, entry_s=ENTRY_S, exit_s=EXIT_S,
                              stop_s=STOP_S, pct_stop_loss=PCT_STOP_LOSS,
                              max_holding_days=MAX_HOLDING_DAYS,
                              max_positions=MAX_CONCURRENT_POSITIONS):
    """Position {-1,0,+1} par action avec hysteresis (entree a `entry_s`, sortie a
    `exit_s`) : +1 = long le residu (achete si s <= -entry_s, sous-evalue), -1 = short
    (vendu si s >= +entry_s, sur-evalue). Sortie forcee si |s| >= stop_s (divergence, la
    relation factorielle semble rompue), si le signal disparait (demi-vie devenue trop
    longue), si la perte depuis l'ouverture atteint `pct_stop_loss`, ou apres
    `max_holding_days` jours (Caldeira & Moura, 2013) : on ne reste jamais expose sans
    signal valide, ni au-dela d'une perte ou d'une duree jugee deraisonnable.

    Le nombre de positions ouvertes simultanement est plafonne a `max_positions` ; en cas
    de sur-demande, priorite aux signaux les plus extremes et a la reversion la plus
    rapide (score = |s| / demi-vie)."""
    tickers = s_scores.columns
    positions = pd.DataFrame(0.0, index=s_scores.index, columns=tickers)
    pos = {t: 0 for t in tickers}
    holding_days = {t: 0 for t in tickers}
    pnl_since_entry = {t: 1.0 for t in tickers}

    s_vals = s_scores.values
    hl_vals = half_lives.reindex(columns=tickers).values
    resid_vals = residuals.reindex(columns=tickers).values

    for i in range(len(s_scores)):
        s_row = s_vals[i]
        hl_row = hl_vals[i]
        r_row = resid_vals[i]
        candidates = []
        for j, ticker in enumerate(tickers):
            s = s_row[j]
            p = pos[ticker]
            if p != 0:
                r = r_row[j]
                if not np.isnan(r):
                    pnl_since_entry[ticker] *= (1 + p * r)
                holding_days[ticker] += 1
                exit_signal = np.isnan(s) or abs(s) <= exit_s or abs(s) >= stop_s
                exit_stop_loss = (pnl_since_entry[ticker] - 1) <= -pct_stop_loss
                exit_time = holding_days[ticker] >= max_holding_days
                if exit_signal or exit_stop_loss or exit_time:
                    p = 0
                    holding_days[ticker] = 0
                    pnl_since_entry[ticker] = 1.0
            elif not np.isnan(s):
                if s <= -entry_s:
                    candidates.append((j, ticker, 1, s, hl_row[j]))
                elif s >= entry_s:
                    candidates.append((j, ticker, -1, s, hl_row[j]))
            pos[ticker] = p
            positions.iloc[i, j] = p

        n_open = sum(1 for v in pos.values() if v != 0)
        capacity = max_positions - n_open
        if capacity > 0 and candidates:
            def _priority(c):
                _, _, _, s, hl = c
                hl = hl if (hl and hl > 0 and not np.isnan(hl)) else 1.0
                return abs(s) / hl
            candidates.sort(key=_priority, reverse=True)
            for j, ticker, direction, s, hl in candidates[:capacity]:
                pos[ticker] = direction
                holding_days[ticker] = 1
                pnl_since_entry[ticker] = 1.0
                positions.iloc[i, j] = direction
    return positions


def _transaction_costs(weights, prices, capital_usd):
    """Cout de transaction IBKR (Fixed Pricing) applique a chaque changement de poids,
    exprime en fraction du capital pour etre directement soustrait au rendement journalier."""
    turnover = weights.diff().abs().fillna(weights.abs())
    notional = turnover * capital_usd
    shares = (notional / prices).fillna(0.0)
    commission = (shares * IBKR_RATE_PER_SHARE).clip(lower=0)
    commission = commission.where(shares == 0, np.maximum(commission, IBKR_MIN_COMMISSION))
    commission = np.minimum(commission, notional * IBKR_MAX_PCT_NOTIONAL)
    commission = commission.where(notional > 0, 0.0)
    return commission.sum(axis=1) / capital_usd


def run_pca_backtest(residuals, s_scores, half_lives, prices=None, capital_usd=DEFAULT_CAPITAL_USD,
                      target_n_positions=TARGET_N_POSITIONS,
                      max_positions=MAX_CONCURRENT_POSITIONS,
                      entry_s=ENTRY_S, exit_s=EXIT_S, stop_s=STOP_S,
                      pct_stop_loss=PCT_STOP_LOSS, max_holding_days=MAX_HOLDING_DAYS):
    """Simule le portefeuille d'arbitrage statistique : chaque position active recoit une
    allocation fixe de capital/`target_n_positions` (le poids ne change qu'a l'ouverture ou
    la fermeture d'une position, jamais par simple effet de renormalisation), et le rendement
    du jour est le rendement du residu (deja neutre au marche par construction, cf. section 2.1
    de Guijarro-Ordonez et al. 2024), net des frais de transaction IBKR si `prices` est fourni."""
    positions = _positions_from_s_scores(s_scores, residuals, half_lives, entry_s, exit_s, stop_s,
                                          pct_stop_loss, max_holding_days, max_positions)
    n_active = positions.abs().sum(axis=1)
    weights = positions / target_n_positions

    daily_ret = (weights.shift(1).fillna(0.0) * residuals.fillna(0.0)).sum(axis=1)

    costs = None
    if prices is not None:
        common_cols = weights.columns.intersection(prices.columns)
        costs = _transaction_costs(weights[common_cols], prices[common_cols].reindex(weights.index), capital_usd)
        daily_ret = daily_ret - costs.fillna(0.0)

    daily_ret = daily_ret[n_active.shift(1).fillna(0) > 0]

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
    avg_n_positions = n_active[n_active > 0].mean()
    avg_cost_bps = round(float(costs[costs.index.isin(daily_ret.index)].mean() * 10_000), 2) if costs is not None else None

    metrics = {
        'n_days': len(daily_ret),
        'total_return': round(float(total_return), 4),
        'annualized_return': round(float(ann_return), 4) if pd.notna(ann_return) else None,
        'annualized_vol': round(float(ann_vol), 4),
        'sharpe': round(float(sharpe), 3) if pd.notna(sharpe) else None,
        'max_drawdown': round(float(max_dd), 4),
        'avg_active_positions': round(float(avg_n_positions), 1),
        'avg_daily_cost_bps': avg_cost_bps,
    }
    log.info(f'Backtest PCA stat-arb : sharpe={metrics["sharpe"]} total_return={metrics["total_return"]} '
              f'max_dd={metrics["max_drawdown"]} positions_actives_moy={metrics["avg_active_positions"]} '
              f'cout_moyen={metrics["avg_daily_cost_bps"]}bps/jour')
    return metrics, daily_ret, positions
