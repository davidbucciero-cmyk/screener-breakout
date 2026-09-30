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
