# Actions US : modele combine (7 blocs), evaluation unique hors echantillon

Hors echantillon : 2019-01 a 2026-09. Top 10 % du score, poids egal, couvert par une vente de SPY. Frais 10 bps par cote (actions), 2 bps (SPY), emprunt SPY 0,5 %/an.
Taux de reussite = part des positions qui battent SPY sur leur mois.

## Hors echantillon (le seul resultat qui compte)

| Serie | Mois | Rdt annuel | Sharpe | t-stat | Max DD | Mois positifs | Taux de reussite (positions) |
|---|---|---|---|---|---|---|---|
| Couvert (long - SPY) | 93 | -3.6% | -0.42 | -1.16 | -24.9% | 43% | 47% |
| Long seul | 93 | +12.8% | 0.78 | 2.17 | -26.4% | 63% | 47% |
| SPY | 93 | +16.2% | 1.01 | 2.82 | -23.9% | 67% |  |

## Verdict du gate

- Sharpe > 1.5 : ECHEC
- Max DD > -15 % : ECHEC
- Taux de reussite > 55 % : ECHEC
- t-stat > 2.89 : ECHEC

**ECHOUE**

Beta de la jambe longue vs SPY (hors echantillon) : 0.95. La couverture 1:1 couvre correctement le marche.
Positions par mois : 110. Rotation mensuelle moyenne : 22%. Positions sans prix le mois suivant (comptees a 0 %) : 0.

## Periode de dev 2010-2018 (info, poids appris en fenetre croissante)

| Serie | Mois | Rdt annuel | Sharpe | t-stat | Max DD | Mois positifs | Taux de reussite (positions) |
|---|---|---|---|---|---|---|---|
| Couvert (long - SPY) | 84 | -1.6% | -0.23 | -0.62 | -17.4% | 46% | 50% |
| Long seul | 84 | +12.0% | 0.95 | 2.52 | -16.0% | 62% | 50% |
| SPY | 84 | +13.1% | 1.19 | 3.15 | -13.5% | 74% |  |

## Rendement par annee

| Annee | Couvert | Long seul | SPY |
|---|---|---|---|
| 2012 | -0.3% | +16.4% | +16.5% |
| 2013 | -1.9% | +20.0% | +21.4% |
| 2014 | +1.4% | +16.3% | +14.1% |
| 2015 | -7.0% | -7.0% | -0.9% |
| 2016 | -2.6% | +17.6% | +20.0% |
| 2017 | -1.8% | +24.8% | +26.3% |
| 2018 | +1.4% | -0.5% | -2.4% |
| 2019 | -7.7% | +13.0% | +21.4% |
| 2020 | -1.5% | +15.1% | +17.2% |
| 2021 | -6.2% | +16.2% | +23.2% |
| 2022 | +9.0% | +1.4% | -8.2% |
| 2023 | -6.6% | +13.5% | +20.6% |
| 2024 | -1.9% | +24.1% | +26.2% |
| 2025 | -4.8% | +12.0% | +16.3% |
| 2026 | -7.5% | +5.1% | +12.2% |

## Poids appris par annee (IC moyen passe ; signe negatif = moins c'est mieux)

| Annee | C2_variation_actions_1an | C1_marge_brute_sur_actifs | B3_volatilite_12m | B2_proximite_plus_haut_52s | B1_momentum_12_1 | C6_accruals | A6_sma50_sup_sma200 |
|---|---|---|---|---|---|---|---|
| 2012 | -0.026 | +0.027 | +0.007 | -0.038 | -0.019 | -0.004 | -0.023 |
| 2013 | -0.023 | +0.019 | +0.004 | -0.026 | -0.001 | -0.005 | -0.024 |
| 2014 | -0.031 | +0.014 | +0.016 | -0.012 | +0.015 | -0.008 | -0.007 |
| 2015 | -0.028 | +0.014 | +0.006 | -0.005 | +0.010 | -0.010 | -0.007 |
| 2016 | -0.024 | +0.017 | -0.005 | +0.007 | +0.023 | -0.009 | +0.002 |
| 2017 | -0.026 | +0.010 | -0.002 | -0.003 | +0.007 | -0.006 | -0.006 |
| 2018 | -0.026 | +0.013 | -0.001 | -0.000 | +0.011 | -0.007 | -0.002 |
| 2019 | -0.022 | +0.016 | -0.009 | +0.006 | +0.010 | -0.008 | +0.000 |
| 2020 | -0.022 | +0.015 | -0.005 | -0.000 | +0.006 | -0.005 | -0.002 |
| 2021 | -0.016 | +0.017 | +0.002 | +0.001 | +0.009 | -0.008 | +0.000 |
| 2022 | -0.021 | +0.017 | -0.003 | +0.004 | +0.007 | -0.006 | +0.003 |
| 2023 | -0.025 | +0.015 | -0.008 | +0.006 | +0.007 | -0.004 | +0.002 |
| 2024 | -0.027 | +0.017 | -0.009 | +0.007 | +0.008 | -0.003 | +0.002 |
| 2025 | -0.026 | +0.016 | -0.011 | +0.011 | +0.010 | -0.002 | +0.004 |
| 2026 | -0.025 | +0.014 | -0.010 | +0.012 | +0.010 | +0.000 | +0.003 |
| 2027 | -0.026 | +0.013 | -0.010 | +0.013 | +0.012 | -0.000 | +0.005 |

