import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

# Selection diversifiee (QAOA) des positions parmi les candidats actionnables du jour,
# a lancer APRES statarb/run_statarb.py (qui produit pca_signals_today.csv et
# pca_residuals.csv). Remplace la regle gloutonne |s|/demi-vie de pca_backtest.py, qui
# ignore la correlation entre candidats, par une optimisation combinatoire QUBO qui en
# tient compte -- resolue par QAOA (defaut : simulateur local Qiskit Aer, gratuit).
#
# Ne s'applique qu'a la decision du jour, pas au backtest historique : QAOA ne passe pas
# a l'echelle sur des milliers de jours x des centaines de candidats (voir le
# commentaire dans scripts/quantum_selection.py). BUDGET doit rester strictement
# inferieur a MAX_QUBITS : sinon il n'y a qu'une seule solution possible (tout garder) et
# QAOA n'a plus de veritable choix a faire -- ici on demontre le cas utile, choisir les 10
# positions les mieux diversifiees parmi les 20 candidats les plus prioritaires.

BUDGET = 10
RISK_FACTOR = 1.0
MAX_QUBITS = 20


def main():
    import quantum_selection as qs

    log.info('=' * 60)
    log.info('SELECTION DIVERSIFIEE (QAOA) DES POSITIONS DU JOUR')
    log.info('=' * 60)

    sel_qaoa, res_qaoa = qs.select_today(budget=BUDGET, risk_factor=RISK_FACTOR,
                                          max_qubits=MAX_QUBITS, use_qaoa=True)
    if res_qaoa is None:
        log.warning('Rien a selectionner (voir pca_signals_today.csv).')
        return

    sel_exact, res_exact = qs.select_today(budget=BUDGET, risk_factor=RISK_FACTOR,
                                            max_qubits=MAX_QUBITS, use_qaoa=False)

    overlap = len(set(sel_qaoa) & set(sel_exact))
    gap_pct = (res_exact.fval - res_qaoa.fval) / abs(res_exact.fval) * 100 if res_exact.fval else 0.0

    log.info(f'QAOA  : {sel_qaoa}')
    log.info(f'EXACT : {sel_exact} (reference classique, sert a jauger la qualite de QAOA)')
    log.info(f'Recouvrement QAOA/EXACT : {overlap}/{len(sel_exact)} '
              f'(ecart a l\'optimum : {gap_pct:.1f}%)')
    log.info('=' * 60)
    log.info('Rappel : ceci est une selection, pas des ordres. Execution live via IBKR '
              'toujours par instruction en attente, a valider manuellement.')


if __name__ == '__main__':
    main()
