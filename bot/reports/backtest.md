# Backtest BTC/USD 1h

Donnees Binance BTCUSDT du 2022-10-07 au 2026-10-06 13:00 UTC. Couts : 25 bps de frais + 5 bps de slippage par cote.
Hors echantillon (gate) : a partir du 2024-10-06. Gate : Sharpe > 1.5, max DD > -15%, taux de reussite > 55%, t-stat > 2.87 (2.0 corrige de Bonferroni pour 11 strategies testees).

## Hors echantillon

| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |
|---|---|---|---|---|---|---|---|
| A - Breakout mat-fanion 1h | -7.6% | -0.50 | -0.71 | -26.6% | 41.2% | 34 | 8% |
| B - Trend ensemble + ciblage vol | +13.9% | 0.64 | 0.90 | -31.9% | 7.1% | 14 | 86% |
| C - Mat-fanion filtre par la tendance | +1.0% | 0.14 | 0.20 | -15.0% | 45.8% | 24 | 6% |
| D - Retour a la moyenne 1h en range | -28.4% | -2.15 | -3.05 | -48.8% | 27.8% | 97 | 6% |
| E - Cassure Donchian 20/10 j | +12.0% | 0.57 | 0.81 | -37.1% | 45.5% | 11 | 50% |
| F - RSI2 quotidien en tendance haussiere | +1.2% | 0.16 | 0.23 | -17.6% | 66.7% | 15 | 7% |
| Reference - Buy & hold | +17.8% | 0.59 | 0.83 | -53.7% | nan% | 0 | 100% |
| G - Rotation momentum BTC/ETH/SOL | +32.1% | 1.00 | 1.41 | -39.0% | 37.5% | 24 | 63% |
| H - Trend diversifie BTC/ETH/SOL | +11.1% | 0.59 | 0.84 | -29.0% | 25.5% | 51 | 92% |
| Reference - Buy & hold equipondere BTC/ETH/SOL | +8.2% | 0.43 | 0.61 | -65.4% | nan% | 0 | 100% |
| I - Momentum top 3 sur 11 cryptos | +6.9% | 0.37 | 0.53 | -48.9% | 41.1% | 95 | 83% |
| J - Rotation G + filtre de financement | +22.5% | 0.78 | 1.11 | -39.0% | 40.6% | 32 | 58% |
| K - Panier G + H + E | +18.9% | 0.84 | 1.19 | -31.4% | 31.4% | 86 | 93% |

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
| B - Trend ensemble + ciblage vol | +38.0% | 1.36 | 1.92 | -22.8% | 100.0% | 1 | 66% |
| C - Mat-fanion filtre par la tendance | +1.3% | 0.17 | 0.24 | -15.1% | 40.0% | 25 | 7% |
| D - Retour a la moyenne 1h en range | -29.0% | -2.67 | -3.77 | -51.9% | 26.0% | 96 | 6% |
| E - Cassure Donchian 20/10 j | +20.1% | 0.79 | 1.12 | -23.1% | 38.5% | 13 | 46% |
| F - RSI2 quotidien en tendance haussiere | +5.2% | 0.41 | 0.57 | -27.9% | 70.0% | 20 | 11% |
| Reference - Buy & hold | +77.9% | 1.42 | 2.01 | -32.3% | 100.0% | 1 | 100% |
| G - Rotation momentum BTC/ETH/SOL | +33.9% | 1.01 | 1.43 | -35.5% | 42.3% | 26 | 67% |
| H - Trend diversifie BTC/ETH/SOL | +35.2% | 1.44 | 2.04 | -21.4% | 37.5% | 8 | 66% |
| Reference - Buy & hold equipondere BTC/ETH/SOL | +83.4% | 1.28 | 1.81 | -48.6% | 100.0% | 3 | 100% |
| I - Momentum top 3 sur 11 cryptos | +17.3% | 0.69 | 0.98 | -33.8% | 46.7% | 90 | 80% |
| J - Rotation G + filtre de financement | +6.6% | 0.37 | 0.52 | -26.7% | 57.1% | 35 | 48% |
| K - Panier G + H + E | +31.1% | 1.23 | 1.74 | -24.4% | 40.4% | 47 | 87% |

## Hors echantillon par regime

### A - Breakout mat-fanion 1h

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -15.9% | -2.43 |
| baissier / vol haute | 134 | -24.2% | -2.29 |
| haussier / vol basse | 173 | -19.4% | -1.89 |
| haussier / vol haute | 92 | +8.8% | 0.49 |
| range / vol basse | 205 | +18.3% | 1.19 |
| range / vol haute | 31 | -25.8% | -2.62 |

