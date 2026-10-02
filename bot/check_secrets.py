"""Verifie que les secrets sont presents (jamais leur valeur) et que les cles Alpaca paper marchent."""
import os
import sys

import requests

ALPACA_PAPER = 'https://paper-api.alpaca.markets'
NAMES = ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'TYPESAFE_API_KEY', 'ANTHROPIC_API_KEY']


def main():
    ok = True
    for n in NAMES:
        present = bool(os.environ.get(n))
        ok &= present
        print(f"{n}: {'present' if present else 'MANQUANT'}")
    if os.environ.get('ALPACA_API_KEY') and os.environ.get('ALPACA_SECRET_KEY'):
        r = requests.get(f'{ALPACA_PAPER}/v2/account', timeout=20, headers={
            'APCA-API-KEY-ID': os.environ['ALPACA_API_KEY'],
            'APCA-API-SECRET-KEY': os.environ['ALPACA_SECRET_KEY']})
        if r.ok:
            a = r.json()
            print(f"Alpaca paper: OK (statut {a.get('status')}, crypto {a.get('crypto_status')})")
        else:
            ok = False
            print(f'Alpaca paper: ECHEC HTTP {r.status_code}')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
