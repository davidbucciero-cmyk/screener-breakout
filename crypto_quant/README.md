# crypto_quant

Systeme de trading quantitatif sur crypto, **inspire de la philosophie**
publique de Renaissance Technologies (fonds Medallion) : combiner plusieurs
signaux statistiques independants plutot qu'une seule idee, avec une
gestion du risque stricte et une validation rigoureuse (walk-forward).

**Ce que ce projet n'est pas** : une reproduction de Medallion. La strategie
reelle de Renaissance est un secret industriel absolu, jamais publie. Rien
ici ne s'en approche en termes de performance ou de sophistication - c'est
un systeme construit a partir de techniques quantitatives publiques et
documentees.

## Dashboard

`crypto_quant/dashboard/index.html` : dashboard HTML autonome (aucune
dependance externe hors CDN) qui affiche la performance walk-forward, le
regime actuel par actif, l'allocation dans le temps et la stabilite des
hyperparametres entre folds. Se regenere avec :

```bash
python -m crypto_quant.dashboard  # ecrit crypto_quant/dashboard/dashboard.json
```

Par defaut construit sur donnees synthetiques (aucun acces reseau requis) -
le dashboard l'indique explicitement en banniere. Pour un dashboard sur
donnees Kraken reelles, remplacer `price_data` dans `dashboard.py` par un
vrai historique `CCXTDataFeed.get_universe_history(...)`.

### Explorateur de parametres interactif

Le meme dashboard inclut un explorateur : 4 curseurs (paire EMA, seuil de
significativite OU, volatilite cible, cout de transaction) recalculent
instantanement les metriques a partir d'une grille pre-calculee de 1152
combinaisons (`dashboard_explore.py`, regenere avec
`python -m crypto_quant.dashboard_explore`).

