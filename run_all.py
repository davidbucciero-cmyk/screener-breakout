import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'screener/scripts'))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)

def main():
    log.info('SCREENER MAT-FANION - LANCEMENT COMPLET')
    log.info('=' * 60)

    log.info('STEP 1 - Univers mid/large cap...')
    import step1_universe
    step1_universe.run()

    log.info('STEP 4 - Fondamentaux (filtre CAGR/ratios, reduit l\'univers)...')
    import step4_fundamentals
    step4_fundamentals.run()

    log.info('STEP 2 - Pattern mat-fanion (sur univers filtre)...')
    import step2_technical
    step2_technical.run()

    log.info('STEP 3 - Insider buying (bonus)...')
    import step3_insiders
    step3_insiders.run()

    log.info('STEP 11 - Institutionnels (bonus)...')
    import step11_institutional
    step11_institutional.run()

    log.info('STEP 6 - Short interest...')
    import step6_shortinterest
    step6_shortinterest.run()

    log.info('STEP 7 - Reddit sentiment...')
    import step7_reddit
    step7_reddit.run()

    log.info('STEP 10 - Congressional trading...')
    import step10_congress
    step10_congress.run()

    log.info('STEP 5 - Scoring final (filtre dur + classement)...')
    import step5_scoring
    step5_scoring.run()

    log.info('STEP 8 - Dashboard HTML...')
    import step8_dashboard
    step8_dashboard.run()

    log.info('=' * 60)
    log.info('PIPELINE COMPLET')

if __name__ == '__main__':
    main()
