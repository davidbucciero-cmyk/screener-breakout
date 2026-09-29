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