Point de conception important : pour rester rapide (la grille complete se
calcule en quelques secondes plutot qu'en dizaines de minutes), le
coupe-circuit de drawdown est DESACTIVE dans cet explorateur - lui seul
introduit une dependance sequentielle (l'equity determine les haltes, qui
determinent l'equity suivante) qui empecherait de vectoriser le balayage.
Verifie par test (`test_dashboard_explore.py`) contre `run_backtest()` pour
garantir que les deux implementations restent d'accord.

Le dashboard affiche TOUJOURS deux chiffres cote a cote pour chaque
combinaison choisie : la performance "train" (ce qu'on optimise en
cherchant - va presque toujours s'ameliorer, meme sans edge reel) et la
performance hors-echantillon sur une periode jamais vue pendant la
recherche (le seul chiffre qui compte). Un nuage de points (train vs test
sur les 1152 combinaisons) rend visible, ou non, le surapprentissage.

## Etat d'avancement

- [x] Etape 1 - Donnees (`data.py`, `synthetic.py`, `config.py`)
- [x] Etape 2 - Signaux (Hurst, EMA, Ornstein-Uhlenbeck, EWMA vol)
- [x] Etape 3 - Combinaison des signaux (`portfolio.py`)
- [x] Etape 4 - Risque et sizing (`risk.py`)
- [x] Etape 5 - Backtest walk-forward (`backtest.py`, `metrics.py`)
- [x] Etape 6 - Execution (`execution.py`)
- [x] Etape 7 - Premier backtest reel contre Kraken (donnees vraies, pas synthetiques) - voir Etape 1 ci-dessous pour les resultats et les bugs trouves
- [x] Etape 7 bis - Historique profond via reconstruction depuis les trades bruts (contourne la limite ~720 bougies de l'OHLC Kraken)
- [x] Etape 8 - Tests de significativite statistique + demi-vie adaptative (inspire de Chan, "Algorithmic Trading") - `metrics.py`, `signals.py`
- [x] Etape 9 - Backtest sur 7 ans de donnees reelles (Binance.US) - voir Etape 9 bis pour le verdict corrige
- [x] Etape 9 bis - Le resultat negatif etait un artefact de turnover (1h), pas un edge negatif reel - confirme "pas d'edge" en 1d
- [x] Etape 10 - Lien theorie/code (momentum academique) : skip de periode recente (`ema_skip`) + activation de `top_n` - aucun des deux ne change le verdict OOS sur l'univers BTC/ETH ; `ema_skip` seul en walk-forward isole ameliore nettement le Sharpe OOS (0.53, toujours pas significatif, p=0.36)
- [x] Etape 11 - Fonction de reponse bornee de Baz et al. (2015) sur le signal EMA (`ema_bounded_response`) - neutre sur cet univers, jamais choisie sur train face au signal lineaire
- [x] Etape 12 - Signal de tendance multi-horizon (3 paires EMA, `ema_multi_horizon`) - nettement PIRE que le signal a un seul horizon sur cet univers, jamais choisi sur train
- [x] Etape 13 - Overlay de regime de marche (`market_regime_symbol`, croisement EMA BTC) - resultat INITIAL (Sharpe 0.99, p=0.086-0.106) trouve ensuite CONTAMINE par un bug de donnees, corrige et re-teste a l'etape 13 bis
- [x] Etape 13 bis - **BUG CRITIQUE CORRIGE** : trou de calendrier non detecte (suspension Binance.US juil. 2023-fev. 2025) contaminait tous les backtests Binance.US depuis l'etape 9bis ; verdict corrige pour l'overlay BTC : Sharpe OOS 0.59, p=0.43-0.45 - toujours pas significatif, et le gain qui semblait spectaculaire s'effondre largement une fois le bug corrige
- [x] Etape 14 - Test sur un univers elargi (11 actifs Binance.US, 2019-2023) - `top_n` et l'overlay BTC, qui semblaient utiles sur BTC/ETH seuls, deviennent NETTEMENT NEGATIFS en walk-forward OOS (Sharpe -0.78 a -1.33) sur cet univers plus large
- [x] Etape 15 - ADX comme filtre de tendance alternatif au Hurst (`trend_gate_source`) - bat nettement le Hurst en walk-forward sur BTC/ETH (Sharpe OOS 0.77 vs jamais choisi, p=0.33) - la piste la plus solide de la session en walk-forward a 2 configs
- [x] Etape 16 - Moteur a trades discrets (`discrete_trading.py` : stop ATR, breakeven, trailing, filtre de session) en parallele du backtester a poids continus - Sharpe train 1.74/p=0.013 mais Sharpe test 0.59/p=0.51 sur un simple split 60/40 (pas encore de walk-forward complet) ; le drawdown (~-6%) reste remarquablement stable entre train et test, contrairement au Sharpe
- [x] Etape 17 - Test hors crypto : l'or (25 ans, yfinance, `GC=F`) - avec les memes reglages qu'en crypto (jamais recalibres), le resultat OOS est quasi NUL (Sharpe 0.006, p=0.98/0.70), pas negatif - contredit l'hypothese initiale ("l'or, marche classique du suivi de tendance, devrait mieux marcher") a reglages inchanges
- [x] Etape 17 bis - Or recalibre aux fenetres CTA classiques (100-250 jours, pas 12-48 jours) - le resultat OOS passe de bruit pur (Sharpe 0.006, p=0.98) a directionnellement positif (Sharpe 0.30, p=0.24-0.30) : la mauvaise calibration etait bien le probleme, pas l'or en tant que tel - toujours pas significatif a 5%
- [x] Etape 18 - Bot de paper trading autonome sur l'or (`gold_paper_bot.py`) - execute une iteration quotidienne (config recalibree etape 17 bis), coupe-circuit inclus, PAPER TRADING UNIQUEMENT (`LiveExecutor(dry_run=True)`) ; tout l'etat (cash, positions, coupe-circuit) persiste en JSON commit/push pour survivre au conteneur ephemere
- [x] Etape 19 - Systeme de breakout Donchian + filtre MM200 (`donchian_system.py`, propose par l'utilisateur) teste en walk-forward (10 folds) sur les memes 25 ans d'or - Sharpe OOS 0.25, p=0.23-0.43 : meme ordre de grandeur que l'ADX/EMA de l'etape 17 bis, pas une amelioration nette, jamais significatif a 5%

## Etape 9 - Verdict decisif sur 7 ans de donnees reelles (Binance.US)

**Pourquoi changer de source de donnees** : l'endpoint OHLC public de Kraken
plafonne a ~720 bougies quel que soit `since` (etape 7), et la reconstruction
depuis les trades bruts (etape 7 bis), bien que fonctionnelle, prenait des
heures pour seulement 700 jours (densite de trades tres elevee sur BTC/USD
et ETH/USD). Verifie que Binance.US honore un `since` reellement profond sur
son endpoint OHLC natif (pas de reconstruction necessaire) : **47 500+
bougies horaires par actif (depuis septembre 2019, ~7 ans) recuperees en
~40 secondes au total**, plusieurs ordres de grandeur plus rapide. Prix
verifies coherents avec Kraken sur une fenetre commune (ecart <0.1%, spread
normal entre exchanges).

**Compromis assume** : ces donnees viennent de Binance.US, pas de Kraken
(l'exchange prevu pour l'execution reelle) - utilisees ici uniquement pour
la recherche/validation de la strategie, pas comme source live.

**Resultat du walk-forward sur BTC/USD + ETH/USD, 1h, sept. 2019 -> sept.
2026 (8 folds, tous valides)** :

| Metrique OOS | Valeur |
|---|---|
| Sharpe | -2.43 |
| CAGR | -69% |
| Max drawdown | -99.6% |
| Hit rate | 19.5% |
| `sharpe_significance` (etape 8) | t=-5.25, **p ≈ 0** (n=41 029) |

**Verdict initial (corrige plus bas - voir Etape 9 bis)** : contrairement
aux resultats precedents (echantillon trop petit pour trancher), celui-ci
semblait **statistiquement decisif** - et dans le mauvais sens. Meme config
(ema=24/96, ou_window=150) choisie a CHAQUE fold (stable, pas de
flip-flop), mais Sharpe train negatif dans les 8 folds.

## Etape 10 - Lien theorie/code (momentum academique) : skip de periode recente et top_n

**Contexte** : comparaison de `ema_trend_signal` avec le momentum academique
classique (Jegadeesh-Titman 1993, et la version "retail" de Foltice &
Langer 2015 identifiee dans la recherche SSRN). Deux ecarts identifies :
(1) le signal EMA continu n'exclut jamais la periode la plus recente de son
calcul, contrairement au "12-1 mois" academique (qui exclut le mois le plus
recent de la periode de formation pour eviter la contamination par le
retournement a tres court terme - exactement le chevauchement avec le
domaine du signal OU mean-reversion qui a cause le bug de turnover de
l'etape 9/9bis) ; (2) `top_n` existait deja dans `BacktestConfig`/
`portfolio.py` mais n'avait jamais ete fixe a une valeur non-`None`.

**Implemente** :
- `signals.ema_trend_signal(..., skip=0)` : les EMA rapide/lente sont
  calculees sur `close.shift(skip)` plutot que sur `close`. Cable dans
  `BacktestConfig.ema_skip` (defaut 0, retro-compatible).
- `top_n` teste pour la premiere fois sur donnees reelles (`top_n=1`, le
  seul choix sense avec 2 actifs : rotation BTC/ETH plutot que detention
  simultanee).

**Resultats sur le cache Binance.US (daily, 2019-2026, meme univers
BTC/USD + ETH/USD qu'aux etapes 9/9bis)** :

| Test | Sharpe | CAGR |
|---|---|---|
| Plein historique, defaut (`ema_skip=0`, `top_n=None`) | 0.392 | 7.9% |
| Plein historique, `ema_skip=1` | 0.426 | 9.5% |
| Plein historique, `ema_skip=2` | 0.507 | 13.6% |
| Plein historique, `ema_skip=3` | **0.536** | **15.1%** |
| Plein historique, `ema_skip=5` | 0.501 | 13.2% |
| Plein historique, `top_n=1` (vs `top_n=None` ci-dessus) | 0.364 | 6.5% |

`ema_skip` ameliore le Sharpe en-sample sur tout l'historique (0.39 -> 0.54
a skip=3j) ; `top_n=1` le degrade legerement (0.39 -> 0.36). Logique pour
`top_n` : avec seulement 2 actifs assez correles (BTC/ETH), concentrer sur
le meilleur score sacrifie la diversification sans vraiment gagner en
selectivite - la litterature retail momentum (Foltice & Langer) suppose un
univers de plusieurs dizaines de titres avec une vraie dispersion
cross-sectionnelle a exploiter, pas 2 actifs.

**Mais en walk-forward (le seul chiffre qui compte, cf. discipline
anti-data-snooping de l'etape 5)**, ajouter `top_n=1` et `ema_skip` comme
candidats dans la grille de selection degrade le resultat OOS par rapport a
la reference de l'etape 9bis :

| | Grille etape 9bis (5 configs) | Grille etendue (+6 configs top_n/ema_skip) |
|---|---|---|
| Sharpe OOS | 0.036 | -0.005 |
| p-value | 0.95 | 0.99 |
| Folds valides | 6/6 | 6/6 |

Le walk-forward choisit `top_n=1, ema_skip=2` sur train dans 4 des 6 folds
(Sharpe train 0.7 a 1.7 - l'air prometteur en-sample), mais l'OOS ne
s'ameliore pas, il empire legerement. **Plus de candidats dans la grille =
plus d'occasions de choisir, par fold, une config qui a l'air bonne sur
train sans generaliser** - le meme phenomene de surapprentissage que celui
deja diagnostique a l'etape 9bis, juste avec une grille plus large cette
fois.

**Verdict** : les deux ajustements sont maintenant disponibles et testes
(89/89 tests unitaires passent, aucune regression), mais ni l'un ni l'autre
ne change la conclusion de fond sur cet univers a 2 actifs - aucune
configuration testee a ce jour n'a un edge OOS statistiquement distinguable
de zero (p toujours > 0.9). Le gain en-sample de `ema_skip` (interessant,
mais mesure sur les 7 memes annees qui servent aussi a le choisir) merite
un test walk-forward isole (pas noye dans une grille a 11 candidats) avant
d'en tirer une conclusion ; `top_n` restera probablement de peu d'utilite
tant que l'univers se limite a BTC/ETH - son interet academique (Foltice &
Langer) suppose un univers bien plus large pour exploiter une vraie
dispersion cross-sectionnelle entre actifs.

**Suite : `ema_skip` teste seul en walk-forward isole** (grille ne variant
QUE `ema_skip` ∈ {0,1,2,3,5}, tout le reste au defaut - pas melange a
`top_n` ni a d'autres variantes ema/ou_window cette fois) :

| | Reference etape 9bis (5 configs, sans ema_skip) | `ema_skip` seul (5 configs, skip uniquement) |
|---|---|---|
| Sharpe OOS | 0.036 | **0.530** |
| p-value | 0.95 | **0.358** |
| CAGR OOS | -7.9% | **+14.7%** |
| Folds valides | 6/6 | 6/6 |

Nettement meilleur que la reference, et le choix n'a pas l'air de pur bruit
de selection : `ema_skip=3` est choisi dans 5 des 6 folds (le fold 0 choisit
`skip=2`, tres proche) - un signal stable a travers des folds qui couvrent
des regimes tres differents (bull 2020-21, bear 2022, range 2023-25),
contrairement aux choix disperses de la grille etendue ci-dessus. Cela dit,
**p=0.358 reste loin du seuil de 5%** - le resultat n'est pas encore
statistiquement distinguable du bruit, juste beaucoup moins mauvais que
tout ce qui a ete teste jusqu'ici sur cet univers. A ce stade, c'est la
piste la plus prometteuse trouvee sur BTC/ETH, mais "plus prometteuse" ne
veut pas dire "prouvee" - un edge reel donnerait un p-value net sous 0.05,
pas 0.36.

## Etape 11 - Fonction de reponse bornee de Baz et al. (2015)

**Contexte** : lecture de Rohrbach, Suremann & Osterrieder (2017, SSRN),
qui reprennent la methode de production de Baz et al. (2015, Man AHL) pour
les signaux de tendance FX/crypto. Au lieu d'utiliser le z-score de tendance
lineairement (ce que fait `ema_trend_signal`), ils appliquent une fonction
de reponse bornee :

    u(z) = z * exp(-z^2/4) / (sqrt(2) * exp(-1/2))

Particularite importante (pas une saturation classique type sigmoide) :
`u` atteint son maximum global exactement en `z=sqrt(2)` puis DECROIT vers
0 pour `|z|` plus grand - un z-score extreme est traite comme moins fiable
(souvent un artefact de volatilite anormalement basse au denominateur de
la normalisation) plutot que comme un signal plus fort.

**Implemente** : `signals.baz_response(z)`, cable via
`BacktestConfig.ema_bounded_response` (applique a `ema_trend` si `True`).

**Teste sur le meme cache Binance.US (daily, BTC/USD + ETH/USD, 2019-2026)** :

| Test | Sharpe | p-value | CAGR |
|---|---|---|---|
| Plein historique, lineaire (defaut) | 0.392 | - | 7.9% |
| Plein historique, reponse bornee | 0.392 | - | 7.8% |
| Walk-forward isole (lineaire vs borne, rien d'autre ne varie) | 0.392 | 0.496 | 8.0% |
| Walk-forward combine (`ema_skip` x reponse bornee, 4 configs) | 0.539 | 0.350 | 15.1% |

**Verdict : effet neutre sur cet univers.** En walk-forward isole (seule
variable = reponse bornee, tout le reste identique), le selecteur choisit
`ema_bounded_response=False` (lineaire) dans les 6/6 folds - la reponse
bornee n'apporte jamais d'avantage mesurable sur le train. En-sample, les
deux versions sont quasi identiques (Sharpe 0.392 vs 0.392) : avec les
fenetres EMA actuelles (`12/48`) et la normalisation par `ewma_vol`, les
z-scores du signal de tendance semblent rarement assez extremes pour que
la decroissance au-dela de `z=sqrt(2)` change grand-chose. Le resultat
"combine" (0.539, p=0.350) n'est pas meilleur que `ema_skip=3` seul
(0.530, p=0.358, etape 10) aux erreurs d'estimation pres - la reponse
bornee ne semble rien ajouter au-dela de ce que `ema_skip` apportait deja.

A noter : le papier original combine 3 horizons EMA differents avant
d'appliquer la fonction de reponse (moyenne ponderee de 3 signaux a
correlation ~85% entre eux), alors qu'ici elle est appliquee a un seul
horizon (`ema_fast`/`ema_slow`). Il est possible que l'effet de la
fonction de reponse ne se manifeste vraiment qu'en presence de plusieurs
horizons combines (elle sert alors aussi a eviter qu'un horizon bruite
ne domine le melange) - hors-scope pour l'instant, mais note pour une
suite eventuelle.

## Etape 12 - Signal de tendance multi-horizon (3 paires EMA, Baz et al. 2015)

**Contexte** : suite a l'etape 11, hypothese que l'effet de la fonction de
reponse bornee ne se manifeste qu'en combinant plusieurs horizons EMA
(comme dans la methode complete de Baz et al. 2015 / Rohrbach et al. 2017),
pas sur un seul horizon. Implementation fidele cette fois : 3 paires EMA
(8,24)/(16,48)/(32,96), chacune normalisee en cascade (vol du PRIX sur une
fenetre fixe de 63 jours, PUIS vol du SIGNAL lui-meme sur sa propre
fenetre glissante de 252 jours), moyennees a poids egaux - voir
`signals.multi_horizon_trend_signal`.

**Teste sur le meme cache Binance.US (daily, BTC/USD + ETH/USD, 2019-2026)** :

| Test | Sharpe | CAGR |
|---|---|---|
| Plein historique, signal simple (`ema_fast=12/ema_slow=48`) | 0.392 | +7.9% |
| Plein historique, multi-horizon | **0.096** | **-4.7%** |
| Plein historique, multi-horizon + reponse bornee | 0.267 | +2.5% |
| Walk-forward isole (simple vs multi, rien d'autre ne varie) - OOS | 0.392 | +8.0% |

**Verdict : nettement PIRE que le signal a un seul horizon sur cet
univers**, pas juste neutre comme la reponse bornee seule (etape 11). En
walk-forward isole, le selecteur choisit le signal a un seul horizon dans
les 6/6 folds - le multi-horizon n'est jamais competitif, meme sur train.
Dans une grille combinee (multi-horizon x reponse bornee x `ema_skip`,
6 configs), le meilleur reste exactement la config de l'etape 10
(signal simple + `ema_skip=3`, Sharpe OOS 0.538, coherent avec le 0.530
deja trouve) - le multi-horizon n'apporte rien, meme combine aux autres
ajustements.

Hypotheses sur cet echec (non testees individuellement, a prendre comme
pistes plutot que diagnostic confirme) :
- **Cout du warm-up** : la cascade des deux normalisations consomme a elle
  seule ~315 jours avant tout signal exploitable, soit environ 16% des
  ~1985 jours de donnees disponibles - une fraction bien plus grande de
  l'historique "perdue" que pour le signal simple (`ema_slow=48`).
- **Horizons trop longs pour ce marche** : les paires (32,96) capturent des
  tendances sur plusieurs mois. Or l'etape 10 a deja montre qu'exclure la
  periode tres recente (`ema_skip`) aide, ce qui suggere un marche ou les
  tendances utiles sont plutot courtes et le bruit de retournement
  frequent - une methode calibree a l'origine sur le FX (tendances plus
  lentes, marches plus liquides) ne se transpose pas necessairement telle
  quelle aux cryptos.
- **Univers trop petit** : la methode originale visait un portefeuille
  cross-sectionnel de plusieurs dizaines de devises/cryptos ; sur 2 actifs
  seulement, la perte de reactivite du multi-horizon n'est compensee par
  aucune diversification supplementaire.

Le code reste disponible et teste (`ema_multi_horizon`, 96/96 tests
passent) pour d'eventuels tests futurs sur un univers plus large ou
d'autres parametres d'horizon, mais n'est PAS recommande sur la
configuration actuelle.

## Etape 13 - Overlay de regime de marche (Starkiller Capital, 2023)

> **CORRECTION (etape 13 bis)** : les chiffres OOS de cette section
> (Sharpe 0.99, p=0.086-0.106) etaient CONTAMINES par un bug de donnees
> decouvert juste apres - un trou de calendrier de 586 jours (suspension du
> trading USD sur Binance.US) traite comme le rendement d'une seule bougie.
> Corrige et re-teste a l'etape 13 bis : le verdict change nettement
> (Sharpe OOS 0.59, p=0.43-0.45 - plus proche du bruit). Section conservee
> pour la tracabilite methodologique, mais NE PAS CITER ces chiffres comme
> resultat final - se referer a l'etape 13 bis.

**Contexte** : Drogen, Hoffstein & Otte (Starkiller Capital, SSRN 4322637)
montrent que superposer un filtre de regime base sur BTC (cash integral
quand BTC est en tendance baissiere) au-dessus d'un portefeuille de
momentum cross-sectionnel fait passer leur rendement annualise de 37.8% a
93.3% et leur drawdown max de 75% a 45%. Contrairement aux ajustements
precedents (par-actif), c'est un gate au niveau du PORTEFEUILLE ENTIER,
base sur un seul actif de reference.

**Implemente** : `signals.market_regime_signal(close, fast=5, slow=50)`
(booleen risk-on/risk-off, croisement EMA simple non normalise), cable via
`BacktestConfig.market_regime_symbol` - force tout le portefeuille en cash
immediatement (meme logique que le coupe-circuit de drawdown) quand
l'actif de reference est risk-off, quels que soient les scores par actif.

**Teste sur le meme cache Binance.US (daily, BTC/USD + ETH/USD, 2019-2026),
BTC/USD comme actif de reference** :

| Test | Sharpe | p-value (gaussien) | p-value (permutation) | CAGR | Max DD |
|---|---|---|---|---|---|
| Plein historique, sans overlay | 0.392 | - | - | +7.9% | -71.0% |
| Plein historique, overlay BTC | **0.805** | - | - | **+25.7%** | **-41.0%** |
| Walk-forward isole (overlay vs rien), OOS | **0.988** | **0.086** | **0.106** | **+32.6%** | -40.7% |
| Walk-forward combine (overlay x `ema_skip`), OOS | 0.988 | 0.086 | 0.106 | +32.6% | -40.7% |

**C'est le meilleur resultat OOS de toute la session** - et de loin
(p=0.086-0.106 contre p=0.35-0.95 pour toutes les pistes precedentes). Le
selecteur walk-forward choisit l'overlay dans 6/6 folds, jamais l'inverse.
Combine avec `ema_skip` (etape 10), le selecteur choisit systematiquement
`ema_skip=0` : une fois l'overlay actif, `ema_skip` n'apporte plus rien -
les deux captent en partie le meme effet (eviter d'etre expose pendant les
baisses), et l'overlay le fait plus directement. Verifie aussi avec le
test de permutation (pas seulement le test gaussien, cf. etape 8) pour
tenir compte des queues epaisses de la crypto documentees par Han, Kang &
Ryu (2026, lus a la meme session) : les deux tests convergent raisonnablement
(0.086 vs 0.106), contrairement aux tests d'Arefev (2026) qui divergeaient
fortement entre eux sur le momentum cross-sectionnel pur.

**Nuances importantes avant de crier victoire** :
- **p reste au-dessus de 0.05.** A 0.086-0.106, ce n'est significatif qu'au
  seuil (plus laxiste) de 10%, pas au seuil conventionnel de 5%. Encourageant,
  pas prouve.
- **Le portefeuille est en cash 73% du temps.** Ce n'est plus vraiment une
  strategie de "trading actif" mais un market-timing binaire tres
  concentre - la nature du risque pris a profondement change (peu de
  periodes actives, chacune portant plus de poids sur le resultat final).
- **Risque de concentration sur un seul evenement** : le Sharpe train
  decroit progressivement d'un fold a l'autre (1.63 -> 1.90 -> 1.71 -> 1.32
  -> 1.24 -> 0.90) a mesure que l'historique s'etend au-dela du bear market
  2022 (Terra/Luna, FTX) - une partie significative du gain pourrait venir
  d'avoir evite CE crash particulier plutot que d'un edge repete et
  independant a travers plusieurs cycles. Un filtre EMA(5,50) binaire sur
  un seul actif reste, par construction, un pari sur peu d'evenements
  extremes distincts sur seulement 7 ans de donnees.
- Hit rate tres bas (13.5%) : attendu avec 73% de cash (bougies a poids nul
  comptees comme non gagnantes), pas un signal d'alarme en soi, mais a
  interpreter avec la meme prudence que le reste.

**Verdict (avant correction - voir etape 13 bis)** : la piste la plus
prometteuse trouvee a ce jour sur cet univers, cohérente avec la recherche
recue a la meme session (Starkiller, Han/Kang/Ryu) qui identifie
systematiquement la PROTECTION A LA BAISSE (pas l'alpha en bull market)
comme la seule forme d'edge momentum qui survit a un examen rigoureux en
crypto. Pas encore statistiquement prouve (p>0.05), et la dependance
possible a un seul gros evenement de marche appelle a la prudence plutot
qu'a la conclusion definitive.

## Etape 13 bis - Bug critique corrige : trou de calendrier Binance.US

**Decouverte** (en preparant l'univers elargi demande juste apres l'etape
13) : Binance.US a suspendu le trading USD du **14 juillet 2023** au
**19 fevrier 2025** (procès SEC de juin 2023, perte des partenaires
bancaires) - un trou de **586 jours sans aucune bougie**, partage par
TOUS les actifs USD de l'exchange (verifie sur les 13 paires testees pour
l'univers elargi, pas seulement BTC/ETH).

`run_backtest` iterant PAR POSITION (t -> t+1), jamais par date (cf. sa
docstring), ce trou etait traite comme le rendement d'une SEULE bougie :

```
BTC/USD : 2023-07-14 (25 073$) -> 2025-02-19 (96 584$) => "rendement" d'une bougie : +285%
ETH/USD : 2023-07-14 (1 595$)  -> 2025-02-19 (2 725$)  => "rendement" d'une bougie : +71%
```

Cet artefact a contamine silencieusement TOUS les backtests Binance.US
depuis l'etape 9bis (EMA, vol glissante, Hurst et P&L simule autour de ce
point) - y compris le "meilleur resultat de la session" de l'etape 13.

**Corrige** :
- `data.largest_contiguous_segment(price_data, max_gap_multiple=3.0)` :
  detecte un trou de calendrier commun a tous les actifs et ne garde que
  le plus grand segment continu.
- `backtest._assert_no_calendar_gaps`, appele dans `_align_universe` sur
  le calendrier des PRIX BRUTS (avant tout calcul de signal - important :
  verifier sur l'index APRES calcul des signaux aurait aussi declenche sur
  des NaN de signal parfaitement legitimes, ex. vol glissante nulle sur un
  prix plat, qui ne sont PAS des trous de marche reels). Leve une erreur
  explicite plutot que de laisser le backtester produire un resultat
  silencieusement fausse - 5 nouveaux tests, 105/105 passent.

**Re-test de l'etape 13 avec les donnees corrigees** (plus grand segment
continu disponible : 2019-09-18 -> 2023-07-14, 1396 bougies - on perd la
reprise 2024-2025, mais on garde COVID 2020, le bull 2021 et le bear
2022) :

| Test | Sharpe | p (gaussien) | p (permutation) | CAGR | Max DD |
|---|---|---|---|---|---|
| Plein historique corrige, sans overlay | 0.527 | - | - | +14.6% | -57.4% |
| Plein historique corrige, overlay BTC | 1.251 | - | - | +49.8% | -26.5% |
| Walk-forward corrige, sans overlay (grille etape 9bis) OOS | 0.292 | 0.721 | - | +2.4% | -51.3% |
| **Walk-forward corrige, overlay BTC seul, OOS** | **0.588** | **0.452** | **0.430** | **+16.8%** | **-29.5%** |

**Le verdict change nettement.** L'overlay reste directionnellement utile
(meilleur Sharpe, bien meilleur drawdown, choisi dans 6/6 folds face a
"pas d'overlay") et l'amelioration en-sample reste substantielle (Sharpe
0.53 -> 1.25). Mais l'amelioration OOS qui semblait spectaculaire
(Sharpe 0.99, p=0.086-0.106 - etape 13) s'effondre une fois le bug
corrige : **Sharpe OOS 0.59, p=0.43-0.45** sur les deux tests de
significativite - nettement plus proche du bruit que ce qu'on croyait.
Le resultat precedent etait donc en bonne partie un artefact du trou de
calendrier (le fold 3 de l'etape 13, 2022-10-24 -> 2025-03-09, contenait
exactement la ligne fictive +285%/+71% - un fold entier gonfle par une
seule ligne de donnees fausse).

**A retenir methodologiquement** (deuxieme occurrence du meme principe que
l'etape 9bis) : un resultat qui semble "trop beau" merite d'etre
investigue avant d'etre publie comme une decouverte - ici, en construisant
l'univers elargi demande par l'utilisateur, la simple verification des
dates de debut/fin par actif a suffi a reveler le trou. Le fait que les
10 autres actifs testes pour l'univers elargi (LTC, BCH, XRP, ADA, ETC,
XLM, ZEC, DASH, NEO, ZRX, BAT) partagent TOUS le meme trou (ou pire,
certains ont carrement disparu de Binance.US en juin 2023 - DASH, NEO,
ZRX, BAT n'ont plus de donnees apres cette date) confirme que c'est un
evenement reel de l'exchange, pas un artefact de notre pipeline de fetch -
mais notre pipeline de BACKTEST, lui, avait un vrai bug en ne le
detectant pas.

## Etape 14 - Test sur un univers elargi (11 actifs)

**Contexte** : demande de tester `top_n` et l'overlay BTC sur un univers
plus grand que BTC/ETH - ces deux mecanismes n'ont de sens que si
l'univers offre une vraie dispersion cross-sectionnelle (cf. etape 10).

**Univers construit** : parmi les paires USD de Binance.US avec un long
historique, 11 actifs partagent une fenetre continue SANS AUCUN TROU (verifie
bougie par bougie) : BTC, ETH, LTC, BCH, ADA, ETC, XLM, DASH, NEO, ZRX, BAT.
XRP et ZEC ont ete exclus (gaps internes propres, suspension/relisting a
des dates differentes du reste). La fenetre commune est 2019-11-01 ->
2023-06-27 (1335 bougies, ~3.65 ans) - bornee par NEO (demarre le plus
tard) et par DASH/NEO/ZRX/BAT (delistes de Binance.US en juin 2023, avant
meme la suspension generale de juillet 2023 qui affecte BTC/ETH).

**A noter sur la composition de cet univers** : 4 des 11 actifs ont ete
delistes de Binance.US moins de 4 ans apres le debut de la fenetre - un
signal de risque de survie qui n'est pas represente dans le backtest
(aucun mecanisme de gestion du risque de delisting/illiquidite dans le
pipeline actuel). Cet univers n'est pas un choix "neutre" de 11 grandes
cryptomonnaies, c'est simplement ce qui avait un historique Binance.US
suffisamment long et continu.

**Resultats (walk-forward, le seul chiffre qui compte)** :

| Test | Sharpe OOS | p-value | CAGR OOS |
|---|---|---|---|
| `top_n` seul (grille {None,1,2,3,5,8}) | **-0.78** | 0.34 | **-53.8%** |
| Overlay BTC seul | **-1.20** | 0.14 | **-47.8%** |
| Combine (`top_n` x overlay) | **-1.33** | 0.11 (gaussien) / 0.96 (permutation) | **-50.7%** |

**Les deux mecanismes qui semblaient utiles sur BTC/ETH (etapes 10 et 13
bis) deviennent NETTEMENT NEGATIFS sur cet univers elargi** - pas juste
"pas d'edge", mais un Sharpe negatif substantiel. Signature classique de
surapprentissage, et meme plus marquee qu'a l'etape 9bis : le Sharpe TRAIN
reste positif et souvent superieur a 1 dans presque tous les folds (ex.
overlay : 0.52 a 1.64) alors que l'OOS s'effondre a -0.78/-1.33 - la
selection sur train choisit systematiquement `top_n=1` et l'overlay
(6/6 folds a chaque fois), avec une confiance apparente forte, pour un
resultat OOS deteriore plutot que simplement bruite.

**Hypothese sur la cause** : contrairement a BTC/ETH (deux actifs matures,
fortement correles, ou concentrer sur "le meilleur des deux" ou couper sur
BTC a un effet limite), cet univers mele des altcoins de capitalisation
bien plus faible (DASH, NEO, ZRX, BAT, ETC...) dont la dynamique recente
(narratifs, pump-and-dump, risque de delisting) semble inverser le signe
du signal entre train et test - `top_n=1` concentre sur "le meilleur
performer du mois precedent", qui dans un univers d'altcoins volatils
capture probablement plus le sommet d'un pump transitoire (suivi d'un
retournement) que la persistance de tendance recherchee par le momentum.
C'est une hypothese, pas un diagnostic confirme (contrairement a l'etape
9bis ou la cause avait ete isolee precisement).

**Verdict** : elargir l'univers n'a pas aide - au contraire, il a
transforme un signal "pas d'edge detectable" (BTC/ETH) en un signal
"edge negatif substantiel" en walk-forward. Ni `top_n` ni l'overlay BTC ne
sont recommandes sur cet univers de 11 actifs tel que construit. Le
probleme n'est pas le manque de dispersion cross-sectionnelle (cet univers
en a, largement) mais plutot que cette dispersion vient d'actifs dont le
comportement (et le risque de survie) est trop different de BTC/ETH pour
que les mecanismes calibres sur ces deux-la se transposent utilement.

## Etape 15 - ADX comme filtre de tendance alternatif au Hurst

**Contexte** : proposition utilisateur d'un filtre anti-ranging base sur
l'ADX (Average Directional Index, Wilder 1978). Plutot que de l'ajouter
en confiance, il est cable comme ALTERNATIVE testable au trend_gate
derive du Hurst (`BacktestConfig.trend_gate_source`), pour comparer
lequel generalise le mieux en walk-forward - meme discipline que pour
toutes les autres pistes de la session.

**Implemente** : `signals.adx(high, low, close, period=14)` (lissage de
Wilder approxime par `ewm(alpha=1/period)`) + `signals.adx_trend_gate`
(conversion en gate [0,1]). Ne remplace que `trend_gate` (force de la
tendance) - `meanrev_gate` reste toujours derive du Hurst, l'ADX n'ayant
pas d'equivalent "retour a la moyenne".

**Teste sur le cache Binance.US corrige (BTC/USD + ETH/USD, 2019-2023)** :

| Test | Sharpe | p-value | CAGR |
|---|---|---|---|
| Plein historique, Hurst (defaut) | 0.527 | - | +14.6% |
| Plein historique, ADX | **1.134** | - | **+61.4%** |
| Walk-forward isole (Hurst vs ADX), OOS | - (jamais choisi) | - | - |
| Walk-forward isole, ADX | **0.769** | **0.326** | +31.1% |

**L'ADX bat nettement le Hurst** : choisi dans 6/6 folds du walk-forward,
jamais l'inverse. C'est le meilleur resultat "mecanisme unique" trouve sur
BTC/ETH cette session (avant le moteur a trades discrets de l'etape 16).
Combine avec l'overlay BTC (etape 13 bis), le resultat se DEGRADE
legerement (Sharpe 0.582, p=0.457) : l'ADX filtre deja bien les phases
sans tendance, l'overlay devient redondant voire legerement contre-
productif par-dessus.

**Verdict** : toujours pas significatif a 5% (p=0.326), mais clairement la
piste la plus solide identifiee sur cet univers a ce jour via un
changement de mecanisme unique.

## Etape 16 - Moteur a trades discrets (stop ATR / breakeven / trailing / session)

**Contexte** : demande de faire evoluer le projet vers un "bot autonome"
a trades discrets (entree/stop-loss), plutot que le modele a poids
continus rebalances en continu utilise jusqu'ici. Construit comme moteur
PARALLELE (`discrete_trading.py`), pas un remplacement - les deux
partagent les memes briques statistiques (Hurst/ADX, EMA trend+skip, OU
mean-reversion, overlay de regime BTC).

**Mecanique** : chaque actif est soit FLAT soit dans un TRADE UNIQUE
(long-only). Stop initial = `entry_price - atr_stop_multiple * ATR`
(`risk.atr`, etape 4 - jamais cable jusqu'ici faute d'un moteur a trades
discrets). Breakeven automatique des que le gain latent atteint
`breakeven_r_multiple * risque_initial` (stop -> prix d'entree). Trailing
stop ATR apres breakeven (`plus_haut_depuis_entree - trailing_atr_multiple
* ATR`, ne redescend jamais). Sizing par risque fixe par trade
(`risk_per_trade` / distance de stop en %), different du vol-targeting du
modele a poids continus. Filtre de session horaire optionnel : mecanisme
fonctionnel et teste, mais **sans effet reel sur des bougies
journalieres** (un seul horodatage par jour) - ne devient un vrai filtre
que sur des donnees intraday.

**Bugs trouves et corriges pendant le developpement** (le processus de
test a lui-meme ete utile ici) :
- Fuite de cash a poids plein (weight=1.0) : le cout de transaction preleve
  EN PLUS d'une notional deja egale a 100% de l'equity rendait `cash`
  legerement negatif, gonflant l'exposition enregistree au-dessus du
  plafond `max_position_fraction` - corrige en dimensionnant la notional
  pour reserver le cout.
- L'exposition deja engagee (`committed`) lors de nouvelles entrees doit
  etre mesuree en mark-to-market (valeur courante des positions), pas via
  le poids fige au moment de l'entree d'une position deja ouverte.
- Plusieurs scenarios de test construits avec un prix DETERMINISTE sans
  bruit produisaient des allers-retours signal/re-entree artificiels
  (`ou_meanreversion_signal` detecte une "significativite" numerique sur
  un residu quasi nul) - corriges en testant systematiquement sur un prix
  bruite. Ce phenomene revele un risque reel a garder en tete : reutiliser
  `composite_score` (concu pour un rebalancement continu) comme simple
  declencheur d'entree/sortie discrete peut provoquer des sorties/
  reentrees frequentes meme en tendance (whipsaw).

**Teste sur le cache Binance.US corrige, `trend_gate_source="adx"`
(la config la plus prometteuse de l'etape 15), pas encore de walk-forward
complet pour ce moteur (seulement un split train/test 60/40 simple, aucun
reglage choisi sur le train) :**

| | Plein historique (en-sample) | Train (60%) | Test (40%, jamais vu) |
|---|---|---|---|
| Sharpe | 1.302 | 1.744 | **0.593** |
| p-value (gaussien) | 0.014 | 0.013 | **0.506** |
| p-value (permutation) | - | 0.129 | 0.102 |
| Max drawdown | -6.5% | -6.5% | **-5.8%** |
| CAGR | +13.2% | +20.7% | +4.9% |

**Meme signature de surapprentissage que le reste de la session** : Sharpe
et p-value se degradent nettement du train au test (1.74/p=0.013 ->
0.59/p=0.51) - la significativite en-sample ne tenait pas. Mais une
caracteristique reste stable et notable : **le drawdown maximum reste
tres bas des les deux segments (-6.5% puis -5.8%)**, bien en-deca de tout
ce qu'on a vu avec le modele a poids continus (typiquement -30% a -70%).
C'est une propriete STRUCTURELLE du stop-loss dur (pas un artefact
statistique comme le Sharpe) : elle ne depend pas de la precision du
signal d'entree, seulement de la discipline de sortie. Le test de
permutation, plus conservateur que le test gaussien sur les DEUX segments
(p~0.10-0.13), confirme une fois de plus l'utilite d'avoir les deux tests
(etape 8).

**Verdict** : le moteur fonctionne (122/122 tests passent, bugs reels
trouves et corriges par le processus de test), mais comme pour toutes les
autres pistes de cette session, **le Sharpe et sa significativite ne
resistent pas a un vrai decoupage train/test** - seul le controle du
drawdown (via le stop-loss) est une amelioration structurelle averee,
independamment de toute question de significativite statistique du
rendement. Pas encore de walk-forward complet (grille de configs +
selection sur train uniquement) pour ce moteur - a construire si cette
piste doit etre creusee plus avant.

## Etape 17 - Test hors crypto : l'or (25 ans de futures)

**Contexte** : question posee apres l'etape 14 (l'univers elargi
altcoins a nettement echoue) - "sur quel actif ca fonctionnerait mieux ?".
Hypothese initiale : le suivi de tendance est une strategie beaucoup plus
documentee sur les marches traditionnels (CTA/managed futures) que sur
la crypto, et l'or est le terrain de jeu classique de ces strategies
depuis des decennies (cf. Baltas & Kosowski, lu a l'etape 10, qui trouve
un momentum time-series robuste sur plusieurs decennies de futures sans
contrainte de capacite).

**Donnees** : futures or (`GC=F`, yfinance), 2000-08-30 a 2026-09-30, soit
~25 ans et 6546 bougies journalieres - bien plus long que les ~4 ans de
crypto propre disponibles (etapes 13 bis/14/15/16). Marche traditionnel
(pas 24/7) : necessite le nouveau `BacktestConfig.calendar_gap_multiple`
(etape 17) pour ne pas confondre les week-ends/jours feries (jusqu'a 5
jours) avec un vrai trou de donnees.

**Important : reglages INCHANGES**, ceux calibres pour la crypto
journaliere tout au long de la session (`ema_fast=12`, `ema_slow=48`,
`hurst_window=100`, `ou_window=100`, etc.) - aucun recalibrage specifique
a l'or n'a ete tente. Seul `target_vol` est adapte a la vol plus faible de
l'or (0.01 par periode, cohere avec `periods_per_year=252` - jours
ouvres, pas 365).

**Resultats (walk-forward, 10 folds sur 25 ans - bien plus de folds
independants que tout ce qu'on a pu faire en crypto)** :

| Test | Sharpe | p (gaussien) | p (permutation) | CAGR |
|---|---|---|---|---|
| Plein historique, Hurst | -0.295 | - | - | -2.3% |
| Plein historique, ADX | 0.070 | - | - | +0.2% |
| Walk-forward (Hurst vs ADX), OOS | **0.006** | **0.978** | **0.698** | -0.4% |

ADX choisi dans 8 des 10 folds (Hurst dans les 2 premiers seulement).

**Le resultat OOS est quasi exactement NUL** - pas negatif comme sur
l'univers elargi altcoins (etape 14), juste indiscernable du bruit pur
(p=0.98, le plus proche de 1.0 vu cette session). Contrairement a
l'hypothese initiale, l'or ne se montre pas plus favorable que la crypto
a ces reglages - au contraire, moins prometteur que le meilleur resultat
crypto (ADX sur BTC/ETH, etape 15, Sharpe OOS 0.77).

**A ne PAS conclure de ce test** : que le suivi de tendance ne marche
jamais sur l'or - la litterature CTA existe reellement, mais typiquement
avec des fenetres beaucoup plus longues (souvent plusieurs mois) et des
regles differentes (breakouts, pas un croisement EMA 12/48 jours) que ce
qui a ete calibre ici pour la crypto. Ce test montre seulement que nos
reglages ACTUELS ne se transposent pas tels quels a l'or - un recalibrage
specifique (walk-forward sur l'or, pas juste reutiliser les reglages
crypto) serait necessaire avant de tirer une vraie conclusion sur le
potentiel de l'or pour cette approche.

**Verdict** : question ouverte par l'utilisateur honnetement traitee -
premiere incursion hors crypto du projet, pipeline etendu avec succes
(`calendar_gap_multiple`), mais aucun edge trouve avec les reglages
actuels. Le volume de donnees (25 ans, 10 folds) donne neanmoins beaucoup
plus confiance dans le "0.006 = bruit" que dans n'importe quel resultat
crypto de la session (4 ans, 6 folds).

## Etape 17 bis - Or recalibre aux fenetres CTA classiques

**Contexte** : suite immediate de l'etape 17 - au lieu de conclure que
l'or ne marche pas, on recalibre aux fenetres REELLEMENT utilisees par le
suivi de tendance classique (mois a annee, cf. Baltas & Kosowski - etape
10 - dont la meilleure config futures utilisait un lookback de 12 mois),
plutot que de reutiliser telles quelles les fenetres crypto (12-48 jours).

**Grille testee** : 4 paires EMA (20/60, 40/120, 60/180, 100/250 jours) x
Hurst/ADX = 8 configs, `hurst_window`/`ou_window` alignes sur `ema_slow`
(coherence d'echelle entre les signaux). Walk-forward 10 folds, mêmes 25
ans de futures or que l'etape 17.

**Resultats** :

| Test | Sharpe | p (gaussien) | p (permutation) | CAGR |
|---|---|---|---|---|
| Plein historique, EMA(12,48) ADX (etape 17, non recalibre) | 0.070 | - | - | +0.2% |
| Plein historique, EMA(100,250) ADX (recalibre) | **0.402** | - | - | +3.8% |
| Walk-forward (etape 17, non recalibre), OOS | 0.006 | 0.978 | 0.698 | -0.4% |
| **Walk-forward (grille recalibree), OOS** | **0.299** | **0.243** | **0.295** | **+2.6%** |

**Nette amelioration.** Le Sharpe OOS passe de quasi-zero (bruit pur) a
directionnellement positif. ADX(100,250) est choisi dans 6 des 10 folds
(le plus souvent, avec le Sharpe train le plus eleve dans la premiere
moitie de l'historique) - la config a l'echelle "CTA classique" (~1 an de
lookback) domine largement les fenetres courtes de type crypto. Ceci
confirme que le resultat quasi-nul de l'etape 17 etait bien un probleme
de MAUVAISE CALIBRATION (fenetres crypto reutilisees telles quelles), pas
une absence d'edge sur l'or en tant que tel.

**Toujours pas significatif a 5%** (p=0.24-0.30), mais c'est le
**deuxieme meilleur resultat OOS de toute la session**, juste derriere
l'ADX sur BTC/ETH (etape 15, Sharpe 0.77, p=0.33) - et sur un echantillon
bien plus long et donc plus digne de confiance (25 ans / 10 folds contre
4 ans / 6 folds). Les deux resultats (BTC/ETH courte echelle, or longue
echelle) restent du meme ordre de grandeur : directionnellement
interessant, jamais prouve.

**Verdict** : la recalibration etait la bonne piste - a retenir pour
toute extension future a un nouvel actif/marche : ne jamais reutiliser
des fenetres calibrees pour un autre marche sans les reajuster a son
horizon de temps naturel.

## Etape 18 - Bot de paper trading autonome sur l'or

**Contexte** : suite a la lecture de Baur, Dichtl, Drobetz & Wendt (2018,
SSRN) qui montre qu'un edge de market timing non corrige pour le
data-snooping multi-strategies (test SPA de Hansen) ne survit
generalement pas - limite reconnue de notre propre methodologie
walk-forward (etape 17 bis : Sharpe OOS 0.30, jamais significatif a 5%).
Plutot que de continuer a chercher un edge plus solide, on pivote vers
une infrastructure honnete : un bot qui **simule** le suivi de cette
strategie en conditions reelles (prix du jour, coupe-circuit, ordres),
sans y engager d'argent reel - paper trading strictement.

**Choix explicites (clarifies avec l'utilisateur avant construction)** :
- Paper trading uniquement (pas d'argent reel) - aucune des 3 barrieres
  de securite du live reel (etape 6) n'est jamais approchee dans ce module.
- Declenchement par une Routine planifiee de cet environnement (pas un
  script independant sur une autre machine) - une execution par jour,
  coherente avec le pas de temps (bougie journaliere) de toute la
  recherche precedente.

**`gold_paper_bot.py`** : `run_daily_step()` execute une iteration complete :

1. Recupere le prix de l'or (`GC=F`, futures, via `yfinance` - Alpha
   Vantage a atteint sa limite de 25 requetes/jour des le premier essai).
2. Idempotent sur la date : si deja execute pour la derniere bougie
   disponible, renvoie `"deja_a_jour"` sans repasser d'ordre (utile si la
   Routine se redeclenche par erreur le meme jour).
3. Calcule l'equity du compte paper en mark-to-market (cash + positions
   au prix courant), fait avancer le coupe-circuit de drawdown
   (`DrawdownCircuitBreaker`, etape 4/6) avec cette equity.
4. Si le trading est autorise, calcule le poids cible via
   `compute_live_weights` - **exactement** le pipeline signal -> score ->
   poids valide en walk-forward a l'etape 17 bis (`GOLD_CONFIG` : ADX,
   EMA 100/250, fenetres Hurst/OU 250 jours, `calendar_gap_multiple=6.0`
   pour les week-ends/jours feries des marches traditionnels). Si le
   coupe-circuit a declenche, poids cible force a 0.
5. Simule l'ordre de rebalancement (`LiveExecutor(dry_run=True)`) et
   persiste tout l'etat (cash, positions, journal d'ordres, coupe-circuit,
   derniere date executee) en JSON dans `gold_paper_bot_state/`.

**Point important sur le coupe-circuit** : il suit l'equity du COMPTE
PAPER, pas le prix brut de l'or - tant qu'aucune position n'est ouverte,
un krach du prix ne fait baisser l'equity de personne. Le test de
non-regression (`test_run_daily_step_forces_flat_when_circuit_breaker_halts`)
simule donc un scenario a 2 jours (entree en position, puis krach sur la
position deja ouverte) plutot qu'un krach des le premier jour.

**Persistance** : le conteneur cloud qui execute ce script est recree a
chaque declenchement de la Routine - seuls les fichiers JSON commit/push
par l'appelant survivent d'une execution a l'autre (`breaker.json`,
`dry_run.json`, `last_run.json` dans `gold_paper_bot_state/`).

**A faire pour un usage continu** : une Routine planifiee
(`create_trigger`, quotidienne) qui invoque `run_daily_step()`, commit et
pousse l'etat mis a jour, et rapporte le resultat.

## Etape 19 - Systeme de breakout Donchian + filtre MM200

**Contexte** : propose par l'utilisateur (regles d'un systeme CTA
classique, lignee "Turtle Trading") : achat si cloture au-dessus de la MM
200 jours ET au-dessus du plus haut des 20 jours precedents, stop initial
a 2xATR(20), sortie si cloture sous le plus bas des 10 jours precedents,
risque de 0.25-0.5% du capital par position. Contrairement a deux autres
propositions evaluees la meme session (VWAP/volume profile, scalp 1-minute
"PTS: Golden Edge") - toutes deux ecartees faute de donnees intraday
suffisantes - celle-ci est en bougies JOURNALIERES, donc pleinement
compatible avec l'infra deja validee.

**`donchian_system.py`** (nouveau module, en parallele de
`discrete_trading.py` plutot que par extension - logique d'entree/sortie
fondamentalement differente, canal de prix plutot que score composite
Hurst/EMA/OU) :
- Entree a l'OUVERTURE du jour SUIVANT le signal (pas a la meme cloture
  qui vient de le generer) - plus realiste, et corrige au passage un biais
  optimiste present dans `discrete_trading.py` (entree a la cloture du
  jour meme, latence signal->execution nulle).
- Sortie par CANAL (cloture sous le plus bas des N jours precedents),
  independante du score - contrairement au moteur existant qui sort sur
  signal<=0.
- Long-only (coherent avec le reste du projet, spot) : la regle symetrique
  de vente a decouvert proposee n'est PAS implementee (demanderait une
  infra de short jamais construite ici).

