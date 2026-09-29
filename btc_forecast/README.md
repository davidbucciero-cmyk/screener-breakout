# btc_forecast — direction BTC 1h avec Chronos (zero-shot)

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

## Lancer
Depuis GitHub : onglet **Actions → BTC 1h Forecast (Chronos) → Run workflow**. Le rapport
(`report.html`, CSV) est dans les artifacts du run.

En local :
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r btc_forecast/requirements.txt
python -m btc_forecast.run backtest --n-test 2000 --fee-bps 5
python -m btc_forecast.run predict      # P(hausse) pour la prochaine bougie
```

## Lire le resultat
- **p-value > 0.05** : le taux de reussite n'est pas distinguable du hasard.
- **brier_modele >= brier_freq_constante** : les probabilites n'apportent rien.
- Une strategie n'a d'interet que si elle bat buy & hold **net de frais**.
