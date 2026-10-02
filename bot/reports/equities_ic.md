# Actions US > 2 Md$ : pouvoir predictif de chaque bloc seul (dev 2010-2018 uniquement)

IC = correlation de rang, chaque fin de mois, entre la feature et le rendement du mois suivant, sur toutes les actions de l'univers. Moyenne des IC mensuels et t-stat.
Avec 11 features testees, un |t| > 2.87 est requis pour ecarter le hasard.

## Couverture des donnees

- Tickers SEC (NYSE + Nasdaq, aujourd'hui) : 7675
- Tickers avec prix Yahoo : 7672
- Tickers sans prix (non telecharges ce run) : 3
- Actions dans l'univers > 2 Md$ par mois (moyenne dev) : 684
- Achats d'initiés extraits (toutes entreprises) : 603462
- Biais du survivant : les entreprises radiees n'ont plus de ticker SEC ni de prix Yahoo : absentes du panel

## IC par bloc

| Feature | Mois | IC moyen | t-stat | Mois IC > 0 | Annees meme signe | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C2_variation_actions_1an | 101 | -0.0226 | -2.45 | 38% | 7/9 |  | +0.011 | -0.053 | -0.020 | -0.038 | -0.028 | -0.014 | -0.030 | -0.029 | +0.018 |
| C1_marge_brute_sur_actifs | 113 | +0.0208 | +1.92 | 55% | 6/10 | +0.038 | -0.007 | +0.069 | -0.004 | -0.016 | +0.047 | +0.039 | -0.050 | +0.044 | +0.059 |
| C6_accruals | 113 | -0.0126 | -1.54 | 42% | 8/10 | +0.061 | -0.034 | -0.037 | -0.007 | -0.035 | -0.019 | -0.005 | +0.023 | -0.017 | -0.020 |
| B1_momentum_12_1 | 113 | +0.0130 | +0.81 | 53% | 7/10 | -0.131 | +0.039 | +0.006 | +0.051 | +0.058 | +0.023 | +0.066 | -0.092 | +0.038 | -0.000 |
| A1_initie_montant_pct_cap | 113 | +0.0038 | +0.71 | 52% | 6/10 | +0.015 | +0.008 | +0.012 | +0.010 | +0.014 | -0.016 | -0.009 | +0.022 | -0.010 | -0.002 |
| B4_rendement_1m | 113 | -0.0077 | -0.59 | 51% | 7/10 | -0.021 | +0.004 | -0.024 | +0.015 | -0.002 | -0.001 | -0.016 | -0.041 | -0.008 | +0.013 |
| B2_proximite_plus_haut_52s | 113 | +0.0101 | +0.54 | 58% | 7/10 | -0.139 | -0.035 | +0.048 | +0.003 | +0.028 | +0.050 | +0.078 | -0.085 | +0.019 | +0.063 |
| A1_initie_acheteurs_90j | 113 | +0.0028 | +0.52 | 51% | 6/10 | +0.013 | +0.006 | +0.009 | +0.007 | +0.013 | -0.017 | -0.007 | +0.021 | -0.011 | -0.001 |
| B3_volatilite_12m | 113 | -0.0105 | -0.49 | 48% | 4/10 | +0.012 | +0.088 | -0.089 | +0.013 | +0.043 | -0.052 | -0.089 | +0.052 | +0.007 | -0.086 |
| A2_croissance_ca_1an | 105 | -0.0044 | -0.37 | 53% | 6/9 |  | -0.050 | -0.032 | -0.010 | -0.012 | +0.014 | +0.004 | -0.009 | +0.054 | -0.006 |
| A6_sma50_sup_sma200 | 113 | +0.0030 | +0.23 | 53% | 5/10 | -0.025 | -0.021 | -0.000 | -0.020 | +0.034 | +0.026 | +0.040 | -0.061 | +0.029 | +0.016 |

## Achats groupes d'initiés (>= 2 initiés acheteurs sur 90 j)

- Mois mesures : 113
- Actions signalees par mois (moyenne) : 30.1
- Surperformance moyenne le mois suivant vs l'univers : -0.20%
- t-stat : -1.11
