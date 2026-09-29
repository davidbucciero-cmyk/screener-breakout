"""Usage :
    python -m btc_forecast.run backtest [--engine chronos|enkf] [--hours 8760] [--n-test 2000] [--fee-bps 5]
    python -m btc_forecast.run predict  [--engine chronos|enkf]
    python -m btc_forecast.run trend    [--symbol BTCUSDT] [--target-vol 0.4] [--max-leverage 1] [--fee-bps 10]
    python -m btc_forecast.run portfolio --symbol BTCUSDT,ETHUSDT,SOLUSDT
"""
import argparse
import json
import logging
import os

from btc_forecast.backtest import evaluate, evaluate_volatility, walk_forward
from btc_forecast.data import fetch_btc, fetch_btc_1h
from btc_forecast.enkf import EnKFConfig, enkf_positions, run_enkf
from btc_forecast.model import QUANTILES, ChronosForecaster, prob_up
from btc_forecast.report import build_html, build_portfolio_html, build_trend_html
from btc_forecast.trend import run_portfolio, run_trend

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
log = logging.getLogger(__name__)


def cmd_backtest(args):
    os.makedirs(OUT_DIR, exist_ok=True)
    df = fetch_btc_1h(hours=args.hours)
    vol = None
    if args.engine == 'enkf':
        cfg = EnKFConfig(n_members=args.members, inflation=args.inflation)
        full = run_enkf(df, cfg)
        # Seuil de dispersion = mediane des dispersions passees (pas de look-ahead).
        spread_thr = full['h_spread'].expanding(24).median()
        preds = full.iloc[-args.n_test:]
        extra = {
            'EnKF sizing moyenne/dispersion': enkf_positions(preds),
            'EnKF sizing, flat si dispersion vol > mediane passee': enkf_positions(
                preds, max_h_spread=spread_thr.loc[preds.index]),
        }
        # P(hausse) EnKF = Phi(mu/sigma) reste proche de 50 % : seuils plus fins que pour Chronos.
        calib, perf, reliability, curves = evaluate(preds, fee_bps=args.fee_bps, thresholds=(0.0, 0.005, 0.01, 0.02),
                                                    label='EnKF', extra_positions=extra)
        r = df['close'].pct_change()
        vol = evaluate_volatility(preds, r ** 2)
        meta_model = f'EnKF {cfg.n_members} membres, inflation {cfg.inflation}'
        context = f'calibration glissante {cfg.calib_hours}h'
    else:
        preds = walk_forward(df['close'], ChronosForecaster(args.model), n_test=args.n_test,
                             context_len=args.context_len)
        calib, perf, reliability, curves = evaluate(preds, fee_bps=args.fee_bps)
        meta_model, context = args.model, f'contexte {args.context_len}h'

    preds.to_csv(os.path.join(OUT_DIR, 'predictions.csv'))
    perf.to_csv(os.path.join(OUT_DIR, 'strategies.csv'), index=False)
    with open(os.path.join(OUT_DIR, 'calibration.json'), 'w') as f:
        json.dump(calib, f, indent=2)
    meta = {'model': meta_model, 'context': context,
            'start': preds.index[0].strftime('%Y-%m-%d'), 'end': preds.index[-1].strftime('%Y-%m-%d')}
    with open(os.path.join(OUT_DIR, 'report.html'), 'w') as f:
        f.write(build_html(calib, perf, reliability, curves, meta, args.fee_bps, vol))
    if vol is not None:
        vol.to_csv(os.path.join(OUT_DIR, 'volatility.csv'), index=False)
        log.info('\n' + vol.to_string(index=False))

    log.info('Calibration : ' + json.dumps(calib, indent=2))
    log.info('\n' + perf.to_string(index=False))
    log.info(f'Rapport : {os.path.join(OUT_DIR, "report.html")}')


def cmd_trend(args):
    os.makedirs(OUT_DIR, exist_ok=True)
    df = fetch_btc('1d', bars=args.days, symbol=args.symbol)
    perf, curves, yearly, enkf, vols, _ = run_trend(df, target_vol=args.target_vol, max_leverage=args.max_leverage,
                                                 fee_bps=args.fee_bps, band=args.band)
    vol = evaluate_volatility(enkf, df['close'].pct_change() ** 2, windows=(30, 90), unit='j')
    meta = {'symbol': args.symbol, 'start': curves.index[0].strftime('%Y-%m-%d'), 'end': curves.index[-1].strftime('%Y-%m-%d'),
            'days': len(curves), 'target_vol': args.target_vol, 'max_leverage': args.max_leverage,
            'fee_bps': args.fee_bps, 'band': args.band}
    perf.to_csv(os.path.join(OUT_DIR, 'trend_strategies.csv'), index=False)
    yearly.to_csv(os.path.join(OUT_DIR, 'trend_yearly.csv'))
    vol.to_csv(os.path.join(OUT_DIR, 'trend_volatility.csv'), index=False)
    with open(os.path.join(OUT_DIR, 'trend_report.html'), 'w') as f:
        f.write(build_trend_html(perf, curves, yearly, vol, meta))
    log.info(f'{args.symbol} | Periode : {meta["start"]} -> {meta["end"]} ({meta["days"]} jours)')
    log.info('\n' + perf.to_string(index=False))
    log.info('\n' + vol.to_string(index=False))
    log.info('\n' + yearly.to_string(float_format=lambda v: f'{v:.1%}'))


