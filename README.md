# screener-breakout

Depot remis a zero le 2026-10-06. Tout le travail precedent est archive dans l'historique git,
au commit `c9cb4c6` (dernier etat de `main` avant la remise a zero).

## Contenu de l'archive

| Projet | Dossiers |
|---|---|
| Screener actions (email quotidien, pattern mat-fanion) | `screener/`, `run_all.py` |
| Bot crypto G2 (rotation BTC/ETH/SOL) et compte paper | `bot/`, `paper_g2/` |
| Prevision BTC 1h (Chronos, EnKF, trend) et compte demo | `btc_forecast/`, `paper_trading/` |
| Recherche : strategies A-F, indicateurs, blocs de donnees | `bot/` (`research.py`, `blocks.py`, `run_backtest.py`) |
| Modele actions US > 2 Md$ | `bot/equities/` |
| Rapports | `bot/reports/` |
| Workflows GitHub Actions | `.github/workflows/` |

## Recuperer l'archive

Tout restaurer :

```
git checkout c9cb4c6 -- .
```

Un seul dossier, par exemple le screener :

```
git checkout c9cb4c6 -- screener run_all.py
```

Consulter sans restaurer : `git show c9cb4c6:bot/reports/g2_final.md`.
