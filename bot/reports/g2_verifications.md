# G2 : verifications avant le premier ordre

## 1. Rejeu des 12 derniers mois avec le code du bot (depuis le 2025-10-01)

Chaque jour, le bot ne voit que les donnees disponibles ce jour-la. Attendu : 0 decision differente, performance proche du backtest en bougies 1h (ecart du aux prix quotidiens et a l'heure d'execution).

| Enveloppe | Jours | Decisions differentes du backtest | Perf. bot | Perf. backtest 1h | Max DD bot | Max DD backtest 1h |
|---|---|---|---|---|---|---|
| G2-19 | 366 | 0 | +6.1% | +6.2% | -6.8% | -8.5% |
| G2-25 | 366 | 0 | +7.6% | +7.8% | -8.9% | -11.0% |
| G2-40 | 366 | 0 | +6.4% | +6.8% | -14.0% | -16.4% |

**OK : le bot reproduit exactement les decisions du backtest**

## 2. Bandes de normalite (historique oct. 2015 -> aujourd'hui, fenetres glissantes)

Lecture : 90 % des periodes de cette duree ont un resultat entre p5 et p95.

### G2-19

| Duree | Rendement p5 | p25 | mediane | p75 | p95 | Periodes negatives | Pire DD p5 | DD median |
|---|---|---|---|---|---|---|---|---|
| 1 mois | -4.4% | -0.1% | +0.0% | +5.2% | +16.5% | 25% | -6.9% | -2.1% |
| 3 mois | -6.2% | +0.0% | +3.1% | +16.9% | +39.3% | 23% | -11.4% | -5.0% |
| 6 mois | -6.1% | +0.0% | +8.6% | +29.1% | +79.6% | 17% | -13.7% | -7.2% |

### G2-25

| Duree | Rendement p5 | p25 | mediane | p75 | p95 | Periodes negatives | Pire DD p5 | DD median |
|---|---|---|---|---|---|---|---|---|
| 1 mois | -5.7% | -0.1% | +0.0% | +6.7% | +21.7% | 26% | -9.0% | -2.8% |
| 3 mois | -8.1% | +0.0% | +4.0% | +22.2% | +54.1% | 24% | -14.9% | -6.3% |
| 6 mois | -8.0% | +0.0% | +10.5% | +38.7% | +112.4% | 17% | -17.8% | -9.4% |

### G2-40

| Duree | Rendement p5 | p25 | mediane | p75 | p95 | Periodes negatives | Pire DD p5 | DD median |
|---|---|---|---|---|---|---|---|---|
| 1 mois | -9.3% | -0.4% | +0.0% | +9.8% | +34.5% | 26% | -13.6% | -4.3% |
| 3 mois | -13.0% | +0.0% | +5.6% | +34.5% | +96.4% | 24% | -22.5% | -9.9% |
| 6 mois | -12.8% | +0.0% | +14.5% | +62.1% | +206.4% | 18% | -27.3% | -14.5% |
