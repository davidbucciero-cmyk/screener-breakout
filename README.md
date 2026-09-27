# screener-breakout

## statarb — arbitrage statistique (facteurs PCA + Ornstein-Uhlenbeck)

Module independant du screener, dans `statarb/`. Implemente l'approche
d'arbitrage statistique cross-sectionnelle d'Avellaneda & Lee (2010) et
Velissaris (2010) : plutot que de chercher des paires de deux actions
(cointegration), chaque action est decomposee chaque jour en une exposition a
des facteurs de risque systematique (PCA glissante) et un residu
idiosyncratique, modelise comme un processus Ornstein-Uhlenbeck qui genere le
signal de trading. C'est la methode que la litterature quantitative a
largement adoptee en remplacement du pairs trading classique (voir aussi
Guijarro-Ordonez, Pelger & Zanotti 2024, "Deep Learning Statistical
Arbitrage", SSRN 3862004, qui documente le gain de performance de cette
famille d'approches face aux paires par cointegration).

Pipeline (`python3 statarb/run_statarb.py`) :
1. **Univers** (`scripts/universe.py`) : les ~500 tickers du S&P 500, recuperes
   dynamiquement depuis Wikipedia (repli sur un univers sectoriel restreint de
   secours si la page est inaccessible), 10 ans d'historique.
2. **Residus hors-echantillon** (`scripts/pca_factors.py`) : PCA glissante sur
   252 jours (5 facteurs) pour construire des eigenportefeuilles, puis
   regression glissante sur 60 jours pour estimer l'exposition de chaque
   action a ces facteurs. Le residu du jour J est calcule sans aucune
   information posterieure a J-1 (pas de biais de anticipation/look-ahead).
3. **S-scores** (`scripts/ou_signal.py`) : ajustement AR(1) glissant et
   vectorise (pandas rolling) du residu cumule sur une fenetre de 60 jours
   pour estimer la vitesse de retour a la moyenne (kappa), puis
   `s = (X - m) / sigma_eq`. Les actions dont la demi-vie depasse 30 jours
   sont ecartees (retour a la moyenne trop lent pour etre exploitable).
4. **Backtest** (`scripts/pca_backtest.py`) : entree si `s <= -1.25` (long
   residu) ou `s >= 1.25` (short residu), sortie si `|s| <= 0.75`, **stop de
   securite force a `|s| >= 3.5`** (divergence, relation factorielle rompue),
   si le signal disparait pendant qu'une position est ouverte, **si la perte
   depuis l'ouverture atteint -7%**, ou **apres 50 jours de detention**
   (regles de Caldeira & Moura, 2013). Le nombre de positions simultanees est
   **plafonne a 50** (`MAX_CONCURRENT_POSITIONS`) ; en cas de sur-demande,
   priorite aux signaux les plus extremes et a la reversion la plus rapide
   (score `|s|/demi-vie`). Allocation fixe de capital/50 par position
   (`TARGET_N_POSITIONS`) plutot qu'une renormalisation quotidienne (evite de
   "retrader" tout le portefeuille a chaque ouverture/fermeture ailleurs).
   Frais de transaction IBKR "Fixed Pricing" modelises (0.005 $/action, min
   1 $/ordre, plafond 1% du notionnel).
5. **Signaux du jour** (`scripts/pca_live_signals.py`) : s-score courant et
   action suggeree par titre.

Sorties dans `statarb/data/` : `prices.csv`, `pca_residuals.csv`,
`pca_s_scores.csv`, `pca_backtest_results.json`, `pca_portfolio_equity.csv`,
`pca_signals_today.csv`.

L'ancienne approche par paires/cointegration Engle-Granger reste disponible
dans `run_pairs_legacy.py` (univers sectoriel restreint de 44 titres, moins
performante d'apres la litterature, gardee pour comparaison).

### Resultats du backtest (S&P 500, 2016-2026, ~2140 jours out-of-sample)

Avec le plafond de 50 positions (priorite au signal le plus fort / demi-vie la
plus courte), le stop -7% et la limite de 50 jours de detention : **Sharpe
+0.71**, rendement cumule +29.8% sur ~8.5 ans, max drawdown **-10.2%**, cout
moyen 1.3 bps/jour. Nette amelioration par rapport a la version precedente
sans plafond de positions (Sharpe -0.63, drawdown -46%, ~115 positions actives
en moyenne pour une taille de slot dimensionnee pour 50 — le sur-trading
gonflait les couts bien plus que necessaire). Le plafond est quasi-toujours
atteint (50.0 positions actives en moyenne), signe qu'il y a plus de signaux
"valables" que de capital alloue pour les exploiter tous.

Piste testee mais abandonnee : regresser sur les prix cumules plutot que sur
les rendements (Skachkov, 2013) degrade le Sharpe sur ce jeu de donnees
(-0.96 contre -0.22 toutes choses egales par ailleurs) au lieu de l'ameliorer
comme dans son exemple mono-facteur — non retenu (voir le commentaire dans
`pca_factors.py`).

Rendement annualise encore modeste (~3.1%) pour une volatilite tres faible
(4.5% annualise) : le profil reste celui d'un edge reel mais fin, coherent
avec la litterature (Rad, Low & Faff 2015 documentent le meme phenomene sur
tout le marche US 1962-2014). Pistes suivantes pour augmenter le rendement
brut plutot que de continuer a limer les couts : enrichir le modele de
facteurs (IPCA conditionnel) ou ajouter un filtre momentum sectoriel
(Velissaris, 2010).

**Important** : les signaux generes ne sont pas des ordres. L'execution live
passe par des instructions IBKR en attente (non des ordres directs), a
valider manuellement avant envoi. Un residu qui retourne bien a sa moyenne
in-sample n'a aucune garantie de persistance out-of-sample (risque de rupture
structurelle — cf. Shleifer & Vishny, "The Limits of Arbitrage"). Ceci n'est
pas un conseil en investissement.
