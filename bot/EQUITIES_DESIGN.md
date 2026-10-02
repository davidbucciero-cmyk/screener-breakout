# Actions US — spec, architecture, plan (a valider avant tout code)

Statut : **valide le 2026-10-02** (univers > 2 Md$, chaque bloc seul puis combinaison). Pivot decide le 2026-10-02 apres 11 strategies crypto et 21 indicateurs
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

## Methode (meme protocole qu'en crypto)
1. **Chaque bloc seul, periode de dev uniquement (2010-2018)** : chaque fin de mois, on classe toutes les actions
   de l'univers selon la feature et on mesure la correlation de rang avec leur rendement du mois suivant
   (IC). Moyenne des IC mensuels, t-stat, stabilite du signe par annee. Seuil de t corrige du nombre de features.
2. **Combinaison** : un seul modele (score composite des features retenues, poids appris uniquement sur le passe,
   reajuste chaque annee). Un seul essai, pas une recherche de combinaisons.
3. **Une seule evaluation hors echantillon (2019 a aujourd'hui)** : portefeuille des meilleures actions du score,
   couvert par une vente de SPY, puis gate inchange.

## Univers
Actions US cotees (NYSE, Nasdaq) dont la capitalisation depasse 2 Md$ a la date de decision :
nombre d'actions publie a la SEC (page de garde des rapports, `dei:EntityCommonStockSharesOutstanding`)
x cours du jour.

## Blocs de la premiere vague (backtestables gratuitement)
| Code | Feature | Source | Disponible a la decision |
|---|---|---|---|
| A1 | Achats d'initiés : nombre d'initiés distincts acheteurs (code P) sur 90 j, montant | SEC Form 3/4/5 | date de publication du Form 4 |
| A2 | Croissance du chiffre d'affaires sur 1 an | SEC XBRL (annuel) | 90 j apres la cloture de l'exercice |
| A6 | Moyenne 50 j au-dessus de la 200 j (golden cross du screener) | prix | cloture |
| B1 | Momentum 12-1 mois | prix | cloture |
| B2 | Distance au plus haut 52 semaines | prix | cloture |
| B3 | Volatilite 12 mois (faible = mieux attendu) | prix | cloture |
| B4 | Rendement du dernier mois (retournement) | prix | cloture |
| C1 | Rentabilite brute : marge brute / actifs | SEC XBRL | 90 j apres la cloture |
| C2 | Variation du nombre d'actions sur 1 an (rachats) | SEC | 15 j apres la date de la page de garde |
| C6 | Accruals : (resultat net - cash operationnel) / actifs | SEC XBRL | 90 j apres la cloture |

Vague suivante si utile : 13F (A3), short interest (A4), textes des 10-K (C4), resultats (C3/D1).

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
1. Donnees via GitHub Actions : tickers SEC, nombre d'actions et comptes annuels (API XBRL frames),
   achats d'initiés (fichiers Form 3/4/5), prix Yahoo.
2. Panel mensuel des features, chacune datee a sa disponibilite reelle. Tests anti-lookahead.
3. IC de chaque bloc sur 2010-2018. **Pause : resultats montres.**
4. Modele combine + evaluation unique 2019-2026, couverte et non couverte.

Limite connue des donnees XBRL frames : elles renvoient la derniere valeur deposee pour une periode, donc une
eventuelle correction posterieure peut fuiter. Le decalage de 90 jours limite l'effet ; il sera signale.
