"""MCP server: the tools an agent (Claude) gets on a client's books.

Six tools. Five only read. The sixth, `proposer_ecriture`, sends a classification (an account, a VAT
code and a reason); the entry itself is built by the ledger and stays « proposée ». There is no tool
to approve or reject: that decision belongs to a person, through the command line (`fidu valider`).

Run: uv run fidu-mcp   (stdio; the database is FIDU_BASE, default ./livres.db, see the README)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import books, ledger

INSTRUCTIONS = """\
Tu aides une fiduciaire suisse à tenir la comptabilité d'un client (plan comptable PME, TVA suisse).
Les factures fournisseurs (QR-factures) et le relevé bancaire (camt.053) sont déjà lus et rapprochés ;
les écritures couvertes par une règle fournisseur sont déjà proposées. Ton travail : classer ce qui reste.

Méthode :
- situation, puis pieces_a_classer pour la liste ; plan_comptable pour les comptes et les codes TVA.
- Pour chaque pièce, proposer_ecriture avec un compte, un code TVA si la pièce n'indique pas sa TVA,
  et une justification d'une phrase qui cite ce qui, dans la pièce, justifie le choix.
- Tu ne calcules aucun montant : le grand livre construit l'écriture et la TVA.
- Si tu hésites entre deux comptes, propose le plus probable et dis ton doute dans la justification.
- Les pièces bloquées par une anomalie ne sont pas pour toi : signale-les, un humain décide.
- Rien de ce que tu proposes n'est comptabilisé tant qu'une personne ne l'a pas validé.
"""

READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
PROPOSE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)


def create_server(db_path: Path | None = None) -> MCPServer:
    path = db_path or Path(os.environ.get("FIDU_BASE", "livres.db"))
    server = MCPServer("fiduciaire", instructions=INSTRUCTIONS)

    def call(fn, *args) -> Any:
        if not path.exists():
            raise ToolError(
                f"base {path} absente : charger d'abord les pièces (fidu demo ou fidu charger)"
            )
        db = books.connect(path)
        try:
            return fn(db, *args)
        except (
            books.BooksError
        ) as exc:  # expected refusals: Claude reads the reason and corrects itself
            raise ToolError(str(exc)) from exc
        finally:
            db.close()

    @server.tool(annotations=READ)
    def situation() -> dict[str, Any]:
        """Vue d'ensemble : pièces lues, paiements rapprochés, anomalies, écritures par statut, pièces à classer."""
        return call(books.overview)

    @server.tool(annotations=READ)
    def pieces_a_classer() -> dict[str, Any]:
        """Les pièces qu'aucune règle ne couvre : factures de fournisseurs inconnus et lignes bancaires sans facture."""
        items = call(books.items_to_classify)
        return {
            "total": len(items),
            "pieces": [{"piece": i.id, "type": i.kind} | i.facts for i in items],
        }

    @server.tool(annotations=READ)
    def plan_comptable() -> dict[str, Any]:
        """Les comptes utilisables et les codes TVA, avec leurs taux."""
        return {
            "comptes_de_charges": {
                a: ledger.ACCOUNTS[a] for a in sorted(ledger.EXPENSE_ACCOUNTS)
            },
            "comptes_pour_une_entree_d_argent": {
                a: ledger.ACCOUNTS[a] for a in sorted(ledger.INCOME_ACCOUNTS)
            },
            "codes_tva": {
                "TVA81": "8,1 % taux normal",
                "TVA26": "2,6 % taux réduit (denrées alimentaires, livres, médicaments)",
                "TVA38": "3,8 % taux spécial (hébergement)",
                "EXO": "0 % : exclu ou exonéré (loyer, assurances, frais bancaires, encaissement d'un débiteur)",
            },
        }

    @server.tool(annotations=READ)
    def anomalies(regle: str | None = None) -> dict[str, Any]:
        """Les anomalies trouvées par les contrôles, de la plus grave à la moins grave. Filtre facultatif par règle."""
        found = call(books.anomalies, regle)
        return {
            "total": len(found),
            "anomalies": found,
            "regles": {k: v[1] for k, v in books.RULES.items()},
        }

    @server.tool(annotations=READ)
    def expliquer_piece(piece: str) -> dict[str, Any]:
        """Tout sur une pièce : ses données, son rapprochement, ses anomalies et ses écritures."""
        return call(books.explain, piece)

    @server.tool(annotations=PROPOSE)
    def proposer_ecriture(
        piece: str, compte: str, justification: str, code_tva: str | None = None
    ) -> dict[str, Any]:
        """Propose le classement d'une pièce. L'écriture est construite par le grand livre et reste « proposée »
        jusqu'à la décision d'une personne. code_tva : seulement si la pièce n'indique pas sa TVA."""
        return call(books.propose, piece, compte, code_tva, justification)

    return server


def main() -> None:
    create_server().run()


if __name__ == "__main__":
    main()