**Walk-forward (10 folds, memes 25 ans de futures or que l'etape 17 bis)**,
grille de 4 configs (fenetres d'entree/MM/sortie variees autour de la
proposition initiale), config choisie sur train uniquement a chaque fold :

| Fold | Periode test | Config choisie | Sharpe train | Sharpe test |
|---|---|---|---|---|
| 1 | 2003-01 -> 2005-06 | rapide (10/100/5) | 0.71 | -0.14 |
| 2 | 2005-06 -> 2007-10 | rapide (10/100/5) | 0.40 | +1.13 |
| 3 | 2007-10 -> 2010-03 | rapide (10/100/5) | 0.75 | +0.24 |
| 4 | 2010-03 -> 2012-07 | rapide (10/100/5) | 0.71 | +0.71 |
| 5 | 2012-07 -> 2014-11 | rapide (10/100/5) | 0.71 | -0.67 |
| 6 | 2014-11 -> 2017-04 | rapide (10/100/5) | 0.60 | -0.37 |
| 7 | 2017-04 -> 2019-08 | rapide (10/100/5) | 0.51 | -0.17 |
| 8 | 2019-08 -> 2022-01 | rapide (10/100/5) | 0.47 | -0.63 |
| 9 | 2022-01 -> 2024-05 | rapide (10/100/5) | 0.37 | +0.57 |
| 10 | 2024-05 -> 2026-09 | rapide (10/100/5) | 0.39 | +0.50 |

**OOS enchaine : Sharpe 0.248, p=0.234 (gaussien), p=0.432 (permutation),
CAGR ~0.3%.**

**Deux reserves honnetes, pas seulement le resultat lui-meme** :
1. La meme config ("rapide", fenetres les plus courtes de la grille) est
   choisie a TOUS les folds - la selection sur train n'a jamais reellement
   arbitre entre plusieurs candidats serieux, contrairement a l'etape 17
   bis (ADX choisi 6/10 fois, Hurst les 4 autres). Un signal plus court
   produit mecaniquement plus de trades et un Sharpe train qui parait
   meilleur (effet d'echantillon), sans que ce soit necessairement le
   signe d'un edge superieur - a traiter avec prudence.
2. Le CAGR (~0.3%) est nettement plus bas que le Sharpe seul ne le
   suggere : le sizing par risque (0.25% du capital par trade, stop large)
   laisse l'essentiel du capital en cash la plupart du temps - une
   difference de PHILOSOPHIE de sizing avec le moteur a poids continus
   (etape 17 bis, quasi toujours investi a 100% quand le signal est actif)
   plutot qu'un defaut du systeme Donchian en tant que tel.

**Verdict** : meme ordre de grandeur que l'ADX/EMA de l'etape 17 bis
(Sharpe OOS 0.25 vs 0.30, ni l'un ni l'autre significatif a 5%) - pas une
amelioration nette, mais une confirmation independante (logique d'entree/
sortie completement differente) que l'or affiche un leger biais de
tendance positif, jamais prouve, a cette echelle de temps. Garde en
parallele de la config actuelle du bot de paper trading (etape 18) plutot
que de la remplacer - aucun des deux resultats ne justifie de preferer
l'un a l'autre avec confiance.

**Points souleves par l'utilisateur, non encore traites (a faire avant tout
passage a du reel)** :
- Heure/fuseau de cloture des bougies specifique au courtier reel -
  `yfinance` suit sa propre convention (COMEX), potentiellement differente
  d'un courtier d'execution (ex: IBKR).
- Frais modelises actuellement comme un seul cout forfaitaire
  (`transaction_cost_bps=15`) : pas de spread bid/ask distinct, pas de
  swap/financement (pertinent pour une detention de futures), et une
  sortie sur stop qui s'execute au prix du stop lui-meme meme en cas de
  gap (optimiste - ignore le glissement au-dela du stop).
- Evaluation separee hausse/baisse/range : pas faite explicitement (le
  walk-forward separe le temps, pas le regime de marche) - le walk-forward
  ci-dessus fournit neanmoins une vraie separation train/test stricte.
- Specifications du contrat et sizing avec effet de levier : **non traite
  et important** - `GC=F` est un contrat a marge (COMEX, 100 onces/contrat),
  et le bot de paper trading (etape 18) le traite comme un notional spot
  entierement finance, pas comme une position a levier. Passer a une
  execution reelle sur futures (marge, rollover de contrat) changerait
  fondamentalement le risque reel par rapport a ce qui est mesure ici -
  chantier separe, pas couvert par ce projet a ce stade.

## Etape 9 bis - Le resultat negatif etait un artefact de turnover, pas un edge negatif reel

**Investigation** (le Sharpe de -2.43 avec p≈0 semblait suspect : un signal
simplement "sans edge" devrait donner un Sharpe proche de 0, pas fortement
negatif de facon aussi certaine). Diagnostic sur le backtest 1h ci-dessus :

- Correlation poids-detenu / rendement suivant ≈ 0 (-0.005 BTC, +0.001 ETH) :
  le signal ne capture rien de mesurable, ni dans un sens ni dans l'autre.
- **Cout de transaction cumule : 654% du capital** sur tout le backtest.
  Turnover moyen ~9.2%/heure, alors que les fenetres des signaux choisis
  (`ou_window=150`, `ema_slow=96`, soit 4 a 6 JOURS) impliquent un horizon
  bien plus lent - le systeme rebalance beaucoup plus souvent que ce que son
  propre signal justifie.
- Coupe-circuit de drawdown : actif seulement 1.8% du temps, pas le
  principal coupable.

Une zone morte de rebalancement (`BacktestConfig.rebalance_threshold`,
ajoutee suite a cette investigation - ne rebalance que si l'ecart au poids
cible depasse le seuil, le coupe-circuit continue de liquider immediatement
quel que soit le seuil) **n'a que tres peu aide** : meme a
`rebalance_threshold=0.5` (seuil enorme), le cout cumule ne baisse que de
654% a 584%, Sharpe de -2.43 a -2.04. Le turnover ne vient pas d'ajustements
graduels de position mais de bascules frequentes investi/plat - une simple
zone morte sur la distance de poids n'y change pas grand-chose.

**Ce qui marche : passer en journalier.** Meme code, memes signaux, juste
le pas de temps (1h -> 1d, target_vol et circuit_breaker_cooldown
recalibres comme a l'etape 7) :

| | 1h (turnover mal calibre) | 1d (turnover cohere avec l'horizon du signal) |
|---|---|---|
| Cout cumule sur tout le backtest | 654% | **27%** |
| Backtest simple - Sharpe | -3.69 | 0.39 |
| Backtest simple - max drawdown | -100% (quasi-ruine) | -71% |
| Walk-forward OOS - Sharpe | -2.43 | **0.036** |
| Walk-forward OOS - p-value (`sharpe_significance`) | ≈0 | **0.95** |
| Folds valides | 8/8 | 6/6 |

**Verdict corrige** : le -2.43 a 1h n'etait PAS la preuve d'un edge negatif
reel - c'etait un artefact de sur-trading a une granularite mal adaptee aux
fenetres du signal. Au bon pas de temps, le verdict redevient "pas d'edge
detectable" (Sharpe OOS quasi nul, p=0.95, aucune signification), mais cette
fois confirme sur un echantillon large et propre (950 jours de test,
6 folds, plusieurs regimes 2020-2026) plutot que sur les petits echantillons
des etapes precedentes. Signal revelateur en prime : le Sharpe TRAIN est
fortement positif dans les 6 folds (0.6 a 2.1) alors que l'OOS retombe a
quasi-zero - la signature classique d'un surapprentissage sur du bruit, pas
d'un edge reel. C'est exactement ce que la discipline walk-forward est
censee detecter, et elle le fait.

**A retenir methodologiquement** : un Sharpe fortement negatif ET
statistiquement significatif merite d'etre investigue avant d'etre pris pour
argent comptant - un signal sans edge devrait donner un resultat proche de
zero, pas fortement negatif de facon certaine. Ici, la cause etait un
decalage entre la granularite de trading et l'horizon reel des signaux, pas
un bug de signe ni un edge negatif reel.

## Etape 8 - Significativite statistique et demi-vie adaptative

Inspire de la lecture de *Algorithmic Trading: Winning Strategies and Their
Rationale* (Ernest Chan, Wiley 2013) - les idees et la methodologie sont
reutilisees ici (code et implementation propres a ce projet), pas le texte
du livre.

**metrics.py** : jusqu'ici on rapportait Sharpe/CAGR/drawdown sans jamais
dire si le resultat est statistiquement distinguable du bruit - un Sharpe
qui semble positif peut tres bien ne rien vouloir dire sur un petit
echantillon. Deux nouveaux tests :
- `sharpe_significance` : test gaussien ferme (t = mean(ret)/std(ret)*sqrt(n),
  compare a la loi normale standard) - integre a `summarize_performance`
  (nouvelle cle `sharpe_p_value`).
- `permutation_test_sharpe` : permute l'ordre temporel des LIGNES de
  `weights_history`, reapplique ces poids permutes aux vrais rendements
  d'actifs, et mesure la fraction de permutations qui font au moins aussi
  bien que l'observe. Teste si le TIMING reel des positions ajoute de la
  valeur, pas seulement leur distribution/frequence.

Applique retroactivement a la courbe OOS de l'etape 7 (Sharpe walk-forward
de 0.35) : **p = 0.73** avec `sharpe_significance` - confirme formellement
que ce resultat n'est pas distinguable du bruit (voir etape 7 ci-dessous).

**signals.py** : `ou_meanreversion_signal` expose maintenant une colonne
`half_life` (-log(2)/theta, meme regression AR(1) que le signal lui-meme).
`estimate_dominant_half_life`/`suggest_meanreversion_window` s'en servent
pour calibrer `ou_window` a partir de la demi-vie dominante plutot que
uniquement par grid search - moins de parametres libres optimises en force
brute, donc moins de risque de data-snooping. Pas encore branche
automatiquement dans `WalkForwardValidator` (a appeler manuellement sur un
segment train pour l'instant).

## Etape 6 - Execution (dry-run par defaut, live derriere 3 barrieres)

`LiveExecutor` calcule et passe les ordres de rebalancement (poids cibles ->
positions actuelles -> ordres achat/vente, avec un seuil de notionnel
minimum). Defense en profondeur deliberee : le live REEL exige
SIMULTANEMENT (1) `dry_run=False` explicite, (2) la variable d'environnement
`CRYPTO_QUANT_CONFIRM_LIVE_TRADING="j-accepte-le-risque"`, (3) des cles API
valides en variables d'environnement (`KRAKEN_API_KEY`/`KRAKEN_API_SECRET`,
jamais en dur dans le code). Un `dry_run=False` accidentel seul ne suffit
jamais a declencher un ordre reel.

`compute_live_weights` (dans `backtest.py`) reutilise le meme pipeline que
`run_backtest` pour calculer les poids cibles a partir de la derniere
bougie disponible.

**Perimetre assume, pas cache** : le coupe-circuit de drawdown a besoin de
suivre l'equity de la strategie dans le temps. `save_breaker_state` /
`load_breaker_state` permettent de persister son etat entre deux executions
d'un processus relance periodiquement (cron, etc.), mais l'orchestration
complete d'une boucle de production (frequence d'execution, alerting en cas
d'echec, service systeme) reste a construire selon l'infrastructure de
deploiement de l'utilisateur - ce module fournit les briques necessaires,
pas un service cle en main.

### Exemple d'usage (dry-run)

```python
from crypto_quant.execution import LiveExecutor
from crypto_quant.backtest import BacktestConfig, compute_live_weights
from crypto_quant.data import CCXTDataFeed

cfg = BacktestConfig()
feed = CCXTDataFeed(exchange_id="kraken")
price_data = feed.get_universe_history(["BTC/USD", "ETH/USD"], "1h", history_days=90)

weights = compute_live_weights(price_data, cfg)

executor = LiveExecutor(dry_run=True)  # jamais de vrai ordre sans les 3 barrieres du live
orders = executor.compute_rebalance_orders(
    current_holdings={},  # a recuperer via l'API du compte en usage reel
    target_weights=weights.to_dict(),
    prices={s: df["close"].iloc[-1] for s, df in price_data.items()},
    total_equity=10_000.0,
)
results = executor.execute_orders(orders)
```

## Etape 5 - Backtest et validation walk-forward

`run_backtest` simule la strategie complete bougie par bougie (rendements
cloture-a-cloture, avec couts de transaction proportionnels au turnover) :
calcul des signaux -> score composite -> poids long-only -> tilt par
volatilite inverse -> ciblage de volatilite -> coupe-circuit de drawdown.

**Limite assumee** : pas de simulation intra-bougie, donc le stop-loss ATR
de l'etape 4 n'est pas execute ici (seul le coupe-circuit, qui agit entre
les bougies, l'est).

`WalkForwardValidator` implemente la discipline anti-overfitting : sur
chaque fold, plusieurs configurations d'hyperparametres sont testees sur le
train (choix par Sharpe), la meilleure est appliquee telle quelle sur le
test suivant sans jamais etre revue, et les segments de test sont enchaines
en une seule courbe hors-echantillon. Si les configs choisies varient
enormement d'un fold a l'autre, c'est un signal d'instabilite/overfitting a
surveiller (consulter `FoldResult.chosen_config` par fold).

**Bugs trouves et corriges pendant cette etape** (documentes ici par souci
de transparence, pas juste dans les messages de commit) :
- Le filtre d'alignement des dates entre actifs supprimait a tort toute
  ligne ou le signal OU etait NaN (frequent et normal quand la reversion
  n'est pas significative), tronquant silencieusement l'essentiel de
  l'historique valide.
- Le coupe-circuit de drawdown, une fois totalement en cash, ne pouvait
  jamais reprendre tout seul (l'equity gelee ne remonte jamais au-dessus du
  seuil de reprise relatif a l'ancien pic) : ajout d'un cooldown et d'une
  reinitialisation du pic de reference a la reprise.

## Etape 1 - Donnees

`CCXTDataFeed` (dans `data.py`) recupere l'historique OHLCV d'une liste de
paires via [ccxt](https://github.com/ccxt/ccxt), avec :

- **Pagination automatique** : l'API Kraken limite le nombre de bougies par
  appel, `_fetch_ohlcv_paginated` boucle jusqu'a couvrir toute la periode
  demandee.
- **Cache local** (CSV dans `crypto_quant/data_cache/`, ignore par git) :
  au second appel, seules les bougies manquantes depuis le dernier
  telechargement sont recuperees.
- **Client d'exchange injectable** : `exchange_client=...` permet de
  remplacer le vrai `ccxt.kraken()` par un faux client pour les tests.

`synthetic.py` genere des series de prix synthetiques (mouvement brownien
geometrique + composante de retour a la moyenne Ornstein-Uhlenbeck) et
fournit `FakeExchange`, un faux client ccxt utilise dans les tests pour
verifier la logique de pagination/cache sans acces reseau.

### Mise a jour : premier backtest reel contre Kraken (etape 7)

Le blocage reseau mentionne plus bas a ete leve dans une session ulterieure
(environnement a acces reseau complet). `curl https://api.kraken.com/0/public/Time`
et un vrai `ccxt.kraken()` fonctionnent. Deux points a connaitre pour
reproduire :

- **ccxt et le proxy de la session** : ccxt met `session.trust_env = False`
  par defaut sur son client `requests` interne, donc il ignore les variables
  d'environnement standard (`REQUESTS_CA_BUNDLE`, `HTTPS_PROXY`) meme quand
  elles sont correctement configurees pour le reste de l'environnement. Sans
  ca, on obtient une erreur `SSL: CERTIFICATE_VERIFY_FAILED` (le proxy
  reterminie le TLS avec son propre certificat). Fix a l'usage, pas dans le
  code de `crypto_quant` (comportement specifique a cet environnement
  proxifie, pas quelque chose a coder en dur dans `build_exchange`) :
  ```python
  ex = ccxt.kraken({"enableRateLimit": True})
  ex.session.trust_env = True  # avant de le passer a CCXTDataFeed(exchange_client=ex)
  ```
- **Limite reelle de l'API OHLC publique de Kraken** : verifie directement
  (appel `fetch_ohlcv` avec un `since` vieux de 400 jours -> Kraken renvoie
  quand meme seulement les ~720 dernieres bougies, en ignorant le `since`).
  Ce n'est pas un bug de pagination cote client : l'endpoint OHLC public de
  Kraken ne sert que les N dernieres bougies les plus recentes (~720, quel
  que soit le timeframe), pas d'historique profond arbitraire. Consequence
  concrete : en `1h`, on ne peut recuperer que ~30 jours reels, pas les 730
  jours par defaut de `Config`. Pour un historique de plusieurs mois/annees,
  utiliser un timeframe plus grossier (`1d` -> ~720 jours, verifie).

**Deux bugs reels trouves et corriges grace a ce premier test en conditions
reelles** (jamais apparus sur les 58 tests avec donnees synthetiques,
documentes ici par souci de transparence) :
- `CCXTDataFeed.get_history` (`data.py`) : le cache ne remontait jamais en
  arriere. Un premier appel avec un `history_days` petit plafonnait
  silencieusement tous les appels suivants avec un `history_days` plus grand
  (le cache n'etait complete qu'en avant, jamais en arriere) - decouvert en
  demandant 180 jours d'historique apres un test initial a 3 jours. Fix :
  `get_history` detecte maintenant si le cache ne couvre pas assez loin en
  arriere et backfill le segment manquant en plus de l'extension en avant.
- `WalkForwardValidator._select_best_config` (`backtest.py`) : la selection
  choisissait la config au meilleur Sharpe TRAIN sans verifier qu'elle
  pouvait meme produire un resultat sur le prochain segment de TEST (taille
  fixe). Sur donnees Kraken reelles (1d, ~700 jours, 4 folds), une config a
  grande fenetre (150 periodes de warm-up) gagnait sur un train qui grandit
  a chaque fold - precisement parce qu'elle overfit sur peu de trades - puis
  echouait integralement sur le test suivant (140 bougies, dont 150
  necessaires en warm-up) : 3 folds sur 4 etaient perdus silencieusement.
  Fix : la selection exclut maintenant, sur un critere purement structurel
  (taille du test, jamais ses prix), les configs qui ne peuvent
  structurellement pas produire de resultat exploitable sur le test suivant.

**Resultats du premier backtest reel** (BTC/USD + ETH/USD, capital initial
10 000$, couts de transaction inclus) - rapportes sans enjolivure :

| | 1h, ~30j reels (limite Kraken), config par defaut | 1d, ~700j reels, config recalibree (target_vol, cooldown) |
|---|---|---|
| Backtest simple - Sharpe | -3.23 | -1.02 |
| Backtest simple - CAGR | -66% | -35% |
| Backtest simple - max drawdown | -13.6% | -63.4% |
| Walk-forward OOS - Sharpe | n/a (trop court pour un WFV a 4 folds) | **0.35** |
| Walk-forward OOS - CAGR | n/a | 6.6% |
| Walk-forward OOS - max drawdown | n/a | -36.5% |
| Walk-forward OOS - hit rate | n/a | 12.8% |

**Verdict honnete** : rien ici ne demontre un edge reel. Le backtest simple
(periode complete, une seule config) est nettement negatif dans les deux
cas. Le Sharpe hors-echantillon de 0.35 en walk-forward est a peine positif,
sur un tres petit echantillon (n=360 jours-test, 4 folds, 2 actifs), avec un
hit rate de seulement 12.8% (la performance ne tient qu'a de rares gros
gains - profil fragile, pas un edge robuste). La config choisie est stable
d'un fold a l'autre (bon signe methodologique - pas de flip-flop erratique),
mais ca ne compense pas la faiblesse du signal lui-meme. A ce stade, la
strategie ne montre pas d'edge exploitable sur cet univers/cette periode.

**Confirmation formelle (etape 8)** : `sharpe_significance` (test gaussien
ferme, cf. Chan, "Algorithmic Trading", chap. 1) applique a cette meme
courbe OOS donne **p = 0.73** - le Sharpe de 0.35 n'est absolument pas
distinguable du bruit statistique (73% de chances d'observer un resultat au
moins aussi extreme sous l'hypothese nulle "pas d'edge reel"). Ca confirme
avec un chiffre ce que l'analyse qualitative disait deja : ce backtest ne
constitue pas une preuve d'edge.

### Installation et tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r crypto_quant/requirements.txt
pytest crypto_quant/tests/ -v
```

### Usage (une fois un vrai reseau disponible)

```python
from crypto_quant.data import CCXTDataFeed
from crypto_quant.config import Config

cfg = Config()
feed = CCXTDataFeed(exchange_id=cfg.universe.exchange, cache_dir=cfg.data.cache_dir)
history = feed.get_universe_history(cfg.universe.pairs, cfg.universe.timeframe, cfg.data.history_days)
```
