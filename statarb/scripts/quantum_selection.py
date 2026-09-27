import logging
import os
import numpy as np
import pandas as pd

from qiskit_optimization import QuadraticProgram
from qiskit_optimization.algorithms import MinimumEigenOptimizer
from qiskit_algorithms import QAOA, NumPyMinimumEigensolver
from qiskit_algorithms.optimizers import COBYLA
from qiskit_algorithms.utils import algorithm_globals
from qiskit_aer.primitives import Sampler

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../logs/quantum_selection.log')
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../data')
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s',
                     handlers=[logging.FileHandler(LOG_PATH), logging.StreamHandler()])
log = logging.getLogger(__name__)
# Qiskit journalise ses passes de transpilation en INFO sur son propre logger : on les
# tait pour ne garder que nos messages (elles ne disent rien d'utile ici).
logging.getLogger('qiskit').setLevel(logging.WARNING)

# La regle actuelle (pca_backtest._priority, score = |s|/demi-vie) choisit les positions
# une par une, sans jamais regarder si deux candidats sont correles entre eux : elle peut
# tres bien remplir tout le budget avec 50 valeurs du meme secteur qui bougent ensemble,
# ce qui annule la diversification recherchee. Le probleme de selection de portefeuille
# sous contrainte de cardinalite (choisir exactement B titres parmi N pour maximiser le
# rendement attendu net d'un terme de risque xSigma x) est un QUBO standard, directement
# soluble par QAOA. Voir Qiskit Finance / Egger et al. (2020), "Quantum Computing for
# Finance: State of the Art and Future Prospects", pour cette formulation.
#
# QAOA sur un simulateur (ou un vrai processeur IBM Quantum) ne passe a l'echelle que
# pour un petit nombre de variables binaires (qubits) -- une vingtaine au plus en
# pratique aujourd'hui. On ne peut donc pas re-optimiser ainsi chaque jour sur des annees
# de backtest (des centaines de candidats, des milliers de jours). Cette fonction est
# pensee pour la decision du jour (`pca_live_signals`) : on reduit d'abord la liste des
# candidats a une short-list raisonnable (par le score heuristique existant), puis QAOA
# choisit, parmi cette short-list, le sous-ensemble le mieux diversifie sous contrainte
# de budget.
MAX_QUBITS = 20


def build_qubo(candidate_returns, covariance, budget, risk_factor=0.5):
    """Construit le programme quadratique Qiskit pour le probleme de selection de
    portefeuille standard (cf. Egger et al. 2020 ; tutoriel Qiskit Finance) :
    maximiser mu.x - risk_factor * x.Sigma.x sous contrainte sum(x) = budget, x binaire.
    `candidate_returns` : array (n,) de rendements/scores attendus (plus grand = mieux).
    `covariance` : array (n,n) de covariance entre les residus des candidats.
    """
    n = len(candidate_returns)
    qp = QuadraticProgram('portfolio_selection')
    for i in range(n):
        qp.binary_var(name=f'x_{i}')
    linear = {f'x_{i}': float(candidate_returns[i]) for i in range(n)}
    quadratic = {
        (f'x_{i}', f'x_{j}'): -risk_factor * float(covariance[i, j])
        for i in range(n) for j in range(n) if covariance[i, j] != 0
    }
    qp.maximize(linear=linear, quadratic=quadratic)
    qp.linear_constraint(linear={f'x_{i}': 1 for i in range(n)}, sense='==', rhs=budget, name='budget')
    return qp


def solve_classical_exact(qp):
    """Solution exacte (diagonalisation classique) -- sert de reference pour verifier QAOA.
    Ne passe a l'echelle que pour un petit nombre de variables (2^n etats)."""
    optimizer = MinimumEigenOptimizer(NumPyMinimumEigensolver())
    return optimizer.solve(qp)


