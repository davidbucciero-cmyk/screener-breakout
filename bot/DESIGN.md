# Bot BTC/USD — spec, architecture, plan (a valider avant tout code)

Statut : **en attente de validation**. Aucun module n'est code tant que ce document n'est pas approuve.

## 1. Spec

| Sujet | Decision |
|---|---|
| Actif | BTC/USD spot, long ou flat (pas de short, pas de levier) |
| Courtier | Alpaca **paper** (crypto). IBKR ecarte : sa passerelle exige une session TWS/Gateway avec 2FA, incompatible avec GitHub Actions et avec la regle "jamais de 2FA" |
| Execution | GitHub Actions, toutes les heures (cron `5 * * * *`), bougies 1h cloturees |
| Strategies candidates | (A) breakout mat-fanion adapte au 1h (logique de `screener/scripts/step2_technical.py`) ; (B) trend ensemble + ciblage vol (`btc_forecast/trend.py`) ; (C) A filtre par B |
| Couche de decision rapide | Jev (questions a issue fixe), appele une fois par bougie |
| Cerveau lent | Claude Opus via API, une fois par nuit : revue de session, propositions de modifs sous forme de **pull request**, jamais de merge automatique |
| Alertes | Email (secret `EMAIL_PASSWORD` deja utilise) + issue GitHub pour kill switch / validation manuelle. Pas de Telegram |
| Dashboard | `bot/output/dashboard.html` regenere chaque heure (signal, probas Jev, confiance, action, resultat) |

### Gate de backtest (code, pas modele)
Sur >= 2 ans de 1h, frais **25 bps par cote** (taker Alpaca crypto) + 5 bps de slippage, walk-forward,
note uniquement sur la partie hors echantillon :
Sharpe > 1,5 · max drawdown < 15 % · taux de reussite > 55 % · t-stat > 2,0.
Resultats aussi par regime (haussier / baissier / range, vol haute / basse).
Si aucune strategie ne passe : **pas de bot**, on le dit.

## 2. Architecture (3 couches, aucun chevauchement)

```
                 nuit (cron 02:13 UTC)                       chaque heure (cron :05)
┌──────────────── Opus (lent) ────────────────┐   ┌──────────── code deterministe ────────────┐
│ lit journal + fills → propose PR :          │   │ data.py  bougies + carnet (Binance/Alpaca)│
│ strategy.md, questions Jev, 1 regle/perte   │   │ state.py snapshot numerique (t-1 strict)  │
│ la CI rejoue le gate ; toi seul merges      │   │    │                                      │
└─────────────────────────────────────────────┘   │    ▼                                      │
                                                  │ jev.py  ──► Jev (reflexe) : probas        │
                                                  │    │                                      │
                                                  │    ▼                                      │
                                                  │ decide.py  seuils strategy.md, poids      │
                                                  │ sizing.py  1/4 Kelly plafonne             │
                                                  │ risk.py    VETO (limites dures) ◄─ final  │
                                                  │ broker.py  ordre Alpaca paper             │
                                                  │ journal.py log decision + resultat        │
                                                  └───────────────────────────────────────────┘
```

Les modeles conseillent, le code decide. `risk.py` est appele juste avant chaque ordre et ne lit aucune sortie de modele.

### Snapshot (seule chose que Jev voit)
Rendements 1h/4h/24h, vol realisee 24h/7j, pente tendance 20/60/120j, position du prix dans le fanion,
ratio volume acheteur taker (dispo en historique via Binance), spread et desequilibre carnet top-10
(**live seulement** : pas d'historique gratuit, donc journalises mais exclus de la decision tant qu'ils
ne sont pas backtestables). Uniquement des donnees horodatees strictement avant la decision ; test unitaire dedie.

### Questions Jev (un appel)
regime (choix : tendance haussiere / baissiere / range), direction (choix : hausse / baisse / neutre),
pression acheteuse reelle (oui/non), qualite du setup (score 1-5), etat du risque (choix : normal / eleve / extreme).
On ne trade que si **chaque** proba depasse son seuil dans `strategy.md`.

### Limites dures (`risk.py`, valeurs initiales sur 10 000 $ paper)
| Limite | Valeur |
|---|---|
| Position max | 50 % de l'equity |
| Perte journaliere max | 3 % → plus d'ordre jusqu'au lendemain UTC |
| Drawdown max | 15 % → **kill switch** : vente totale + fichier `bot/HALT` ; redemarrage uniquement en supprimant ce fichier a la main |
| Validation manuelle | ordre > 1 000 $ → non execute, issue GitHub ouverte, execute seulement si tu ajoutes le label `approved` |
| Donnees perimees | derniere bougie > 2h → aucun ordre |

### Calibration
Chaque decision et son issue sont journalisees. Brier + courbe de fiabilite par question, chaque nuit.
Tant qu'il n'y a pas >= 200 decisions resolues et une courbe correcte, sizing fixe minimal (pas de Kelly).
Si la courbe plie : recalibration isotone dans le code.

## 3. Plan (chaque etape : test qui echoue d'abord, puis code, revue vs cette spec)

1. `bot/state.py` + test anti-lookahead
2. `bot/backtest.py` + gate (frais Alpaca, walk-forward, par regime) → lancer A, B, C via GitHub Actions
3. **Pause** : je te montre les chiffres. Si rien ne passe, on s'arrete ou on change d'idee
4. `bot/strategy.md` pour la gagnante
5. `bot/risk.py` + tests (chaque limite, kill switch qui se declenche vraiment)
6. `bot/jev.py` (client + mode simule pour les tests), `decide.py`, `sizing.py`
7. `bot/broker.py` Alpaca paper, `journal.py`, `dashboard.py`, alertes email/issue
8. Workflow horaire `bot_hourly.yml` + workflow nuit `bot_nightly.yml` (PR Opus, CI rejoue le gate)
9. Rapport quotidien : trades, P&L, taux de reussite, plus grosse perte, latence et cout Jev, score de calibration
10. Check final "WHAT COULD BLOW UP THIS ACCOUNT?" — pas de reel tant que tout n'est pas propre

Rollback : chaque etape est un commit ; le bot lit `strategy.md` versionne, revenir en arriere = `git revert`.

## Risques deja identifies
- **Jev dans le backtest** : Jev a ete entraine sur des donnees qui couvrent probablement 2024-2026, donc ses probas historiques peuvent "connaitre" le futur. Sa valeur ne se juge qu'en forward (paper). Le gate porte sur la strategie deterministe ; Jev n'est qu'un filtre a prouver en live.
- **Frais** : 25 bps par cote sur Alpaca crypto. Une strategie qui trade souvent en 1h meurt la-dessus.
- **GitHub Actions** : les cron peuvent avoir 5-20 min de retard ; acceptable en 1h, pas en "chaque bougie sub-seconde".
- **Sharpe > 1,5 hors echantillon** sur BTC long-only est un seuil tres dur ; s'attendre a ce que rien ne passe.
