# btc_forecast — prevision BTC 1h : Chronos (zero-shot) et EnKF (methode meteo)

Les modeles meteo (GraphCast, Pangu, Aurora) attendent des grilles lat/lon de variables
atmospheriques : une serie de prix n'y rentre pas. On utilise a la place un modele de fondation
series temporelles, **Chronos-Bolt** (Amazon), pre-entraine sur des millions de series (dont
beaucoup de meteo/energie), applique sans re-entrainement a BTC/USDT 1h.

## Principe
1. Bougies 1h cloturees depuis Binance (`data-api.binance.vision`, fallback Coinbase).
2. Pour chaque heure `t`, Chronos recoit les 512 derniers closes (jusqu'a `t` inclus) et predit
   les quantiles q10..q90 du close `t+1`.
3. `P(hausse) = 1 - F(close[t])`, ou `F` est la repartition interpolee entre les quantiles.
4. Backtest walk-forward sur les N dernieres heures : taux de reussite (+ p-value vs 50 %),
   score de Brier, strategies long/short a seuils nettes de frais, comparees a buy & hold,
   momentum, mean-reversion et aleatoire.

## Moteur EnKF (assimilation de donnees par ensemble)
La methode des centres meteo, transposee (`enkf.py`, `--engine enkf`) :
- **Etat latent** par membre : drift horaire `mu` et log-variance `h`.
- **Dynamique** : AR(1) sur `mu` et sur `h` (vol stochastique) ; chaque membre tire ses propres
  coefficients de persistance (ensemble a parametres perturbes). N = 100 membres.
- **Observations** a chaque bougie cloturee : rendement (observe `mu`, bruit `exp(h)`) et
  log-variance de Parkinson high/low (observe `h`, bruit calibre sur 30 j glissants).
- **Assimilation** : EnKF stochastique (observations perturbees), inflation de covariance 1.05.
- **Niveau de vol de reference** : variance realisee 30 j glissante, uniquement passee.
- **Sorties** : P(hausse), vol prevue, ratio moyenne/dispersion du drift (sizing), dispersion
  de la vol (fiabilite : flat si superieure a sa mediane passee).

Le rapport ajoute une section **prevision de volatilite** (QLIKE vs variance realisee 24 h / 30 j) :
c'est la que l'EnKF a le plus de chances d'etre utile (sizing, stops), le drift horaire etant
quasi inobservable.

Funding, open interest et carnet d'ordres ne sont pas encore branches : il suffit d'ajouter une
ligne d'observation (et son operateur `H`) dans `run_enkf`.

## Trend following quotidien + ciblage de volatilite (`trend.py`)
- Signal : momentum temporel long/flat sur 20, 60, 120 et 250 jours (horizons standards, non
  optimises), moyenne des votes -> exposition de 0 a 100 %.
- Ciblage de vol : exposition x vol cible (40 %/an) / vol prevue, plafonnee a 1 (pas de levier).
  Vol prevue par l'EnKF sur bougies journalieres, comparee a la vol realisee 30 j.
- Bande de re-balancement de 10 % pour limiter les frais (10 bps par cote, spot).
- Rapport : rendement annuel, Sharpe, max drawdown, Calmar, rendement par annee.

```bash
python -m btc_forecast.run trend --target-vol 0.4 --max-leverage 1
```

## Compte demo (`paper.py`)
Paper trading de la strategie retenue (trend ensemble + ciblage vol 30 j) sur BTC, ETH et SOL,
10 000 USDT fictifs repartis en trois poches egales, prix de cloture Binance reels, frais 10 bps.
Le workflow **Compte demo crypto** tourne chaque jour a 00:07 UTC, enregistre l'etat dans
`paper_trading/` (`state.json`, `trades.csv`, `equity.csv`) et envoie un email recapitulatif
(meme secret `EMAIL_PASSWORD` que le screener). Compare en continu a un buy & hold equipondere.

## Lancer
Depuis GitHub : onglet **Actions → BTC 1h Forecast → Run workflow** (choisir `enkf` ou `chronos`). Le rapport
(`report.html`, CSV) est dans les artifacts du run.

En local :
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r btc_forecast/requirements.txt
python -m btc_forecast.run backtest --n-test 2000 --fee-bps 5
python -m btc_forecast.run predict      # P(hausse) pour la prochaine bougie
python -m btc_forecast.run backtest --engine enkf   # sans torch ni HuggingFace
```

## Lire le resultat
- **p-value > 0.05** : le taux de reussite n'est pas distinguable du hasard.
- **brier_modele >= brier_freq_constante** : les probabilites n'apportent rien.
- Une strategie n'a d'interet que si elle bat buy & hold **net de frais**.