def solve_qaoa(qp, reps=2, maxiter=250, seed=42, sampler=None):
    """Resout le QUBO par QAOA. Par defaut sur le simulateur Sampler de Qiskit (gratuit,
    local) ; passer un Sampler d'IBM Quantum Runtime pour executer sur un vrai processeur."""
    algorithm_globals.random_seed = seed
    qaoa = QAOA(sampler=sampler or Sampler(), optimizer=COBYLA(maxiter=maxiter), reps=reps)
    optimizer = MinimumEigenOptimizer(qaoa)
    return optimizer.solve(qp)


def select_positions(candidates_df, residuals_window, budget, risk_factor=1.0, max_qubits=MAX_QUBITS,
                      use_qaoa=True):
    """Choisit `budget` positions parmi les candidats, en tenant compte de leur correlation.

    `candidates_df` : DataFrame indexe par ticker, colonnes 's_score', 'half_life_days',
    'direction' (+1 = long le residu, -1 = short). `residuals_window` : DataFrame (jours x
    tickers) des rendements de residu recents, utilise pour estimer la covariance -- calculee
    sur le rendement SIGNE de la position (residu x direction), pas sur le residu brut, pour
    refleter comment les positions reelles (et non les series sous-jacentes) co-varient.

    Si plus de `max_qubits` candidats, on reduit d'abord a une short-list des meilleurs par
    score heuristique |s|/demi-vie avant de lancer QAOA -- au-dela d'une vingtaine de
    variables binaires, le probleme n'est plus simulable ni executable sur le materiel NISQ
    actuel dans un temps raisonnable.
    """
    df = candidates_df.copy()
    df['half_life_days'] = df['half_life_days'].replace(0, 1.0)
    df['priority'] = df['s_score'].abs() / df['half_life_days']
    shortlist_df = df.sort_values('priority', ascending=False).head(max_qubits)
    if len(df) > max_qubits:
        log.info(f'{len(df)} candidats -> short-list des {max_qubits} meilleurs avant QAOA')

    tickers = shortlist_df.index.tolist()
    budget = min(budget, len(tickers))
    if budget <= 0 or not tickers:
        return [], None

    directions = shortlist_df['direction'].values
    window = residuals_window[tickers].tail(60)
    signed_returns = window * directions  # rendement de la position, pas du residu brut
    covariance = signed_returns.cov().fillna(0.0).values
    expected_returns = shortlist_df['s_score'].abs().values
    # Le s-score s'interprete comme le Sharpe ex-ante du trade (Meucci, 2010), d'ou son usage
    # direct comme proxy de rendement attendu dans l'objectif.

    qp = build_qubo(expected_returns, covariance, budget, risk_factor)

    result = solve_qaoa(qp) if use_qaoa else solve_classical_exact(qp)
    selected = [tickers[i] for i, v in enumerate(result.x) if v > 0.5]
    log.info(f'{"QAOA" if use_qaoa else "Exact"} a selectionne {len(selected)}/{budget} positions '
              f'parmi {len(tickers)} candidats (objectif={result.fval:.4f})')
    return selected, result


def select_today(alloc_usd=None, budget=50, risk_factor=1.0, max_qubits=MAX_QUBITS, use_qaoa=True):
    """Charge les signaux et residus du dernier run de `run_statarb.py`
    (statarb/data/pca_signals_today.csv, pca_residuals.csv) et applique la selection
    diversifiee par QAOA aux candidats actionnables du jour."""
    signals_path = os.path.join(DATA_DIR, 'pca_signals_today.csv')
    residuals_path = os.path.join(DATA_DIR, 'pca_residuals.csv')
    signals = pd.read_csv(signals_path)
    residuals = pd.read_csv(residuals_path, index_col=0, parse_dates=True)

    actionable = signals[signals['action'].isin(['ENTER_LONG_RESIDUAL', 'ENTER_SHORT_RESIDUAL'])].copy()
    actionable['direction'] = np.where(actionable['action'] == 'ENTER_LONG_RESIDUAL', 1, -1)
    candidates_df = actionable.set_index('ticker')[['s_score', 'half_life_days', 'direction']]

    if candidates_df.empty:
        log.warning('Aucun candidat actionnable dans pca_signals_today.csv')
        return [], None

    return select_positions(candidates_df, residuals, budget, risk_factor, max_qubits, use_qaoa)
