# fiduciaire-agent

Pré-comptabilité d'un client de fiduciaire suisse. Les QR-factures et le relevé bancaire camt.053
entrent ; le code lit, vérifie, rapproche et contrôle ; un agent Claude classe par MCP ce qu'aucune
règle ne couvre ; **une personne valide chaque écriture**.

```
 QR-factures (texte du QR) ─┐                         ┌─► écritures proposées ──► fidu valider (une personne)
                            ├─► lecture et contrôles ─┤
 relevé camt.053 ───────────┘   rapprochement         └─► pièces à classer ──► agent Claude (MCP, 6 outils)
                                règles fournisseurs                               └─► proposer_ecriture
```

Le partage du travail est le cœur du projet :

| Qui | Fait quoi |
|---|---|
| **Le code** | Lit et valide les QR-factures (chiffres de contrôle QRR, ISO 11649, IBAN, cohérence QR-IBAN et référence, bloc TVA Swico S1), lit le camt.053, rapproche les paiements, lance onze contrôles, **construit toutes les écritures** |
| **L'agent** | Classe les pièces qu'aucune règle ne couvre : un compte, un code TVA si la pièce n'en porte pas, une justification. Il ne calcule aucun montant |
| **Une personne** | Valide ou rejette chaque écriture. Aucun outil donné à l'agent ne peut valider |

Les raisons de ce partage, et les options écartées, sont dans [`docs/adr/`](docs/adr).

## Ce qui est réel, ce qui est simulé

| | |
|---|---|
| Formats | **Réels** : charge utile de la QR-facture suisse (SIX, version 0200), bloc Swico S1, relevé ISO 20022 camt.053 (versions .04 et .08). Les chiffres de contrôle sont vérifiés contre les exemples publiés par SIX et ISO |
| TVA | Taux suisses en vigueur depuis le 1<sup>er</sup> janvier 2024 : 8,1 %, 2,6 %, 3,8 % |
| Plan comptable | Un **sous-ensemble** inspiré du plan comptable suisse PME, dans un seul dictionnaire (`ledger.ACCOUNTS`). Un vrai mandat utilise le plan du client |
| Données | **Fictives** : un mois (septembre 2026) d'un client inventé, 13 QR-factures et un relevé de 15 lignes. Tous les noms portent « Démo » ; les IBAN sont calculés, pas relevés |
| Agent | **Deux vrais essais**, avec Claude Opus 5.5 et Claude Sonnet 5 : voir [`docs/essais.md`](docs/essais.md) |

Le code lit le **texte** du QR code, pas l'image : décoder l'image est un problème résolu par
n'importe quelle bibliothèque de lecture, et ce qui compte pour une fiduciaire vient après.

## Démarrer

Prérequis : [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run fidu demo                        # écrit le mois de démonstration et le charge
uv run fidu anomalies                   # les 7 anomalies plantées
uv run fidu proposees                   # 13 écritures proposées par les règles et le rapprochement
uv run fidu valider --origine rapprochement
uv run fidu a-classer                   # les 9 pièces pour l'agent
uv run fidu classer F-hotel-7730 6640 --justification "Nuitées d'un séminaire client"
uv run fidu valider 14 --retenir        # un classement validé devient une règle fournisseur
uv run fidu evaluer                     # compare les classements au corrigé
uv run pytest -q
```

## Brancher Claude

Claude Desktop (`claude_desktop_config.json`) :

```json
{
  "mcpServers": {
    "fiduciaire": {
      "command": "uv",
      "args": ["run", "--project", "/chemin/vers/fiduciaire-agent", "fidu-mcp"],
      "env": { "FIDU_BASE": "/chemin/vers/livres.db" }
    }
  }
}
```

Claude Code, en tâche de fond : la commande exacte des essais est dans [`docs/essais.md`](docs/essais.md).

Les six outils : `situation`, `pieces_a_classer`, `plan_comptable`, `anomalies`, `expliquer_piece`
(lecture seule) et `proposer_ecriture`. Un refus du serveur (compte qui n'est pas un compte de
charges, code TVA contraire à la facture, pièce bloquée) revient à Claude comme une erreur lisible,
qu'il lit pour se corriger.

## Les contrôles

| Contrôle | Gravité | Planté dans la démo |
|---|---|---|
| QR-facture refusée à la lecture (ici : chiffre de contrôle de la référence) | haute | 1 |
| TVA de la facture incohérente avec son montant | haute | 1 |
| Facture reçue deux fois | haute | 1 |
| Facture payée deux fois | haute | 1 |
| Paiement d'un montant différent de la facture | haute | 1 |
| Paiement avec une référence qu'aucune facture ne porte | moyenne | 1 |
| Facture échue et impayée à la date du relevé | moyenne | 1 |
| QR-facture sans montant | moyenne | testé à part |
| Relevé incomplet : les soldes ne se raccordent pas | haute | testé à part |
| Paiement d'une facture elle-même en anomalie | moyenne | testé à part |
| Paiement qui correspond à plusieurs factures (sans référence) | moyenne | testé à part |

`tests/test_books.py` exige que les contrôles retrouvent **les sept anomalies plantées, et rien
d'autre** ; `tests/test_edge_cases.py` couvre les autres. Une pièce en anomalie ne reçoit aucune écriture automatique et n'est pas proposée à
l'agent, sauf la facture échue, qui reste une dette à comptabiliser.

## Ce que les relectures ont changé

- Le **premier essai de l'agent** a trouvé une facture sans date mal datée : corrigé.
- Une **relecture de code indépendante** (un second agent, consigne : justesse seulement) a trouvé
  neuf défauts, tous reproduits puis corrigés, chacun avec un test dans `tests/test_edge_cases.py`.
  Les plus sérieux : une même référence QR chez deux fournisseurs créait un faux « payée deux fois »
  (une référence QR n'est unique que pour un compte créancier) ; un second paiement identique sans
  référence passait inaperçu et doublait la charge et l'impôt préalable ; un rejet était annulé au
  chargement suivant.

## Limites

- Un seul client, une seule devise comptable (CHF) : une pièce en EUR est refusée avec une raison,
  à traiter à la main.
- Les ventes ne sont pas suivies : un encaissement client est classé, pas rapproché d'une facture
  de vente.
- Sans date de réception, le doublon gardé comme original est le premier dans l'ordre des noms.
- camt.053 : seules les écritures comptabilisées (BOOK) sont lues ; les contre-passations et les
  frais déduits d'une écriture groupée ne sont pas encore traités.
- Serveur MCP en stdio : un poste, un utilisateur, pas d'authentification (voir l'ADR 0004).
- Aucun export vers un logiciel comptable. Le journal validé est lisible (`fidu journal`), pas
  encore exporté.
- Une facture qui n'indique pas sa TVA n'est pas encore signalée comme risque sur l'impôt préalable
  (relevé par l'agent lors du premier essai).

## Code

| Module | Rôle |
|---|---|
| `qrbill.py` | QR-facture : lecture, validation, bloc Swico S1 |
| `camt.py` | Relevé camt.053, écritures groupées découpées par transaction |
| `ledger.py` | Plan comptable, codes TVA, construction et invariants des écritures |
| `books.py` | Ingestion, rapprochement, contrôles, propositions, validation, évaluation (SQLite) |
| `mcp_server.py` | Les six outils de l'agent |
| `cli.py` | La ligne de commande du comptable |
| `demo.py` | Le mois de démonstration et son corrigé |