def cmd_portfolio(args):
    os.makedirs(OUT_DIR, exist_ok=True)
    symbols = [s.strip() for s in args.symbol.split(',') if s.strip()]
    dfs = {s: fetch_btc('1d', bars=args.days, symbol=s) for s in symbols}
    perf, curves, yearly, corr = run_portfolio(dfs, target_vol=args.target_vol, max_leverage=args.max_leverage,
                                               fee_bps=args.fee_bps, band=args.band)
    meta = {'symbols': symbols, 'start': curves.index[0].strftime('%Y-%m-%d'),
            'end': curves.index[-1].strftime('%Y-%m-%d'), 'days': len(curves),
            'target_vol': args.target_vol, 'fee_bps': args.fee_bps}
    perf.to_csv(os.path.join(OUT_DIR, 'portfolio_strategies.csv'), index=False)
    yearly.to_csv(os.path.join(OUT_DIR, 'portfolio_yearly.csv'))
    with open(os.path.join(OUT_DIR, 'portfolio_report.html'), 'w') as f:
        f.write(build_portfolio_html(perf, curves, yearly, corr, meta))
    log.info(f'{"+".join(symbols)} | Periode : {meta["start"]} -> {meta["end"]} ({meta["days"]} jours)')
    log.info('\n' + perf.to_string(index=False))
    for strat, c in corr.items():
        log.info(f'Correlations - {strat}\n' + c.round(2).to_string())
    log.info('\n' + yearly.to_string(float_format=lambda v: f'{v:.1%}'))


def cmd_predict(args):
    if args.engine == 'enkf':
        df = fetch_btc_1h(hours=24 * 60)
        preds = run_enkf(df, EnKFConfig(n_members=args.members, inflation=args.inflation), keep_last=True)
        row = preds.iloc[-1]
        log.info(f'Derniere bougie cloturee : {df.index[-1]} close={row["close"]:.2f}')
        log.info(f'P(hausse) = {row["p_up"]:.1%} | vol prevue = {row["var_forecast"] ** 0.5:.3%} '
                 f'| moyenne/dispersion = {row["signal"]:.2f} | position suggeree = {enkf_positions(preds.iloc[-1:])[0]:+.2f}')
        return
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
    parser.add_argument('command', choices=['backtest', 'predict', 'trend', 'portfolio'])
    parser.add_argument('--engine', choices=['chronos', 'enkf'], default='chronos')
    parser.add_argument('--model', default='amazon/chronos-bolt-small')
    parser.add_argument('--members', type=int, default=100, help='EnKF : taille de l ensemble')
    parser.add_argument('--inflation', type=float, default=1.05, help='EnKF : inflation de covariance')
    parser.add_argument('--context-len', type=int, default=512)
    parser.add_argument('--hours', type=int, default=24 * 365, help='historique a telecharger')
    parser.add_argument('--n-test', type=int, default=2000, help='nb de previsions walk-forward')
    parser.add_argument('--fee-bps', type=float, default=None,
                        help='frais par cote en bps (defaut : 5 en 1h futures, 10 en trend spot)')
    parser.add_argument('--symbol', default='BTCUSDT',
                        help='paire Binance (trend) ou liste separee par des virgules (portfolio)')
    parser.add_argument('--days', type=int, default=4000, help='trend : historique journalier a telecharger')
    parser.add_argument('--target-vol', type=float, default=0.40, help='trend : vol annuelle cible')
    parser.add_argument('--max-leverage', type=float, default=1.0, help='trend : exposition max')
    parser.add_argument('--band', type=float, default=0.10, help='trend : ecart min avant re-balancement')
    args = parser.parse_args()
    if args.fee_bps is None:
        args.fee_bps = 10.0 if args.command in ('trend', 'portfolio') else 5.0
    {'backtest': cmd_backtest, 'predict': cmd_predict, 'trend': cmd_trend, 'portfolio': cmd_portfolio}[args.command](args)


if __name__ == '__main__':
    main()
