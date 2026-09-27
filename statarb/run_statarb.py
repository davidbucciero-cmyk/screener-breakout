import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

# Arbitrage statistique par facteurs PCA + processus Ornstein-Uhlenbeck sur les residus
# idiosyncratiques (Avellaneda & Lee 2010 ; Velissaris 2010). Remplace l'approche
# "pairs trading" par cointegration (conservee dans run_pairs_legacy.py) : la litterature
# montre que trader la cross-section complete des residus d'un modele factoriel bat
# nettement le fait de chercher des paires isolees (voir README pour les references).
#
# Les residus sont calcules hors-echantillon jour par jour (PCA glissante 252j +
# regression glissante 60j), donc toute la periode produite est deja "out-of-sample" :
# pas de decoupage formation/trading supplementaire necessaire ici.

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


def main():
    import universe
    import pca_factors
    import ou_signal
    import pca_backtest
    import pca_live_signals

    log.info('=' * 60)
    log.info('STAT-ARB - FACTEURS PCA + OU SUR RESIDUS (Avellaneda-Lee / Velissaris)')
    log.info('=' * 60)

    log.info('STEP 1 - Prix historiques...')
    prices = universe.fetch_prices()
    if prices.empty:
        log.error('Pas de donnees, arret.')
        return
    universe.save_prices(prices)
    returns = prices.pct_change().dropna(how='all')

    log.info('STEP 2 - Residus hors-echantillon (PCA glissante + regression sur facteurs)...')
    residuals = pca_factors.compute_daily_residuals(returns)
    if residuals.notna().sum().sum() == 0:
        log.error('Aucun residu calcule (historique trop court pour PCA_WINDOW+LOADING_WINDOW).')
        return
    residuals.to_csv(os.path.join(DATA_DIR, 'pca_residuals.csv'))

    log.info('STEP 3 - S-scores (OU AR(1) sur residu cumule, filtre demi-vie < 30j)...')
    s_scores, half_lives = ou_signal.compute_s_scores(residuals)
    s_scores.to_csv(os.path.join(DATA_DIR, 'pca_s_scores.csv'))

    log.info('STEP 4 - Backtest portefeuille (dollar-neutre, poids egaux sur positions actives, frais IBKR)...')
    metrics, daily_ret, positions = pca_backtest.run_pca_backtest(residuals, s_scores, half_lives, prices=prices)
    if metrics:
        import json
        with open(os.path.join(DATA_DIR, 'pca_backtest_results.json'), 'w') as f:
            json.dump(metrics, f, indent=2)
        (1 + daily_ret).cumprod().to_csv(os.path.join(DATA_DIR, 'pca_portfolio_equity.csv'), header=['equity'])
        log.info(f'Metriques : {metrics}')

    log.info('STEP 5 - Signaux du jour (dernier prix disponible)...')
    signals_df = pca_live_signals.run(s_scores, half_lives)
    if not signals_df.empty:
        log.info('\n' + signals_df.to_string(index=False))

    log.info('=' * 60)
    log.info('TERMINE. Rappel : les signaux ne sont PAS des ordres. Toute execution live via '
              'IBKR passe par une instruction en attente (create_order_instruction), a valider '
              'manuellement dans la plateforme IBKR avant envoi.')


if __name__ == '__main__':
    main()
