"""Recupere chaque bloc et ecrit sa couverture reelle dans bot/reports/blocks.md."""
import logging
import os
from pathlib import Path

import pandas as pd

from bot.blocks import BLOCKS

OUT = Path(__file__).parent / 'reports' / 'blocks.md'
DATA = Path(__file__).parent / 'data'


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    lines = ['# Couverture des blocs de donnees', '',
             '| Bloc | Series | Debut | Fin | Jours | Statut |', '|---|---|---|---|---|---|']
    DATA.mkdir(exist_ok=True)
    for name, fn in BLOCKS.items():
        try:
            x = fn()
            df = x.to_frame() if isinstance(x, pd.Series) else x
            df = df.dropna(how='all')
            df.to_csv(DATA / f"{name.split(' ')[0]}.csv")
            for col in df.columns:
                s = df[col].dropna()
                lines.append(f'| {name} | {col} | {s.index[0]:%Y-%m-%d} | {s.index[-1]:%Y-%m-%d} | {len(s)} | OK |')
        except Exception as e:
            lines.append(f'| {name} | - | - | - | - | ECHEC : {type(e).__name__}: {str(e)[:80]} |')
    report = '\n'.join(lines) + '\n'
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(report)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write(report)
    print(report)


if __name__ == '__main__':
    main()
