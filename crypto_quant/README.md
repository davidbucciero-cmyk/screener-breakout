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

## Etat d'avancement

- [x] Etape 1 - Donnees (`data.py`, `synthetic.py`, `config.py`)
- [x] Etape 2 - Signaux (Hurst, EMA, Ornstein-Uhlenbeck, EWMA vol)
- [x] Etape 3 - Combinaison des signaux (`portfolio.py`)
- [x] Etape 4 - Risque et sizing (`risk.py`)
- [x] Etape 5 - Backtest walk-forward (`backtest.py`, `metrics.py`)
- [ ] Etape 6 - Execution (dry-run par defaut)

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

### Limite connue de cet environnement de dev

Dans le sandbox cloud utilise pour developper ce module, l'acces reseau
sortant vers `api.kraken.com` est bloque par la politique d'egress de la
session (403). Le code est ecrit pour un usage reel (il suffit d'un acces
internet normal, aucune cle API n'est requise pour lire des donnees
publiques), mais n'a pas pu etre teste en direct contre Kraken depuis cette
session - seulement contre des donnees synthetiques via `FakeExchange`.

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
