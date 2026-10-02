"""The accountant's command line: load documents, read controls, and decide on every entry."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import books, demo, runlog


def _print(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _entry_line(e: dict) -> str:
    lines = "  ".join(
        f"{ln['compte']} {'D' if ln['debit'] != '0.00' else 'C'} {ln['debit'] if ln['debit'] != '0.00' else ln['credit']}"
        for ln in e["lignes"]
    )
    return f"#{e['ecriture']:<4} {e['origine']:<13} {e['piece']:<32} {lines}\n      {e['justification']}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="fidu", description="Pré-comptabilité d'un client de fiduciaire."
    )
    p.add_argument(
        "--base", type=Path, default=Path(os.environ.get("FIDU_BASE", "livres.db"))
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo", help="écrit le mois de démonstration et le charge")
    d.add_argument("dossier", type=Path, nargs="?", default=Path("donnees/demo"))
    sub.add_parser(
        "charger", help="lit factures/, banque/ et regles.json d'un dossier"
    ).add_argument("dossier", type=Path)
    sub.add_parser("situation")
    sub.add_parser("anomalies")
    sub.add_parser("a-classer", help="les pièces qu'aucune règle ne couvre")
    sub.add_parser("proposees", help="les écritures en attente de décision")
    sub.add_parser("journal", help="les écritures validées")
    v = sub.add_parser("valider", help="valider des écritures proposées")
    v.add_argument("ids", type=int, nargs="*")
    v.add_argument(
        "--origine",
        choices=["regle", "rapprochement"],
        help="valider toutes celles de cette origine",
    )
    v.add_argument(
        "--retenir",
        action="store_true",
        help="faire d'un classement de facture une règle fournisseur",
    )
    r = sub.add_parser("rejeter")
    r.add_argument("id", type=int)
    r.add_argument("--motif", required=True)
    c = sub.add_parser("classer", help="classer une pièce soi-même")
    c.add_argument("piece")
    c.add_argument("compte")
    c.add_argument("--tva")
    c.add_argument("--justification", required=True)
    sub.add_parser(
        "evaluer", help="comparer les classements au corrigé du mois de démonstration"
    )
    t = sub.add_parser(
        "essai",
        help="garder la transcription stream-json d'un essai de l'agent et ajouter sa ligne au journal",
    )
    t.add_argument("transcription", type=Path)
    t.add_argument("--dossier", type=Path, default=Path("docs/runs"))
    a = p.parse_args(argv)

    try:
        if a.cmd == "demo":
            demo.write(a.dossier)
            if a.base.exists():
                a.base.unlink()  # the demo starts from a clean slate, decisions included
            db = books.connect(a.base)
            _print(books.ingest(db, a.dossier))
            return 0
        if not a.base.exists():
            raise books.BooksError(
                f"base {a.base} absente : lancer d'abord fidu demo ou fidu charger"
            )
        db = books.connect(a.base)
        if a.cmd == "charger":
            _print(books.ingest(db, a.dossier))
        elif a.cmd == "situation":
            _print(books.overview(db))
        elif a.cmd == "anomalies":
            for x in books.anomalies(db):
                print(
                    f"{x['gravite']:<8} {x['regle']:<18} {x['piece']:<32} {x['constat']}"
                )
        elif a.cmd == "a-classer":
            for i in books.items_to_classify(db):
                print(i.id, json.dumps(i.facts, ensure_ascii=False))
        elif a.cmd == "proposees":
            for e in books.entries(db, "proposed"):
                print(_entry_line(e))
        elif a.cmd == "journal":
            for e in books.entries(db, "approved"):
                print(_entry_line(e))
        elif a.cmd == "valider":
            origin = {"regle": "règle", "rapprochement": "rapprochement"}.get(
                a.origine or ""
            )
            ids = a.ids + [
                e["ecriture"]
                for e in books.entries(db, "proposed")
                if origin and e["origine"] == origin
            ]
            ids = list(dict.fromkeys(ids))  # an id given and also picked by --origine
            if not ids:
                raise books.BooksError(
                    "rien à valider : donner des numéros d'écriture ou --origine"
                )
            print(
                f"{books.approve(db, ids, remember=a.retenir)} écriture(s) validée(s)"
            )
        elif a.cmd == "rejeter":
            books.reject(db, a.id, a.motif)
            print(f"écriture {a.id} rejetée")
        elif a.cmd == "classer":
            print(
                _entry_line(
                    books.propose(
                        db, a.piece, a.compte, a.tva, a.justification, origin="human"
                    )
                )
            )
        elif a.cmd == "evaluer":
            score = books.evaluate(db, demo.EXPECTED_CLASSIFICATION)
            for row in score["detail"]:
                got = row["obtenu"] or {}
                mark = "ok " if row["juste"] else "NON"
                print(
                    f"{mark} {row['piece']:<24} attendu {row['attendu']}  obtenu {got}"
                )
            print(f"{score['justes']}/{score['total']} justes")
        elif a.cmd == "essai":
            score = books.evaluate(db, demo.EXPECTED_CLASSIFICATION)
            try:
                _print(runlog.record(a.transcription, a.dossier, score))
            except (OSError, ValueError) as exc:
                raise books.BooksError(f"essai non consigné : {exc}") from exc
    except books.BooksError as exc:
        print(f"refusé : {exc}", file=sys.stderr)
        return 1
    return 0