## Diagnostic (mesure, pas un nouvel essai) : nos actions contre l'action moyenne de l'univers

Les IC des blocs mesuraient la capacite a battre l'action moyenne (poids egal), pas le SPY.

| Periode | Mois | Ecart annuel vs action moyenne | Sharpe de l'ecart | t-stat | Mois gagnants | IC moyen du score | t-stat IC |
|---|---|---|---|---|---|---|---|
| Dev 2010-2018 | 84 | -0.5% | -0.08 | -0.20 | 51% | -0.0061 | -0.49 |
| Hors echantillon 2019-2026 | 93 | +0.3% | 0.08 | 0.23 | 51% | +0.0287 | 2.71 |

| Annee | Nos actions | Action moyenne | SPY | Ecart vs action moyenne | Ecart action moyenne vs SPY |
|---|---|---|---|---|---|
| 2012 | +16.4% | +18.0% | +16.5% | -1.6% | +1.5% |
| 2013 | +20.0% | +24.5% | +21.4% | -4.6% | +3.1% |
| 2014 | +16.3% | +10.8% | +14.1% | +5.5% | -3.3% |
| 2015 | -7.0% | -7.1% | -0.9% | +0.1% | -6.3% |
| 2016 | +17.6% | +27.6% | +20.0% | -10.0% | +7.6% |
| 2017 | +24.8% | +23.8% | +26.3% | +1.1% | -2.5% |
| 2018 | -0.5% | -4.7% | -2.4% | +4.2% | -2.3% |
| 2019 | +13.0% | +13.8% | +21.4% | -0.8% | -7.6% |
| 2020 | +15.1% | +20.1% | +17.2% | -5.0% | +3.0% |
| 2021 | +16.2% | +9.9% | +23.2% | +6.2% | -13.2% |
| 2022 | +1.4% | +4.2% | -8.2% | -2.9% | +12.4% |
| 2023 | +13.5% | +5.9% | +20.6% | +7.6% | -14.7% |
| 2024 | +24.1% | +18.6% | +26.2% | +5.6% | -7.6% |
| 2025 | +12.0% | +14.6% | +16.3% | -2.6% | -1.7% |
| 2026 | +5.1% | +6.1% | +12.2% | -1.0% | -6.2% |

### IC de chaque bloc : dev 2010-2018 vs hors echantillon 2019-2026

| Bloc | IC dev | t dev | IC 2019-2026 | t 2019-2026 |
|---|---|---|---|---|
| C2_variation_actions_1an | -0.0226 | -2.45 | -0.0326 | -3.14 |
| C1_marge_brute_sur_actifs | +0.0208 | +1.92 | +0.0128 | +1.46 |
| B3_volatilite_12m | -0.0105 | -0.49 | -0.0143 | -0.67 |
| B2_proximite_plus_haut_52s | +0.0101 | +0.54 | +0.0269 | +1.43 |
| B1_momentum_12_1 | +0.0130 | +0.81 | +0.0182 | +1.08 |
| C6_accruals | -0.0126 | -1.54 | +0.0112 | +1.53 |
| A6_sma50_sup_sma200 | +0.0030 | +0.23 | +0.0149 | +1.07 |

## Limites

- Biais du survivant : entreprises radiees absentes (ni ticker SEC ni prix Yahoo). Resultats flattes.
- Donnees XBRL frames : derniere valeur deposee, une correction posterieure peut fuiter (decalage 90 j).
