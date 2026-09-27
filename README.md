# screener-breakout

## statarb — arbitrage statistique (pairs trading)

Module independant du screener, dans `statarb/`. Implemente une strategie
d'arbitrage statistique par cointegration (methode Engle-Granger en deux
etapes + demi-vie de retour a la moyenne via un AR(1) sur le spread), dans la
lignee de la litterature academique sur le pairs trading (Caldeira & Moura
2013, Gatev et al. 2006) et des travaux de Nicholas Burgess sur l'arbitrage
statistique (SSRN).

Pipeline (`python3 statarb/run_statarb.py`) :
1. **Univers** (`scripts/universe.py`) : ~44 actions US liquides, groupees par
   secteur (les paires ne sont testees qu'au sein d'un meme secteur).
2. **Cointegration** (`scripts/cointegration.py`) : test d'Engle-Granger sur
   la periode de formation (60% de l'historique), filtre sur p-value < 0.05
   et demi-vie entre 3 et 90 jours.
3. **Backtest out-of-sample** (`scripts/backtest.py`) : sur la periode de
   trading restante, entree quand `|z-score| >= 2`, sortie quand `|z-score|
   <= 0.5`, stop de securite si `|z-score| >= 4` (rupture de la relation).
4. **Signaux du jour** (`scripts/signals.py`) : z-score courant par paire et
   quantites suggerees (dimensionnement neutre au hedge ratio).

Sorties dans `statarb/data/` : `prices.csv`, `cointegrated_pairs.csv`,
`backtest_results.csv`, `portfolio_equity.csv`, `signals_today.csv`.

**Important** : les signaux generes ne sont pas des ordres. L'execution live
passe par des instructions IBKR en attente (non des ordres directs), a
valider manuellement avant envoi. Une relation de cointegration passee ne
garantit pas sa persistance (risque de rupture structurelle — cf. Shleifer &
Vishny, "The Limits of Arbitrage"). Ceci n'est pas un conseil en
investissement.
