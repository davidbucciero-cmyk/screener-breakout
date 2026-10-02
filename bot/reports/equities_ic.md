# Actions US > 2 Md$ : pouvoir predictif de chaque bloc seul (dev 2010-2018 uniquement)

IC = correlation de rang, chaque fin de mois, entre la feature et le rendement du mois suivant, sur toutes les actions de l'univers. Moyenne des IC mensuels et t-stat.
Avec 11 features testees, un |t| > 2.87 est requis pour ecarter le hasard.

## Couverture des donnees

- Tickers SEC (NYSE + Nasdaq, aujourd'hui) : 7675
- Tickers avec prix Yahoo : 7671
- Tickers sans prix (non telecharges ce run) : 0
- Actions dans l'univers > 2 Md$ par mois (moyenne dev) : 792
- Achats d'initiés extraits (toutes entreprises) : 603462
- Biais du survivant : les entreprises radiees n'ont plus de ticker SEC ni de prix Yahoo : absentes du panel

## IC par bloc

| Feature | Mois | IC moyen | t-stat | Mois IC > 0 | Annees meme signe | 2009 | 2010 | 2011 | 2012 | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C2_variation_actions_1an | 101 | -0.0527 | -6.17 | 26% | 8/9 |  | +0.016 | -0.047 | -0.041 | -0.060 | -0.074 | -0.074 | -0.058 | -0.064 | -0.036 |
| C1_marge_brute_sur_actifs | 113 | +0.0459 | +4.36 | 67% | 8/10 | +0.023 | -0.009 | +0.088 | +0.011 | -0.009 | +0.075 | +0.078 | +0.014 | +0.081 | +0.101 |
| B3_volatilite_12m | 113 | -0.0847 | -4.34 | 35% | 8/10 | +0.020 | +0.081 | -0.143 | -0.076 | -0.031 | -0.159 | -0.162 | -0.067 | -0.102 | -0.164 |
| B2_proximite_plus_haut_52s | 113 | +0.0686 | +4.01 | 71% | 8/10 | -0.148 | -0.036 | +0.092 | +0.069 | +0.074 | +0.135 | +0.138 | +0.021 | +0.107 | +0.131 |
| B1_momentum_12_1 | 113 | +0.0455 | +3.25 | 67% | 8/10 | -0.140 | +0.034 | +0.028 | +0.080 | +0.070 | +0.039 | +0.110 | -0.007 | +0.086 | +0.062 |
| C6_accruals | 113 | +0.0261 | +3.17 | 59% | 8/10 | +0.081 | -0.030 | -0.032 | +0.037 | +0.010 | +0.045 | +0.049 | +0.055 | +0.032 | +0.042 |
| A6_sma50_sup_sma200 | 113 | +0.0352 | +2.97 | 63% | 8/10 | -0.041 | -0.032 | +0.022 | +0.020 | +0.066 | +0.063 | +0.070 | +0.002 | +0.086 | +0.059 |
| A2_croissance_ca_1an | 105 | -0.0089 | -0.82 | 47% | 6/9 |  | -0.059 | -0.044 | -0.016 | -0.035 | +0.026 | +0.003 | -0.004 | +0.046 | -0.004 |
| A1_initie_montant_pct_cap | 113 | +0.0023 | +0.42 | 53% | 7/10 | +0.012 | +0.006 | +0.002 | +0.010 | +0.011 | -0.020 | -0.016 | +0.024 | +0.002 | -0.004 |
| A1_initie_acheteurs_90j | 113 | -0.0016 | -0.30 | 48% | 5/10 | +0.008 | +0.004 | -0.004 | +0.007 | +0.008 | -0.026 | -0.017 | +0.019 | -0.003 | -0.007 |
| B4_rendement_1m | 113 | +0.0011 | +0.09 | 57% | 5/10 | -0.029 | +0.002 | -0.004 | +0.024 | -0.018 | +0.017 | -0.004 | -0.030 | +0.010 | +0.030 |

## Achats groupes d'initiés (>= 2 initiés acheteurs sur 90 j)

- Mois mesures : 113
- Actions signalees par mois (moyenne) : 45.6
- Surperformance moyenne le mois suivant vs l'univers : -0.39%
- t-stat : -1.74
