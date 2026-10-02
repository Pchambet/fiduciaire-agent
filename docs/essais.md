# Essais réels de l'agent

Trois essais le 2026-09-28, chacun sur le mois de démonstration fraîchement chargé (`fidu demo`) :
un par modèle, puis Sonnet 5 à nouveau sur le code final, après les corrections de la relecture.
L'agent n'avait que les six outils MCP : aucun accès aux fichiers, donc aucun accès au corrigé, qui
vit dans `src/fiduciaire_agent/demo.py`.

```bash
claude -p "Classe les pièces en attente de ce client de la fiduciaire. Termine par un résumé : \
ce que tu as proposé, tes doutes, et ce qui doit aller à un humain." \
  --mcp-config mcp.json --strict-mcp-config --tools "" --allowedTools "mcp__fiduciaire" \
  --setting-sources project --no-session-persistence --output-format stream-json --verbose
uv run fidu evaluer
```

| Modèle | Classements justes | Appels d'outils | Refus du serveur | Tours | Durée | Coût |
|---|---|---|---|---|---|---|
| Claude Opus 5.5 | **9 / 9** | 15 | 0 | 16 | 42 s | 0,19 $ |
| Claude Sonnet 5 | **9 / 9** | 13 | 0 | 14 | 41 s | 0,14 $ |
| Claude Sonnet 5, code final | **9 / 9** | 13 | 0 | 14 | 47 s | 0,09 $ |

Les classements justes viennent de `fidu evaluer`. Les autres colonnes ont été lues dans la sortie
stream-json de la CLI et recopiées à la main ; les transcriptions brutes n'ont pas été conservées,
donc ces colonnes ne peuvent pas être revérifiées.
Le nombre de jetons et l'usage du cache n'ont pas été relevés non plus : l'écart de coût entre les
deux essais Sonnet (0,14 $ et 0,09 $ pour les mêmes appels et tours) reste inexpliqué.

Les prochains essais seront consignés sans recopie : rediriger la sortie de la commande ci-dessus
(`> essai.jsonl`), puis, avant toute validation, lancer `uv run fidu essai essai.jsonl`. La commande
garde la transcription dans `docs/runs/` (sans les événements `system`, qui décrivent le poste
local) et ajoute à `docs/runs/results.jsonl` une ligne dont chaque colonne est lue dans la
transcription (appels d'outils, refus du serveur, tours, durée, coût, jetons et cache), avec le
score de `fidu evaluer`. Aucun essai n'a encore été consigné ainsi.

Aucun n'a proposé d'écriture sur les 7 pièces en anomalie (dont 6 bloquées). **Neuf pièces et un
ou deux essais par modèle ne font pas un banc d'essai** : le résultat dit que la chaîne fonctionne
de bout en bout, pas quel est le taux d'erreur d'un modèle sur des pièces réelles.

## Ce que l'essai a changé dans le code

Le premier agent a relevé qu'une facture sans date (le garage) était datée au 30.09, date du
relevé, alors qu'elle avait été payée le 20.09. C'était un vrai défaut : une facture sans date prend
désormais la date de son paiement rapproché, et un test le fixe.

Il a aussi soulevé deux questions qui relèvent du métier et restent ouvertes :
- une facture qui n'indique pas la TVA ne permet peut-être pas de déduire l'impôt préalable ; le
  logiciel ne le signale pas encore ;
- les encaissements clients sont passés en 1100 en supposant les factures de vente déjà
  comptabilisées ; la maquette ne suit pas les ventes, donc ne peut pas le vérifier.

## Le résumé rendu par Claude Opus 5.5, tel quel

> J'ai proposé une écriture pour les 9 pièces à classer (écritures n° 14 à 22). Elles restent au statut « proposée » : rien n'est comptabilisé tant qu'une personne ne les a pas validées.
>
> **Écritures proposées**
>
> | Écr. | Pièce | Compte | TVA | Motif |
> |---|---|---|---|---|
> | 14 | F-assurance-rc-2027 | 6300 Assurances | 0 % (facture) | Prime RC entreprise |
> | 15 | F-garage-3190 | 6200 Véhicules | TVA81 (supposée) | Service et pneus de la camionnette |
> | 16 | F-hotel-7730 | 6640 Voyage/représentation | 3,8 % (facture) | Nuitées, séminaire client |
> | 17 | F-librairie-551 | 6500 Administration | 2,6 % (facture) | Ouvrages de référence |
> | 18 | F-traiteur-126 | 6640 Voyage/représentation | 8,1 % et 2,6 % (facture) | Apéritif clients |
> | 19 | B-BK-0903-01 | 6000 Loyer | EXO | Loyer de l'atelier, septembre |
> | 20 | B-BK-0925-01 | 1100 Débiteurs | EXO | Paiement de la facture A-2026-031 |
> | 21 | B-BK-0925-02 | 1100 Débiteurs | EXO | Paiement de la facture A-2026-034 |
> | 22 | B-BK-0930-01 | 6900 Frais financiers | EXO | Frais de tenue de compte |
>
> **Mes doutes**
>
> - **Garage (écr. 15)** : la facture n'indique ni TVA, ni date, ni numéro.
>   - J'ai supposé le taux de 8,1 %. Mais sans facture conforme, l'impôt préalable de 64.80 n'est pas vraiment déductible. Il faut demander une facture en règle au garage.
>   - Comme la facture n'a pas de date, le grand livre l'a datée au 30.09. Or elle a été payée le 20.09 (B-BK-0920-01) : la date est à corriger.
> - **Assurance RC (écr. 14)** : la prime couvre 2026-2027. Selon la date de clôture de l'exercice, il faudra peut-être en reporter une partie sur l'exercice suivant (actif transitoire).
> - **Encaissements clients (écr. 20 et 21)** : je les ai passés en 1100 en supposant que les factures de vente A-2026-031 et A-2026-034 sont déjà enregistrées. Je ne peux pas le vérifier avec les outils disponibles. Si elles ne le sont pas, ces encaissements doivent aller en 3400 avec TVA81. Les montants le suggèrent : 3243 = 3000 + 8,1 % et 1081 = 1000 + 8,1 %.
> - **Loyer (écr. 19)** : je l'ai passé sans TVA. Il faudrait l'ajuster si le bailleur a choisi de soumettre le loyer à la TVA.
> - **Traiteur (écr. 18)** : 6640 me paraît le plus probable. Si l'apéritif était un événement promotionnel, 6600 Publicité conviendrait mieux.
>
> **À traiter par un humain : 7 pièces bloquées, auxquelles je n'ai pas touché**
>
> **Gravité haute :**
> - **B-BK-0922-01** : Télécom Démo a facturé 162.15 mais seulement 150.00 ont été payés.
> - **F-papeterie-2026-0917-copie** : facture reçue deux fois.
> - **B-BK-0909-01** : facture Informatique Démo payée deux fois (déjà réglée par B-BK-0908-01). Il faut demander le remboursement ou un avoir.
> - **F-imprimerie-6612** : la référence QR est invalide (chiffre de contrôle faux).
> - **F-nettoyage-0925** : la TVA est incohérente. 1000 + 8,1 % donne 1081.00, mais la facture dit 1100.00.
>
> **Gravité moyenne :**
> - **B-BK-0924-01** : paiement à « Fournisseur Démo Inconnu » avec une référence qu'aucune facture ne porte.
> - **F-informatique-4388** : facture de 540.50 échue le 09.09 et toujours impayée. À rapprocher du doublon de paiement ci-dessus : le deuxième paiement visait peut-être cette facture.
