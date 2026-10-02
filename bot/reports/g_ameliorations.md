# Ameliorations de G

Donnees Binance du 2017-08-17 au 2026-10-02. Couts : 25 bps + 5 bps de slippage par cote. SOL n'existe qu'a partir d'aout 2020 : avant, rotation BTC/ETH.
Gate jugee uniquement sur la periode jamais utilisee (2018-04-01 -> 2022-10-03) : Sharpe > 1.5, max DD > -15%, taux de reussite > 55%, t-stat > 2.96 (15 strategies testees au total).

## Periode jamais utilisee (avril 2018 -> septembre 2022) : le seul juge

| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |
|---|---|---|---|---|---|---|---|
| G - reference (top 1, 30 j) | +71.7% | 1.69 | 3.59 | -38.5% | 54.3% | 46 | 64% |
| G1 - horizons 14/30/60/90 j | +69.7% | 1.62 | 3.45 | -47.1% | 43.8% | 32 | 64% |
| G2 - G + filtre BTC > moyenne 200 j | +70.9% | 1.98 | 4.21 | -30.7% | 48.4% | 31 | 39% |
| G3 - top 2, moitie chacune | +54.4% | 1.60 | 3.40 | -36.1% | 54.2% | 59 | 64% |
| Reference - BTC achete et garde | +25.2% | 0.68 | 1.44 | -74.1% | nan% | 0 | 100% |
| Reference - BTC/ETH/SOL a parts egales | +61.5% | 1.02 | 2.17 | -81.5% | nan% | 0 | 100% |

## Verdict du gate (periode jamais utilisee)

- **G - reference (top 1, 30 j)** : ECHOUE (echoue sur : max_drawdown, hit_rate)
- **G1 - horizons 14/30/60/90 j** : ECHOUE (echoue sur : max_drawdown, hit_rate)
- **G2 - G + filtre BTC > moyenne 200 j** : ECHOUE (echoue sur : max_drawdown, hit_rate)
- **G3 - top 2, moitie chacune** : ECHOUE (echoue sur : max_drawdown, hit_rate)

## Periode deja vue (octobre 2022 -> aujourd'hui), info seulement

| Strategie | Rdt annuel | Sharpe | t-stat | Max DD | Taux reussite | Trades | Expo |
|---|---|---|---|---|---|---|---|
| G - reference (top 1, 30 j) | +38.1% | 1.09 | 2.19 | -39.0% | 40.0% | 50 | 67% |
| G1 - horizons 14/30/60/90 j | +5.0% | 0.31 | 0.63 | -47.3% | 33.3% | 45 | 67% |
| G2 - G + filtre BTC > moyenne 200 j | +35.0% | 1.20 | 2.41 | -33.0% | 44.7% | 38 | 49% |
| G3 - top 2, moitie chacune | +31.2% | 1.03 | 2.06 | -32.8% | 40.6% | 69 | 67% |
| Reference - BTC achete et garde | +45.4% | 1.03 | 2.07 | -53.7% | nan% | 0 | 100% |
| Reference - BTC/ETH/SOL a parts egales | +41.8% | 0.88 | 1.76 | -65.4% | nan% | 0 | 100% |

## Periode jamais utilisee, par regime

### G - reference (top 1, 30 j)

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 315 | +8.9% | 0.48 |
| baissier / vol haute | 274 | -27.8% | -1.22 |
| haussier / vol basse | 383 | +521.5% | 4.04 |
| haussier / vol haute | 276 | +155.9% | 2.76 |
| range / vol basse | 345 | -1.1% | 0.16 |
| range / vol haute | 53 | -5.4% | -0.19 |

### G1 - horizons 14/30/60/90 j

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 315 | +12.2% | 0.79 |
| baissier / vol haute | 274 | +8.6% | 0.44 |
| haussier / vol basse | 383 | +443.9% | 3.71 |
| haussier / vol haute | 276 | +183.2% | 2.87 |
| range / vol basse | 345 | -27.8% | -0.61 |
| range / vol haute | 53 | -20.6% | -0.95 |

### G2 - G + filtre BTC > moyenne 200 j

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 315 | -7.5% | -1.18 |
| baissier / vol haute | 274 | -17.1% | -1.18 |
| haussier / vol basse | 383 | +378.6% | 3.82 |
| haussier / vol haute | 276 | +137.6% | 2.60 |
| range / vol basse | 345 | +49.2% | 1.71 |
| range / vol haute | 53 | -29.2% | -2.16 |

### G3 - top 2, moitie chacune

| Regime | Jours | Rdt annualise | Sharpe |
|---|---|---|---|
| baissier / vol basse | 315 | +10.3% | 0.61 |
| baissier / vol haute | 274 | -27.4% | -1.45 |
| haussier / vol basse | 383 | +248.5% | 3.27 |
| haussier / vol haute | 276 | +153.2% | 3.02 |
| range / vol basse | 345 | +2.4% | 0.23 |
| range / vol haute | 53 | +73.3% | 3.16 |

## Rendement par annee

| Annee | G - reference (top 1, 30 j) | G1 - horizons 14/30/60/90 j | G2 - G + filtre BTC > moyenne 200 j | G3 - top 2, moitie chacune | Reference - BTC achete et garde | Reference - BTC/ETH/SOL a parts egales |
|---|---|---|---|---|---|---|
| 2017 | +71.8% | +32.2% | +71.8% | +56.9% | +217.4% | +124.6% |
| 2018 | -26.4% | -34.3% | -6.9% | -26.3% | -73.0% | -57.2% |
| 2019 | +52.0% | +87.1% | +45.0% | +35.8% | +94.3% | +33.4% |
| 2020 | +235.4% | +212.7% | +188.0% | +177.9% | +302.0% | +174.1% |
| 2021 | +253.2% | +284.9% | +168.5% | +173.3% | +59.8% | +1132.1% |
| 2022 | -20.6% | -36.1% | +0.0% | -18.8% | -64.2% | -79.3% |
| 2023 | +139.8% | +45.0% | +108.2% | +119.5% | +155.6% | +292.5% |
| 2024 | +19.3% | +8.0% | +8.7% | +24.1% | +121.3% | +91.6% |
| 2025 | +28.1% | +35.7% | +23.8% | +16.8% | -6.3% | -14.1% |
| 2026 | +4.0% | -31.8% | +18.6% | +5.3% | -2.6% | -4.0% |
