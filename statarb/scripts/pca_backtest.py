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


def _positions_from_s_scores(s_scores, entry_s=ENTRY_S, exit_s=EXIT_S, stop_s=STOP_S):
    """Position {-1,0,+1} par action avec hysteresis (entree a `entry_s`, sortie a
    `exit_s`) : +1 = long le residu (achete si s <= -entry_s, sous-evalue), -1 = short
    (vendu si s >= +entry_s, sur-evalue). Sortie forcee si |s| >= stop_s (divergence,
    la relation factorielle semble rompue) ou si le signal disparait (demi-vie devenue
    trop longue) pendant qu'une position est ouverte : on ne reste jamais expose sans
    signal valide pour justifier la position."""
    positions = pd.DataFrame(0.0, index=s_scores.index, columns=s_scores.columns)
    current = {ticker: 0 for ticker in s_scores.columns}
    values = s_scores.values
    for i in range(len(s_scores)):
        row = values[i]
        for j, ticker in enumerate(s_scores.columns):
            s = row[j]
            pos = current[ticker]
            if np.isnan(s):
                pos = 0  # signal perdu -> on ferme, jamais de position "orpheline"
            elif pos == 0:
                if s <= -entry_s:
                    pos = 1
                elif s >= entry_s:
                    pos = -1
            else:
                if abs(s) <= exit_s or abs(s) >= stop_s:
                    pos = 0
            current[ticker] = pos
            positions.iloc[i, j] = pos
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


def run_pca_backtest(residuals, s_scores, prices=None, capital_usd=DEFAULT_CAPITAL_USD,
                      target_n_positions=TARGET_N_POSITIONS,
                      entry_s=ENTRY_S, exit_s=EXIT_S, stop_s=STOP_S):
    """Simule le portefeuille d'arbitrage statistique : chaque position active recoit une
    allocation fixe de capital/`target_n_positions` (le poids ne change qu'a l'ouverture ou
    la fermeture d'une position, jamais par simple effet de renormalisation), et le rendement
    du jour est le rendement du residu (deja neutre au marche par construction, cf. section 2.1
    de Guijarro-Ordonez et al. 2024), net des frais de transaction IBKR si `prices` est fourni."""
    positions = _positions_from_s_scores(s_scores, entry_s, exit_s, stop_s)
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
