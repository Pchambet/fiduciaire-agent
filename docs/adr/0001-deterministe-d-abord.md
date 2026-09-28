# 0001. Le code déterministe d'abord, l'agent seulement pour ce qui reste

Statut : accepté, 2026-09-28.

## Contexte

Une fiduciaire reçoit chaque mois, pour chaque client, des QR-factures et un relevé bancaire. La
plus grande partie du travail est mécanique : lire, vérifier, rapprocher un paiement de sa facture,
ventiler la TVA. Une petite partie demande du jugement : dans quel compte passer une facture d'un
fournisseur jamais vu, que faire d'un débit sans facture.

## Options

1. **Tout confier au modèle** : il lit les pièces et propose toutes les écritures. Rapide à
   construire, mais chaque chiffre devient probabiliste, et une erreur de rapprochement ne se voit
   qu'à la révision.
2. **Tout en règles** : aucune dépendance à un modèle, mais chaque nouveau fournisseur demande une
   règle écrite à la main, et les lignes bancaires sans facture restent en souffrance.
3. **Hybride** : le code fait tout ce qui a une réponse exacte ; le modèle ne reçoit que les pièces
   qu'aucune règle ne couvre.

## Décision

Option 3. Sont déterministes : la lecture et la validation des QR-factures (chiffres de contrôle
QRR, ISO 11649, IBAN, cohérence QR-IBAN et référence), la lecture du camt.053, le rapprochement
(par référence, puis par compte et montant exact quand il n'y a qu'un candidat), les onze contrôles,
et le calcul de chaque écriture. L'agent ne voit que la liste `pieces_a_classer`.

## Conséquences

- Sur le mois de démonstration, 13 écritures sur 22 sont proposées sans modèle ; l'agent en classe 9.
- Une pièce bloquée par une anomalie (doublon, TVA incohérente, paiement d'un mauvais montant)
  n'arrive jamais à l'agent : elle part chez une personne.
- Les règles fournisseurs apprises à la validation (ADR 0003) font baisser, mois après mois, la part
  confiée au modèle.
