# Backtest BTC/USD 1h

Donnees Binance BTCUSDT du 2022-10-03 au 2026-10-02 11:00 UTC. Couts : 25 bps de frais + 5 bps de slippage par cote.
Hors echantillon (gate) : a partir du 2024-10-02. Gate : Sharpe > 1.5, max DD > -15%, taux de reussite > 55%, t-stat > 2.87 (2.0 corrige de Bonferroni pour 11 strategies testees).

## Hors echantillon

| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |
|---|---|---|---|---|---|---|---|
| A - Breakout mat-fanion 1h | -7.6% | -0.50 | -0.71 | -26.6% | 41.2% | 34 | 8% |
| B - Trend ensemble + ciblage vol | +14.7% | 0.67 | 0.94 | -31.9% | 7.1% | 14 | 86% |
| C - Mat-fanion filtre par la tendance | +1.0% | 0.14 | 0.20 | -15.0% | 45.8% | 24 | 6% |
| D - Retour a la moyenne 1h en range | -28.7% | -2.18 | -3.08 | -49.7% | 27.8% | 97 | 6% |
| E - Cassure Donchian 20/10 j | +12.0% | 0.58 | 0.82 | -37.1% | 45.5% | 11 | 49% |
| F - RSI2 quotidien en tendance haussiere | +1.2% | 0.16 | 0.23 | -17.6% | 66.7% | 15 | 7% |
| Reference - Buy & hold | +18.8% | 0.61 | 0.86 | -53.7% | nan% | 0 | 100% |
| G - Rotation momentum BTC/ETH/SOL | +32.1% | 0.99 | 1.41 | -39.0% | 37.5% | 24 | 63% |
| H - Trend diversifie BTC/ETH/SOL | +11.3% | 0.60 | 0.85 | -29.0% | 25.5% | 51 | 92% |
| Reference - Buy & hold equipondere BTC/ETH/SOL | +8.6% | 0.43 | 0.62 | -65.4% | nan% | 0 | 100% |
| I - Momentum top 3 sur 11 cryptos | +7.2% | 0.38 | 0.54 | -48.9% | 40.4% | 94 | 83% |
| J - Rotation G + filtre de financement | +22.5% | 0.78 | 1.11 | -39.0% | 40.6% | 32 | 58% |
| K - Panier G + H + E | +19.0% | 0.84 | 1.19 | -31.4% | 31.4% | 86 | 93% |

## Verdict du gate

- **A - Breakout mat-fanion 1h** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **B - Trend ensemble + ciblage vol** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **C - Mat-fanion filtre par la tendance** : ECHOUE (echoue sur : sharpe, hit_rate, t_stat)
- **D - Retour a la moyenne 1h en range** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **E - Cassure Donchian 20/10 j** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **F - RSI2 quotidien en tendance haussiere** : ECHOUE (echoue sur : sharpe, max_drawdown, t_stat)
- **G - Rotation momentum BTC/ETH/SOL** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **H - Trend diversifie BTC/ETH/SOL** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **I - Momentum top 3 sur 11 cryptos** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **J - Rotation G + filtre de financement** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)
- **K - Panier G + H + E** : ECHOUE (echoue sur : sharpe, max_drawdown, hit_rate, t_stat)

## Periode de dev (info seulement, pas de gate)

| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |
|---|---|---|---|---|---|---|---|
| A - Breakout mat-fanion 1h | -5.7% | -0.34 | -0.48 | -19.5% | 32.5% | 40 | 9% |
| B - Trend ensemble + ciblage vol | +36.2% | 1.31 | 1.85 | -22.8% | 100.0% | 1 | 66% |
| C - Mat-fanion filtre par la tendance | +1.3% | 0.17 | 0.24 | -15.1% | 40.0% | 25 | 7% |
| D - Retour a la moyenne 1h en range | -28.7% | -2.64 | -3.73 | -51.6% | 26.0% | 96 | 6% |
| E - Cassure Donchian 20/10 j | +22.3% | 0.85 | 1.20 | -23.1% | 38.5% | 13 | 46% |
| F - RSI2 quotidien en tendance haussiere | +6.8% | 0.49 | 0.70 | -27.9% | 71.4% | 21 | 11% |
| Reference - Buy & hold | +78.2% | 1.42 | 2.01 | -32.3% | 100.0% | 1 | 100% |
| G - Rotation momentum BTC/ETH/SOL | +34.3% | 1.02 | 1.44 | -35.5% | 42.3% | 26 | 67% |
| H - Trend diversifie BTC/ETH/SOL | +34.3% | 1.41 | 1.99 | -20.6% | 37.5% | 8 | 66% |
| Reference - Buy & hold equipondere BTC/ETH/SOL | +83.5% | 1.28 | 1.81 | -48.6% | 100.0% | 3 | 100% |
| I - Momentum top 3 sur 11 cryptos | +17.0% | 0.68 | 0.97 | -33.8% | 46.7% | 90 | 80% |
| J - Rotation G + filtre de financement | +6.9% | 0.38 | 0.54 | -26.7% | 57.1% | 35 | 47% |
| K - Panier G + H + E | +31.7% | 1.25 | 1.77 | -23.2% | 40.4% | 47 | 87% |

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
| haussier / vol basse | 169 | +4.1% | 0.28 |
| haussier / vol haute | 93 | +162.5% | 3.18 |
| range / vol basse | 207 | +28.3% | 1.00 |
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
| range / vol basse | 207 | -70.2% | -4.40 |
| range / vol haute | 32 | +84.0% | 3.71 |

### E - Cassure Donchian 20/10 j

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -6.0% | -0.44 |
| baissier / vol haute | 134 | -8.0% | -0.70 |
| haussier / vol basse | 169 | +5.0% | 0.31 |
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
| haussier / vol basse | 169 | +8.5% | 0.40 |
| haussier / vol haute | 93 | +321.1% | 3.41 |
| range / vol basse | 207 | +15.4% | 0.55 |
| range / vol haute | 32 | -55.9% | -1.71 |

### G - Rotation momentum BTC/ETH/SOL

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -30.9% | -2.10 |
| baissier / vol haute | 134 | -2.6% | -0.13 |
| haussier / vol basse | 169 | +47.0% | 1.23 |
| haussier / vol haute | 93 | +139.5% | 2.53 |
| range / vol basse | 207 | +59.1% | 1.26 |
| range / vol haute | 32 | +0.3% | 0.08 |

### H - Trend diversifie BTC/ETH/SOL

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -3.4% | -0.62 |
| baissier / vol haute | 134 | -9.4% | -1.62 |
| haussier / vol basse | 169 | +3.3% | 0.25 |
| haussier / vol haute | 93 | +111.7% | 2.98 |
| range / vol basse | 207 | +17.4% | 0.73 |
| range / vol haute | 32 | -35.1% | -2.88 |

### Reference - Buy & hold equipondere BTC/ETH/SOL

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | +4.0% | 0.30 |
| baissier / vol haute | 134 | -31.2% | -0.16 |
| haussier / vol basse | 169 | +6.3% | 0.37 |
| haussier / vol haute | 93 | +518.3% | 3.49 |
| range / vol basse | 207 | -3.3% | 0.27 |
| range / vol haute | 32 | -87.4% | -2.93 |

### I - Momentum top 3 sur 11 cryptos

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -21.7% | -1.10 |
| baissier / vol haute | 134 | -10.5% | -0.73 |
| haussier / vol basse | 169 | +6.6% | 0.35 |
| haussier / vol haute | 93 | +211.9% | 3.46 |
| range / vol basse | 207 | -11.9% | -0.17 |
| range / vol haute | 32 | -2.8% | -0.28 |

### J - Rotation G + filtre de financement

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -30.9% | -2.10 |
| baissier / vol haute | 134 | -2.6% | -0.13 |
| haussier / vol basse | 169 | +28.0% | 0.86 |
| haussier / vol haute | 93 | +110.9% | 2.47 |
| range / vol basse | 207 | +44.6% | 1.05 |
| range / vol haute | 32 | +0.3% | 0.08 |

### K - Panier G + H + E

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -14.1% | -1.44 |
| baissier / vol haute | 134 | -6.4% | -0.82 |
| haussier / vol basse | 169 | +17.9% | 0.72 |
| haussier / vol haute | 93 | +131.3% | 2.92 |
| range / vol basse | 207 | +22.6% | 0.83 |
| range / vol haute | 32 | +8.9% | 0.86 |

