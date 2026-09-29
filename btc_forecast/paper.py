"""Compte demo (paper trading) de la strategie trend + ciblage de vol 30 j, sur prix reels.

Chaque jour apres la cloture journaliere (00:00 UTC) :
  1. telecharge les bougies journalieres cloturees de chaque crypto ;
  2. calcule l'exposition cible (meme code que le backtest) ;
  3. re-balance si l'ecart depasse la bande, au prix de cloture, frais deduits ;
  4. enregistre l'etat (state.json), les ordres (trades.csv) et la valeur (equity.csv) ;
  5. envoie un email recapitulatif.
Idempotent : une journee deja traitee n'est pas re-executee.
"""
import argparse
import csv
import json
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from btc_forecast.data import fetch_btc
from btc_forecast.trend import DAYS_PER_YEAR, trend_signals, vol_target

log = logging.getLogger(__name__)

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'paper_trading')
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
INITIAL_CAPITAL = 10_000.0
FEE_BPS = 10.0
TARGET_VOL = 0.40
MAX_LEVERAGE = 1.0
BAND = 0.10

EMAIL_FROM = 'david.bucciero.ide@gmail.com'
EMAIL_TO = 'david.bucciero@outlook.fr'


def target_exposure(df):
    """Exposition cible pour demain, connue a la cloture de la derniere bougie."""
    close = df['close']
    ensemble = trend_signals(close)['ensemble'].iloc[-1]
    vol = close.pct_change().rolling(30).std().iloc[-1] * DAYS_PER_YEAR ** 0.5
    return float(vol_target(ensemble, vol, TARGET_VOL, MAX_LEVERAGE)), float(ensemble), float(vol)


def _load_state():
    path = os.path.join(DIR, 'state.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def _init_state(prices, date):
    sleeve = INITIAL_CAPITAL / len(SYMBOLS)
    return {
        'start_date': date,
        'last_date': None,
        'sleeves': {s: {'cash': sleeve, 'qty': 0.0} for s in SYMBOLS},
        # Benchmark : buy & hold equipondere, achete au premier jour.
        'benchmark_qty': {s: sleeve * (1 - FEE_BPS / 1e4) / prices[s] for s in SYMBOLS},
    }


def _append_csv(name, row):
    path = os.path.join(DIR, name)
    new = not os.path.exists(path)
    with open(path, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def step():
    os.makedirs(DIR, exist_ok=True)
    data = {s: fetch_btc('1d', bars=400, symbol=s) for s in SYMBOLS}
    date = min(df.index[-1] for df in data.values()).strftime('%Y-%m-%d')
    prices = {s: float(df['close'].iloc[-1]) for s, df in data.items()}

    state = _load_state() or _init_state(prices, date)
    if state['last_date'] == date:
        log.info(f'Journee {date} deja traitee, rien a faire.')
        return None

    lines = []
    for s, df in data.items():
        sl = state['sleeves'][s]
        price = prices[s]
        value = sl['cash'] + sl['qty'] * price
        current = sl['qty'] * price / value if value > 0 else 0.0
        target, ensemble, vol = target_exposure(df)
        traded = 0.0
        if (target == 0.0 and sl['qty'] > 0) or abs(target - current) > BAND:
            delta_qty = (target * value) / price - sl['qty']
            notional = abs(delta_qty) * price
            fee = notional * FEE_BPS / 1e4
            sl['qty'] += delta_qty
            sl['cash'] -= delta_qty * price + fee
            traded = delta_qty * price
            _append_csv('trades.csv', {'date': date, 'symbol': s, 'side': 'BUY' if delta_qty > 0 else 'SELL',
                                       'qty': round(abs(delta_qty), 8), 'price': price,
                                       'notional': round(notional, 2), 'fee': round(fee, 4),
                                       'exposure_before': round(current, 4), 'exposure_after': round(target, 4)})
        value = sl['cash'] + sl['qty'] * price
        lines.append({'symbol': s, 'price': price, 'signal': ensemble, 'vol': vol, 'target': target,
                      'exposure': sl['qty'] * price / value if value > 0 else 0.0,
                      'traded': traded, 'value': value})

    total = sum(l['value'] for l in lines)
    bench = sum(state['benchmark_qty'][s] * prices[s] for s in SYMBOLS)
    row = {'date': date, 'total': round(total, 2), 'buy_and_hold': round(bench, 2)}
    row.update({f'{l["symbol"]}_value': round(l['value'], 2) for l in lines})
    row.update({f'{l["symbol"]}_exposure': round(l['exposure'], 4) for l in lines})
    _append_csv('equity.csv', row)

    state['last_date'] = date
    with open(os.path.join(DIR, 'state.json'), 'w') as f:
        json.dump(state, f, indent=2)
    log.info(f'{date} | total {total:,.2f} USDT | buy & hold {bench:,.2f}')
    for l in lines:
        log.info(f'  {l["symbol"]}: signal {l["signal"]:.2f}, vol {l["vol"]:.0%}, exposition {l["exposure"]:.0%}, '
                 f'ordre {l["traded"]:+,.2f} USDT, valeur {l["value"]:,.2f}')
    return date, state['start_date'], total, bench, lines


def send_email(date, start, total, bench, lines):
    password = os.environ.get('EMAIL_PASSWORD', '')
    if not password:
        log.warning('EMAIL_PASSWORD non defini - email ignore')
        return
    perf = total / INITIAL_CAPITAL - 1
    perf_b = bench / INITIAL_CAPITAL - 1
    def order(traded):
        if not traded:
            return '&mdash;'
        return f'{"Achat" if traded > 0 else "Vente"} {abs(traded):,.0f} USDT'

    rows = ''.join(
        f'<tr><td><b>{l["symbol"].replace("USDT", "")}</b></td><td>{l["price"]:,.2f}</td>'
        f'<td>{l["signal"]:.0%}</td><td>{l["vol"]:.0%}</td><td><b>{l["exposure"]:.0%}</b></td>'
        f'<td>{order(l["traded"])}</td><td>{l["value"]:,.2f}</td></tr>' for l in lines)
    html = f'''<html><body style="font-family:sans-serif">
<h2>Compte demo trend crypto &mdash; {date}</h2>
<p>Valeur : <b>{total:,.2f} USDT</b> ({perf:+.2%} depuis le {start})<br>
Buy &amp; hold equipondere : {bench:,.2f} USDT ({perf_b:+.2%})</p>
<table border="1" cellpadding="5" style="border-collapse:collapse">
<tr><th>Crypto</th><th>Prix</th><th>Signal tendance</th><th>Vol 30 j</th><th>Exposition</th><th>Ordre du jour</th><th>Valeur</th></tr>
{rows}</table>
<p style="color:#666;font-size:12px">Compte fictif de {INITIAL_CAPITAL:,.0f} USDT, prix de cloture Binance, frais {FEE_BPS:.0f} bps.
Signal = part des horizons 20/60/120/250 j en tendance haussiere. Exposition = signal x 40 % / vol 30 j, max 100 %.</p>
</body></html>'''
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f'Compte demo crypto - {total:,.0f} USDT ({perf:+.1%}) - {date}'
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg.attach(MIMEText(html, 'html'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_FROM, password)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f'Email envoye a {EMAIL_TO}')
    except Exception as e:
        log.error(f'Erreur email : {e}')


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    parser = argparse.ArgumentParser(description='Compte demo trend crypto (un pas par jour)')
    parser.add_argument('--no-email', action='store_true')
    args = parser.parse_args()
    res = step()
    if res and not args.no_email:
        send_email(*res)


if __name__ == '__main__':
    main()
