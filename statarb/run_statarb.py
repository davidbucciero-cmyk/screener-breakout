import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

FORMATION_RATIO = 0.6   # part de l'historique utilisee pour selectionner les paires / estimer le hedge ratio
MAX_PAIRS = 10
ALLOC_PER_PAIR_USD = 20_000


def main():
    import universe
    import cointegration
    import backtest
    import signals

    log.info('=' * 60)
    log.info('STAT-ARB - PAIRS TRADING PAR COINTEGRATION')
    log.info('=' * 60)

    log.info('STEP 1 - Prix historiques...')
    prices = universe.fetch_prices()
    if prices.empty:
        log.error('Pas de donnees, arret.')
        return
    universe.save_prices(prices)

    split_idx = int(len(prices) * FORMATION_RATIO)
    formation = prices.iloc[:split_idx]
    trading = prices.iloc[split_idx:]
    log.info(f'Formation : {formation.index.min().date()} -> {formation.index.max().date()} '
              f'({len(formation)}j) | Trading (out-of-sample) : {trading.index.min().date()} -> '
              f'{trading.index.max().date()} ({len(trading)}j)')

    log.info('STEP 2 - Recherche de paires cointegrees (periode de formation)...')
    pairs_df = cointegration.find_cointegrated_pairs(formation)
    if pairs_df.empty:
        log.warning('Aucune paire cointegree trouvee sur cette fenetre.')
        return
    pairs_path = os.path.join(os.path.dirname(__file__), 'data', 'cointegrated_pairs.csv')
    pairs_df.to_csv(pairs_path, index=False)
    log.info(f'{len(pairs_df)} paires retenues -> {pairs_path}')
    log.info('\n' + pairs_df.head(MAX_PAIRS).to_string(index=False))

    log.info('STEP 3 - Backtest out-of-sample (periode de trading)...')
    metrics_df, portfolio_ret = backtest.run_portfolio_backtest(trading, pairs_df, max_pairs=MAX_PAIRS)
    metrics_path = os.path.join(os.path.dirname(__file__), 'data', 'backtest_results.csv')
    metrics_df.to_csv(metrics_path, index=False)
    if not portfolio_ret.empty:
        equity_path = os.path.join(os.path.dirname(__file__), 'data', 'portfolio_equity.csv')
        (1 + portfolio_ret).cumprod().to_csv(equity_path, header=['equity'])
        log.info(f'Resultats backtest -> {metrics_path} | equity -> {equity_path}')

    log.info('STEP 4 - Signaux du jour (dernier prix disponible)...')
    signals_df = signals.run(prices, pairs_df, alloc_usd=ALLOC_PER_PAIR_USD, max_pairs=MAX_PAIRS)
    if not signals_df.empty:
        log.info('\n' + signals_df.to_string(index=False))

    log.info('=' * 60)
    log.info('TERMINE. Rappel : les signaux ne sont PAS des ordres. Toute execution live via '
              'IBKR passe par une instruction en attente (create_order_instruction), a valider '
              'manuellement dans la plateforme IBKR avant envoi.')


if __name__ == '__main__':
    main()
