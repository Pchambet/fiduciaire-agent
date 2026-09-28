# 0003. Une personne valide chaque écriture, et l'agent n'a aucun outil pour le faire

Statut : accepté, 2026-09-28.

## Contexte

En fiduciaire, la responsabilité d'une écriture reste humaine. La question n'est pas de savoir si
le modèle classe bien en moyenne, mais qui répond d'une écriture précise.

## Options

1. **Validation automatique au-dessus d'un seuil de confiance.** Moins de travail, mais un seuil
   de confiance déclaré par le modèle n'est pas une probabilité calibrée, et l'erreur passe sans
   témoin.
2. **Validation humaine de tout, avec une interface qui la rend rapide.**

## Décision

Option 2. Toute écriture, qu'elle vienne d'une règle, d'un rapprochement ou de l'agent, naît
« proposée ». La validation passe par la ligne de commande (`fidu valider`, en lot par origine pour
les écritures de règle et de rapprochement). Le serveur MCP n'expose aucun outil qui valide ou
rejette : un test le vérifie. Un rejet exige un motif, et la pièce revient dans la liste à classer.

Pour réduire la charge sans déléguer la décision : `fidu valider <n> --retenir` transforme un
classement validé en règle fournisseur. Le mois suivant, ce fournisseur est traité sans le modèle.

## Conséquences

- Le travail humain se déplace de la saisie vers la relecture, pièce justifiée en main.
- La justification de l'agent est obligatoire (au moins une phrase) : c'est elle qui rend la
  relecture rapide.
- Si un jour une validation automatique est envisagée, elle devra s'appuyer sur un historique
  mesuré par fournisseur, pas sur la confiance déclarée du modèle.
