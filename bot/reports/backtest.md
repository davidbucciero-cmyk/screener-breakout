# Backtest BTC/USD 1h

Donnees Binance BTCUSDT du 2022-10-03 au 2026-10-02 10:00 UTC. Couts : 25 bps de frais + 5 bps de slippage par cote.
Hors echantillon (gate) : a partir du 2024-10-02. Gate : Sharpe > 1.5, max DD > -15%, taux de reussite > 55%, t-stat > 2.67 (2.0 corrige de Bonferroni pour 6 strategies testees).

## Hors echantillon

| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |
|---|---|---|---|---|---|---|---|
| A - Breakout mat-fanion 1h | -7.6% | -0.50 | -0.71 | -26.6% | 41.2% | 34 | 8% |
| B - Trend ensemble + ciblage vol | +14.6% | 0.66 | 0.94 | -31.9% | 7.1% | 14 | 86% |
| C - Mat-fanion filtre par la tendance | +1.0% | 0.14 | 0.20 | -15.0% | 45.8% | 24 | 6% |
| D - Retour a la moyenne 1h en range | -28.7% | -2.18 | -3.08 | -49.7% | 27.8% | 97 | 6% |
| E - Cassure Donchian 20/10 j | +12.0% | 0.57 | 0.81 | -37.1% | 45.5% | 11 | 49% |
| F - RSI2 quotidien en tendance haussiere | +1.2% | 0.16 | 0.23 | -17.6% | 66.7% | 15 | 7% |
| Reference - Buy & hold | +18.7% | 0.61 | 0.86 | -53.7% | nan% | 0 | 100% |

## Verdict du gate

- **A - Breakout mat-fanion 1h** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **B - Trend ensemble + ciblage vol** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **C - Mat-fanion filtre par la tendance** : ECHOUE (echoue sur : sharpe, hit_rate, t_stat)
- **D - Retour a la moyenne 1h en range** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **E - Cassure Donchian 20/10 j** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **F - RSI2 quotidien en tendance haussiere** : ECHOUE (echoue sur : sharpe, max_drawdown, t_stat)

## Periode de dev (info seulement, pas de gate)

| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |
|---|---|---|---|---|---|---|---|
| A - Breakout mat-fanion 1h | -5.7% | -0.34 | -0.48 | -19.5% | 32.5% | 40 | 9% |
| B - Trend ensemble + ciblage vol | +36.3% | 1.31 | 1.85 | -22.8% | 100.0% | 1 | 66% |
| C - Mat-fanion filtre par la tendance | +1.3% | 0.17 | 0.24 | -15.1% | 40.0% | 25 | 7% |
| D - Retour a la moyenne 1h en range | -28.7% | -2.63 | -3.72 | -51.6% | 26.0% | 96 | 6% |
| E - Cassure Donchian 20/10 j | +22.3% | 0.85 | 1.20 | -23.1% | 38.5% | 13 | 46% |
| F - RSI2 quotidien en tendance haussiere | +6.8% | 0.49 | 0.70 | -27.9% | 71.4% | 21 | 11% |
| Reference - Buy & hold | +78.0% | 1.42 | 2.01 | -32.3% | 100.0% | 1 | 100% |

## Hors echantillon par regime

### A - Breakout mat-fanion 1h

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -15.9% | -2.43 |
| baissier / vol haute | 134 | -24.2% | -2.29 |
| haussier / vol basse | 169 | -19.8% | -1.91 |
| haussier / vol haute | 93 | +8.7% | 0.48 |
| range / vol basse | 207 | +18.1% | 1.19 |
| range / vol haute | 32 | -25.1% | -2.58 |

### B - Trend ensemble + ciblage vol

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -11.4% | -1.97 |
| baissier / vol haute | 134 | -14.1% | -1.37 |
| haussier / vol basse | 169 | +3.8% | 0.27 |
| haussier / vol haute | 93 | +162.5% | 3.18 |
| range / vol basse | 207 | +28.1% | 1.00 |
| range / vol haute | 32 | -38.9% | -2.36 |

### C - Mat-fanion filtre par la tendance

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | +0.0% | nan |
| baissier / vol haute | 134 | +9.1% | 1.65 |
| haussier / vol basse | 169 | -19.8% | -1.91 |
| haussier / vol haute | 93 | +8.7% | 0.48 |
| range / vol basse | 207 | +18.1% | 1.19 |
| range / vol haute | 32 | -25.1% | -2.58 |

### D - Retour a la moyenne 1h en range

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -14.8% | -3.25 |
| baissier / vol haute | 134 | +0.0% | nan |
| haussier / vol basse | 169 | +0.0% | nan |
| haussier / vol haute | 93 | +0.0% | nan |
| range / vol basse | 207 | -70.3% | -4.41 |
| range / vol haute | 32 | +84.0% | 3.71 |

### E - Cassure Donchian 20/10 j

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -6.0% | -0.44 |
| baissier / vol haute | 134 | -8.0% | -0.70 |
| haussier / vol basse | 169 | +4.7% | 0.30 |
| haussier / vol haute | 93 | +137.0% | 2.62 |
| range / vol basse | 207 | -4.5% | -0.04 |
| range / vol haute | 32 | +94.4% | 4.26 |

### F - RSI2 quotidien en tendance haussiere

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | +2.1% | 1.95 |
| baissier / vol haute | 134 | +0.0% | nan |
| haussier / vol basse | 169 | -1.5% | -0.09 |
| haussier / vol haute | 93 | +22.5% | 2.24 |
| range / vol basse | 207 | +3.4% | 0.29 |
| range / vol haute | 32 | -41.0% | -4.65 |

### Reference - Buy & hold

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -18.9% | -0.47 |
| baissier / vol haute | 134 | -3.6% | 0.23 |
| haussier / vol basse | 169 | +8.2% | 0.39 |
| haussier / vol haute | 93 | +321.1% | 3.41 |
| range / vol basse | 207 | +15.1% | 0.54 |
| range / vol haute | 32 | -55.9% | -1.71 |

