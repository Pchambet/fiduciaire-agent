# 0002. L'agent classe, le grand livre écrit

Statut : accepté, 2026-09-28.

## Contexte

Une écriture fausse peut l'être de deux façons : mauvais classement (le compte, le code TVA) ou
mauvais calcul (des lignes qui ne s'équilibrent pas, une TVA mal extraite, un arrondi perdu).
La seconde famille n'a aucune raison d'exister, puisqu'elle a une réponse exacte.

## Options

1. **L'agent écrit les lignes**, le serveur les vérifie après coup et refuse ce qui est faux.
2. **L'agent n'envoie qu'un classement** (compte, code TVA si la pièce n'en porte pas, justification),
   et le serveur construit lui-même l'écriture.

## Décision

Option 2. L'outil `proposer_ecriture` prend `piece`, `compte`, `justification` et, au besoin,
`code_tva`. Le module `ledger` construit les lignes : ventilation par taux depuis le bloc Swico S1,
compte d'impôt préalable 1170 ou 1171 selon la classe du compte de charge, résidu d'arrondi
affecté à la part la plus grosse pour que l'écriture égale exactement la facture.

## Conséquences

- Une écriture déséquilibrée ou mal calculée ne peut pas exister : les invariants sont vérifiés à la
  construction, et un test vérifie que toutes les écritures stockées s'équilibrent.
- L'agent ne peut se tromper que sur le classement, et c'est exactement ce que mesure
  `fidu evaluer`. Le périmètre d'erreur est petit, nommé et mesurable.
- Quand la facture indique sa TVA, l'agent n'a pas le droit d'en proposer une autre : le serveur
  refuse avec une raison lisible, que le modèle lit pour se corriger.
