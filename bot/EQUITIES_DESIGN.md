# Actions US — spec, architecture, plan (a valider avant tout code)

Statut : **en attente de validation**. Pivot decide le 2026-10-02 apres 11 strategies crypto et 21 indicateurs
sans edge suffisant.

## Pourquoi les actions
Le screener collecte deja des signaux ou un avantage informationnel est documente dans la litterature
academique (achats d'initiés surtout). En crypto, toutes les donnees testees etaient soit publiques et
deja arbitrees, soit en perte de vitesse.

## Ce que le screener permet de backtester
Le screener ne garde qu'un instantane du jour : il faut reconstruire l'historique depuis des sources archivees.

| Signal du screener | Source historique | Depuis | Backtestable |
|---|---|---|---|
| Achats d'initiés (step3) | SEC, jeux de donnees Form 3/4/5 (fichiers trimestriels publics) | 2006 | ✅ oui, au jour de publication |
| Fondamentaux (step4) | SEC, Financial Statement Data Sets (XBRL), avec date de depot | 2009 | ✅ oui, plus lourd |
| Short interest (step6) | FINRA, fichiers bimensuels | a verifier | ⚠️ a verifier |
| Parlementaires (step10) | FMP gratuit = 10 dernieres operations | — | ❌ pas d'historique exploitable |
| Reddit (step7) | — | — | ❌ |
| Mat-fanion (step2) | prix Yahoo | 2000+ | ✅ (deja teste en crypto, sans succes) |

## Premiere strategie testee (une seule, fixee a l'avance)
**Achats groupes d'initiés** (Lakonishok & Lee 2001 ; Cohen, Malloy & Pomorski 2012) :
- Signal : au moins 2 initiés distincts achetent en bourse (code de transaction `P`) dans une fenetre de 30 jours,
  pour au moins 50 000 $ au total. Memes regles que `step3_insiders.py`.
- Date de decision : le lendemain de la **publication** du Form 4 a la SEC (pas la date de la transaction).
- Portefeuille : chaque action signalee est achetee a l'ouverture suivante, a poids egal, et gardee 3 mois.
- Univers : actions US de plus de 2 Md$ de capitalisation (comme le screener).

## Le probleme du drawdown
Un portefeuille d'actions acheteur seul suit le marche : le S&P 500 a perdu 34 % en 2020 et 25 % en 2022.
Le seuil de drawdown (15 %) est alors quasi impossible a tenir, quel que soit le signal.
**Proposition : couvrir le marche** en vendant a decouvert l'ETF SPY pour le meme montant (possible sur Alpaca paper).
On mesure alors l'edge pur du signal, sans le risque de marche. Le seuil reste inchange.

## Couts
Alpaca actions : 0 commission. Spread + slippage : 10 bps par cote pour les actions, 2 bps pour SPY.
Cout d'emprunt de SPY : 0,5 %/an.

## Periodes
Dev : 2010-2018. Hors echantillon : 2019 a aujourd'hui (Covid 2020 et marche baissier 2022 inclus).
Beaucoup plus de donnees qu'en crypto : 7 ans hors echantillon au lieu de 2.

## Biais connus, annonces avant les resultats
- **Survivant** : Yahoo n'a plus les prix de nombreuses actions retirees de la cote (faillites, rachats).
  Les rendements seront un peu surestimes. Attenuation : univers reconstruit a chaque date, et une action
  sans prix est comptee a -100 % si elle a ete radiee pour faillite (quand l'info est connue), sinon exclue
  et signalee dans le rapport.
- **Nombre d'essais** : on repart de 1 essai pour cette nouvelle famille, mais le rapport rappellera les 11
  strategies crypto deja testees.

## Plan (test qui echoue d'abord a chaque etape)
1. Telecharger les fichiers SEC Form 3/4/5 (2006-2026) via GitHub Actions, extraire les achats `P`.
2. Construire les signaux d'achats groupes, dates a la publication. Test anti-lookahead.
3. Prix quotidiens Yahoo des actions signalees + SPY.
4. Backtest couvert et non couvert, gate inchange, rapport par periode et par regime.
5. **Pause** : resultats montres avant toute suite (fondamentaux, paper trading).
