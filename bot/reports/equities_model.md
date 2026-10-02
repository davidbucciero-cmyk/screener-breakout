# Actions US : modele combine (7 blocs), evaluation unique hors echantillon

Hors echantillon : 2019-01 a 2026-09. Top 10 % du score, poids egal, couvert par une vente de SPY. Frais 10 bps par cote (actions), 2 bps (SPY), emprunt SPY 0,5 %/an.
Taux de reussite = part des positions qui battent SPY sur leur mois.

## Hors echantillon (le seul resultat qui compte)

| Serie | Mois | Rdt annuel | Sharpe | t-stat | Max DD | Mois positifs | Taux de reussite (positions) |
|---|---|---|---|---|---|---|---|
| Couvert (long - SPY) | 93 | -6.9% | -0.76 | -2.12 | -43.5% | 43% | 46% |
| Long seul | 93 | +9.7% | 0.72 | 2.00 | -21.9% | 61% | 46% |
| SPY | 93 | +16.2% | 1.01 | 2.82 | -23.9% | 67% |  |

## Verdict du gate

- Sharpe > 1.5 : ECHEC
- Max DD > -15 % : ECHEC
- Taux de reussite > 55 % : ECHEC
- t-stat > 2.89 : ECHEC

**ECHOUE**

Beta de la jambe longue vs SPY (hors echantillon) : 0.74. La couverture 1:1 sur-couvre le marche.
Positions par mois : 128. Rotation mensuelle moyenne : 26%. Positions sans prix le mois suivant (comptees a 0 %) : 173.

## Periode de dev 2010-2018 (info, poids appris en fenetre croissante)

| Serie | Mois | Rdt annuel | Sharpe | t-stat | Max DD | Mois positifs | Taux de reussite (positions) |
|---|---|---|---|---|---|---|---|
| Couvert (long - SPY) | 84 | +0.5% | 0.11 | 0.28 | -9.3% | 49% | 51% |
| Long seul | 84 | +14.4% | 1.18 | 3.11 | -14.5% | 64% | 51% |
| SPY | 84 | +13.1% | 1.19 | 3.15 | -13.5% | 74% |  |

## Rendement par annee

| Annee | Couvert | Long seul | SPY |
|---|---|---|---|
| 2012 | +7.0% | +24.3% | +16.5% |
| 2013 | +0.3% | +22.5% | +21.4% |
| 2014 | +0.3% | +15.2% | +14.1% |
| 2015 | +4.2% | +4.5% | -0.9% |
| 2016 | -4.8% | +15.0% | +20.0% |
| 2017 | -1.9% | +24.7% | +26.3% |
| 2018 | -1.4% | -2.8% | -2.4% |
| 2019 | -6.3% | +15.4% | +21.4% |
| 2020 | -11.0% | +5.8% | +17.2% |
| 2021 | -6.2% | +16.2% | +23.2% |
| 2022 | +2.0% | -3.9% | -8.2% |
| 2023 | -11.3% | +8.2% | +20.6% |
| 2024 | -2.6% | +23.5% | +26.2% |
| 2025 | -6.5% | +10.4% | +16.3% |
| 2026 | -10.6% | +1.9% | +12.2% |

## Poids appris par annee (IC moyen passe ; signe negatif = moins c'est mieux)

| Annee | C2_variation_actions_1an | C1_marge_brute_sur_actifs | B3_volatilite_12m | B2_proximite_plus_haut_52s | B1_momentum_12_1 | C6_accruals | A6_sma50_sup_sma200 |
|---|---|---|---|---|---|---|---|
| 2012 | -0.023 | +0.030 | -0.013 | -0.022 | -0.013 | +0.006 | -0.019 |
| 2013 | -0.027 | +0.024 | -0.034 | +0.004 | +0.012 | +0.013 | -0.009 |
| 2014 | -0.040 | +0.020 | -0.033 | +0.022 | +0.027 | +0.014 | +0.011 |
| 2015 | -0.045 | +0.023 | -0.051 | +0.037 | +0.024 | +0.018 | +0.015 |
| 2016 | -0.047 | +0.027 | -0.065 | +0.051 | +0.039 | +0.021 | +0.023 |
| 2017 | -0.049 | +0.026 | -0.068 | +0.049 | +0.033 | +0.024 | +0.022 |
| 2018 | -0.051 | +0.031 | -0.072 | +0.056 | +0.039 | +0.024 | +0.029 |
| 2019 | -0.049 | +0.035 | -0.081 | +0.063 | +0.041 | +0.025 | +0.032 |
| 2020 | -0.051 | +0.036 | -0.081 | +0.062 | +0.041 | +0.030 | +0.032 |
| 2021 | -0.046 | +0.037 | -0.073 | +0.060 | +0.042 | +0.027 | +0.032 |
| 2022 | -0.052 | +0.037 | -0.080 | +0.066 | +0.038 | +0.028 | +0.035 |
| 2023 | -0.058 | +0.037 | -0.087 | +0.072 | +0.044 | +0.031 | +0.035 |
| 2024 | -0.061 | +0.041 | -0.093 | +0.078 | +0.050 | +0.033 | +0.039 |
| 2025 | -0.060 | +0.041 | -0.096 | +0.082 | +0.053 | +0.035 | +0.042 |
| 2026 | -0.059 | +0.039 | -0.094 | +0.084 | +0.054 | +0.036 | +0.042 |
| 2027 | -0.059 | +0.037 | -0.092 | +0.082 | +0.054 | +0.035 | +0.042 |

## Limites

- Biais du survivant : entreprises radiees absentes (ni ticker SEC ni prix Yahoo). Resultats flattes.
- Donnees XBRL frames : derniere valeur deposee, une correction posterieure peut fuiter (decalage 90 j).
