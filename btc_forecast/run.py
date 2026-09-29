"""Usage :
    python -m btc_forecast.run backtest [--hours 8760] [--n-test 2000] [--fee-bps 5]
    python -m btc_forecast.run predict
"""
import argparse
import json
import logging
import os

from btc_forecast.backtest import evaluate, walk_forward
from btc_forecast.data import fetch_btc_1h
from btc_forecast.model import QUANTILES, ChronosForecaster, prob_up
from btc_forecast.report import build_html

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)


def cmd_backtest(args):
    os.makedirs(OUT_DIR, exist_ok=True)
    df = fetch_btc_1h(hours=args.hours)
    forecaster = ChronosForecaster(args.model)
    preds = walk_forward(df['close'], forecaster, n_test=args.n_test, context_len=args.context_len)
    calib, perf, reliability, curves = evaluate(preds, fee_bps=args.fee_bps)

    preds.to_csv(os.path.join(OUT_DIR, 'predictions.csv'))
    perf.to_csv(os.path.join(OUT_DIR, 'strategies.csv'), index=False)
    with open(os.path.join(OUT_DIR, 'calibration.json'), 'w') as f:
        json.dump(calib, f, indent=2)
    meta = {'model': args.model, 'context_len': args.context_len,
            'start': preds.index[0].strftime('%Y-%m-%d'), 'end': preds.index[-1].strftime('%Y-%m-%d')}
    with open(os.path.join(OUT_DIR, 'report.html'), 'w') as f:
        f.write(build_html(calib, perf, reliability, curves, meta, args.fee_bps))

    log.info('Calibration : ' + json.dumps(calib, indent=2))
    log.info('\n' + perf.to_string(index=False))
    log.info(f'Rapport : {os.path.join(OUT_DIR, "report.html")}')


def cmd_predict(args):
    df = fetch_btc_1h(hours=args.context_len + 24)
    close = df['close'].to_numpy()[-args.context_len:]
    q = ChronosForecaster(args.model).predict_quantiles([close])[0]
    p = prob_up(close[-1], q)
    next_open = df.index[-1] + (df.index[-1] - df.index[-2])
    log.info(f'Derniere bougie cloturee : {df.index[-1]} close={close[-1]:.2f}')
    log.info(f'Bougie {next_open} -> P(hausse) = {p:.1%}')
    log.info('Quantiles : ' + ', '.join(f'q{int(l * 100)}={v:.2f}' for l, v in zip(QUANTILES, q)))


def main():
    parser = argparse.ArgumentParser(description='Prevision direction BTC 1h (Chronos zero-shot)')
    parser.add_argument('command', choices=['backtest', 'predict'])
    parser.add_argument('--model', default='amazon/chronos-bolt-small')
    parser.add_argument('--context-len', type=int, default=512)
    parser.add_argument('--hours', type=int, default=24 * 365, help='historique a telecharger')
    parser.add_argument('--n-test', type=int, default=2000, help='nb de previsions walk-forward')
    parser.add_argument('--fee-bps', type=float, default=5.0, help='frais par cote en bps (5 = 0.05 %%)')
    args = parser.parse_args()
    {'backtest': cmd_backtest, 'predict': cmd_predict}[args.command](args)


if __name__ == '__main__':
    main()