### B - Trend ensemble + ciblage vol

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -11.4% | -1.97 |
| baissier / vol haute | 134 | -14.1% | -1.37 |
| haussier / vol basse | 173 | +9.2% | 0.43 |
| haussier / vol haute | 92 | +139.7% | 2.91 |
| range / vol basse | 205 | +25.1% | 0.92 |
| range / vol haute | 31 | -37.5% | -2.20 |

### C - Mat-fanion filtre par la tendance

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | +0.0% | nan |
| baissier / vol haute | 134 | +9.1% | 1.65 |
| haussier / vol basse | 173 | -19.4% | -1.89 |
| haussier / vol haute | 92 | +8.8% | 0.49 |
| range / vol basse | 205 | +18.3% | 1.19 |
| range / vol haute | 31 | -25.8% | -2.62 |

### D - Retour a la moyenne 1h en range

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -14.8% | -3.25 |
| baissier / vol haute | 134 | +0.0% | nan |
| haussier / vol basse | 173 | +0.0% | nan |
| haussier / vol haute | 92 | +0.0% | nan |
| range / vol basse | 205 | -70.2% | -4.37 |
| range / vol haute | 31 | +87.6% | 3.77 |

### E - Cassure Donchian 20/10 j

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -6.0% | -0.44 |
| baissier / vol haute | 134 | -8.0% | -0.70 |
| haussier / vol basse | 173 | +12.4% | 0.53 |
| haussier / vol haute | 92 | +109.2% | 2.29 |
| range / vol basse | 205 | -5.2% | -0.06 |
| range / vol haute | 31 | +107.1% | 4.61 |

### F - RSI2 quotidien en tendance haussiere

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | +2.1% | 1.95 |
| baissier / vol haute | 134 | +0.0% | nan |
| haussier / vol basse | 173 | +5.5% | 0.53 |
| haussier / vol haute | 92 | +8.0% | 1.19 |
| range / vol basse | 205 | +3.4% | 0.30 |
| range / vol haute | 31 | -42.0% | -4.73 |

### Reference - Buy & hold

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -18.9% | -0.47 |
| baissier / vol haute | 134 | -3.6% | 0.23 |
| haussier / vol basse | 173 | +16.8% | 0.60 |
| haussier / vol haute | 92 | +266.3% | 3.12 |
| range / vol basse | 205 | +11.8% | 0.47 |
| range / vol haute | 31 | -55.0% | -1.63 |

### G - Rotation momentum BTC/ETH/SOL

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -30.9% | -2.10 |
| baissier / vol haute | 134 | -2.6% | -0.13 |
| haussier / vol basse | 173 | +42.5% | 1.15 |
| haussier / vol haute | 92 | +141.8% | 2.55 |
| range / vol basse | 205 | +61.0% | 1.29 |
| range / vol haute | 31 | +8.1% | 0.86 |

### H - Trend diversifie BTC/ETH/SOL

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -3.4% | -0.62 |
| baissier / vol haute | 134 | -9.4% | -1.62 |
| haussier / vol basse | 173 | +5.7% | 0.34 |
| haussier / vol haute | 92 | +100.1% | 2.77 |
| range / vol basse | 205 | +17.7% | 0.74 |
| range / vol haute | 31 | -34.3% | -2.74 |

### Reference - Buy & hold equipondere BTC/ETH/SOL

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | +4.0% | 0.30 |
| baissier / vol haute | 134 | -31.2% | -0.16 |
| haussier / vol basse | 173 | +10.6% | 0.45 |
| haussier / vol haute | 92 | +455.6% | 3.30 |
| range / vol basse | 205 | -3.4% | 0.27 |
| range / vol haute | 31 | -87.3% | -2.86 |

### I - Momentum top 3 sur 11 cryptos

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -21.7% | -1.10 |
| baissier / vol haute | 134 | -10.5% | -0.73 |
| haussier / vol basse | 173 | +5.5% | 0.33 |
| haussier / vol haute | 92 | +212.4% | 3.45 |
| range / vol basse | 205 | -13.0% | -0.20 |
| range / vol haute | 31 | +4.1% | 0.51 |

### J - Rotation G + filtre de financement

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -30.9% | -2.10 |
| baissier / vol haute | 134 | -2.6% | -0.13 |
| haussier / vol basse | 173 | +24.5% | 0.79 |
| haussier / vol haute | 92 | +112.6% | 2.48 |
| range / vol basse | 205 | +46.2% | 1.07 |
| range / vol haute | 31 | +8.1% | 0.86 |

### K - Panier G + H + E

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 96 | -14.1% | -1.44 |
| baissier / vol haute | 134 | -6.4% | -0.82 |
| haussier / vol basse | 173 | +20.2% | 0.79 |
| haussier / vol haute | 92 | +118.4% | 2.73 |
| range / vol basse | 205 | +22.9% | 0.84 |
| range / vol haute | 31 | +14.5% | 1.34 |

