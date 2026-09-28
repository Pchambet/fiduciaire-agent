"""The books of one client: ingestion, reconciliation, controls, proposals and human validation.

The division of labour is the point of the design (see docs/adr):
  - deterministic code reads the documents, matches payments, runs the controls and builds every
    entry, so numbers are never produced by a language model;
  - the agent only classifies what the rules cannot (an account and a VAT code, with a reason);
  - a person approves or rejects every entry. No tool given to the agent can approve.

State lives in one SQLite file. `ingest` rebuilds the documents, matches and anomalies from the
input folder at every run; entries and supplier rules are decisions, so they are kept.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import camt, ledger, qrbill
from .ledger import EntryError

DEFAULT_PAYMENT_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoice (
  id TEXT PRIMARY KEY, file TEXT, creditor TEXT, iban TEXT, amount TEXT, currency TEXT,
  ref_type TEXT, reference TEXT, number TEXT, invoice_date TEXT, due_date TEXT,
  vat TEXT, vat_number TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS bank_line (
  id TEXT PRIMARY KEY, booking_date TEXT, amount TEXT, currency TEXT, credit INTEGER,
  reference TEXT, counterparty TEXT, counterparty_iban TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS match (bank_id TEXT PRIMARY KEY, invoice_id TEXT, method TEXT);
CREATE TABLE IF NOT EXISTS anomaly (
  id TEXT PRIMARY KEY, rule TEXT, severity TEXT, item_id TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS entry (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, kind TEXT, origin TEXT, status TEXT,
  account TEXT, vat_code TEXT, rationale TEXT, entry_date TEXT, label TEXT, lines TEXT,
  created_at TEXT, decided_at TEXT, note TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_entry ON entry(item_id, kind) WHERE status != 'rejected';
CREATE TABLE IF NOT EXISTS rule (iban TEXT PRIMARY KEY, account TEXT, vat_code TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Rules, with the severity and the person who acts on them in a fiduciary.
RULES: dict[str, tuple[str, str]] = {
    "qr_invalid": ("haute", "QR-facture refusée à la lecture"),
    "vat_inconsistent": ("haute", "TVA de la facture incohérente avec son montant"),
    "amount_missing": ("moyenne", "QR-facture sans montant"),
    "duplicate_invoice": ("haute", "facture reçue deux fois"),
    "duplicate_payment": ("haute", "facture payée deux fois"),
    "amount_mismatch": ("haute", "paiement d'un montant différent de la facture"),
    "unknown_reference": (
        "moyenne",
        "paiement avec une référence qu'aucune facture ne porte",
    ),
    "invoice_on_hold": ("moyenne", "paiement d'une facture elle-même en anomalie"),
    "ambiguous_payment": ("moyenne", "paiement qui correspond à plusieurs factures"),
    "unpaid_overdue": ("moyenne", "facture échue et impayée à la date du relevé"),
    "statement_balance": (
        "haute",
        "relevé incomplet : les soldes ne se raccordent pas",
    ),
}


ORIGINS = {
    "rule": "règle",
    "match": "rapprochement",
    "agent": "agent",
    "human": "comptable",
}

# An overdue invoice is still a debt to book: the only anomaly that does not hold its document back.
NON_BLOCKING = {"unpaid_overdue"}


class BooksError(ValueError):
    """An expected refusal. The message is for the user (or the agent) and says what to do."""


@dataclass(frozen=True)
class Item:
    """Something that needs an entry: a supplier invoice or an unmatched bank line."""

    id: str
    kind: str  # "invoice" or "bank"
    facts: dict[str, Any]


def connect(path: Path | str) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


GENEVA = ZoneInfo("Europe/Zurich")


def _now() -> str:
    return datetime.now(GENEVA).isoformat(timespec="seconds")


# --- ingestion -----------------------------------------------------------------------------------


def ingest(db: sqlite3.Connection, folder: Path) -> dict[str, int]:
    """Read `folder/factures/*.txt` (QR payloads), `folder/banque/*.xml` (camt.053) and
    `folder/regles.json` (known suppliers), rebuild everything derived, propose what rules allow."""
    with db:
        for table in ("invoice", "bank_line", "match", "anomaly"):
            db.execute(f"DELETE FROM {table}")
        _load_rules(db, folder / "regles.json")
        _load_invoices(db, sorted((folder / "factures").glob("*.txt")))
        closing = _load_statements(db, sorted((folder / "banque").glob("*.xml")))
        _reconcile(db)
        _overdue(db, closing)
        _propose_from_rules(db)
    return overview(db)["documents"]


def _anomaly(db: sqlite3.Connection, rule: str, item_id: str, message: str) -> None:
    db.execute(
        "INSERT OR REPLACE INTO anomaly VALUES (?,?,?,?,?)",
        (f"{rule}:{item_id}", rule, RULES[rule][0], item_id, message),
    )


def _load_rules(db: sqlite3.Connection, path: Path) -> None:
    if path.exists():
        for r in json.loads(path.read_text(encoding="utf-8")):
            db.execute(
                "INSERT OR IGNORE INTO rule VALUES (?,?,?,?)",
                (r["iban"], r["compte"], r.get("code_tva"), "fichier regles.json"),
            )


def _load_invoices(db: sqlite3.Connection, files: list[Path]) -> None:
    for f in files:
        item_id = f"F-{f.stem}"
        try:
            bill = qrbill.parse(f.read_text(encoding="utf-8"))
        except qrbill.QrBillError as exc:
            _anomaly(db, "qr_invalid", item_id, f"{f.name} : {exc}")
            continue
        info = bill.bill_info
        vat = (
            [
                [str(p.rate), None if p.net is None else str(p.net)]
                for p in info.vat_parts
            ]
            if info
            else []
        )
        inv_date = info.invoice_date if info else None
        days = (info.payment_days if info else None) or DEFAULT_PAYMENT_DAYS
        db.execute(
            "INSERT INTO invoice VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item_id,
                f.name,
                bill.creditor.name,
                bill.iban,
                None if bill.amount is None else str(bill.amount),
                bill.currency,
                bill.reference_type,
                bill.reference,
                info.invoice_number if info else None,
                inv_date.isoformat() if inv_date else None,
                (inv_date + timedelta(days=days)).isoformat() if inv_date else None,
                json.dumps(vat) if vat else None,
                info.vat_number if info else None,
                bill.message,
            ),
        )
        if bill.amount is None:
            _anomaly(
                db,
                "amount_missing",
                item_id,
                f"{bill.creditor.name} : montant laissé en blanc",
            )
        elif vat:
            try:
                ledger.split_vat(
                    bill.amount,
                    [(Decimal(r), None if n is None else Decimal(n)) for r, n in vat],
                )
            except EntryError as exc:
                _anomaly(
                    db, "vat_inconsistent", item_id, f"{bill.creditor.name} : {exc}"
                )

    # A second copy of the same bill: same creditor account and same reference (or invoice number).
    # With no reception date, the first document in name order is kept as the original.
    seen: dict[tuple[str, str], str] = {}
    for inv in db.execute("SELECT * FROM invoice ORDER BY id").fetchall():
        key = (inv["iban"], inv["reference"] or inv["number"] or inv["id"])
        if key in seen:
            _anomaly(
                db,
                "duplicate_invoice",
                inv["id"],
                f"{inv['creditor']} : même facture que {seen[key]}, gardée comme originale",
            )
        else:
            seen[key] = inv["id"]


def _load_statements(db: sqlite3.Connection, files: list[Path]) -> date | None:
    closing = None
    for f in files:
        try:
            statements = camt.parse(f.read_bytes())
        except camt.CamtError as exc:
            raise BooksError(f"{f.name} : {exc}") from exc
        for k, st in enumerate(statements, 1):
            closing = _load_statement(db, f, k, st, closing)
    if closing:
        db.execute(
            "INSERT OR REPLACE INTO meta VALUES ('closing_date', ?)",
            (closing.isoformat(),),
        )
    return closing


def _load_statement(
    db: sqlite3.Connection, f: Path, k: int, st: camt.Statement, closing: date | None
) -> date:
    piece = f"R-{f.stem}" if k == 1 else f"R-{f.stem}-{k}"
    gap = st.balance_gap()
    if gap:
        _anomaly(
            db,
            "statement_balance",
            piece,
            f"{f.name} ({st.iban}) : écart de {gap} entre soldes et mouvements",
        )
    for ln in st.lines:
        line_id = f"B-{ln.id}"
        if db.execute("SELECT 1 FROM bank_line WHERE id = ?", (line_id,)).fetchone():
            raise BooksError(
                f"{f.name} : la ligne {ln.id} a déjà été lue, relevé chargé deux fois ?"
            )
        db.execute(
            "INSERT INTO bank_line VALUES (?,?,?,?,?,?,?,?,?)",
            (
                line_id,
                ln.booking_date.isoformat(),
                str(ln.amount),
                ln.currency,
                int(ln.credit),
                ln.reference,
                ln.counterparty,
                ln.counterparty_iban,
                ln.text,
            ),
        )
    return max(closing or st.closing_date, st.closing_date)


def _blocked(db: sqlite3.Connection) -> set[str]:
    """Documents held back for a person: no automatic entry, not offered to the agent."""
    rows = db.execute("SELECT item_id, rule FROM anomaly")
    return {r["item_id"] for r in rows if r["rule"] not in NON_BLOCKING}


def _reconcile(db: sqlite3.Connection) -> None:
    """Match each debit to a bill: by reference and payee account, else by payee account,
    currency and exact amount when a single open bill fits. Whatever cannot be matched
    cleanly becomes an anomaly or goes to classification, never a guess."""
    blocked = _blocked(db)
    invoices = db.execute("SELECT * FROM invoice ORDER BY id").fetchall()
    paid: dict[str, str] = {}
    lines = db.execute(
        "SELECT * FROM bank_line WHERE credit = 0 ORDER BY booking_date, id"
    ).fetchall()
    for ln in lines:
        amount = Decimal(ln["amount"])
        payee = ln["counterparty_iban"]
        if ln["reference"]:
            # A QR reference is unique for one creditor account only: compare both.
            hits = [
                i
                for i in invoices
                if i["reference"] == ln["reference"]
                and (not payee or i["iban"] == payee)
            ]
            hits.sort(
                key=lambda i: i["id"] in blocked
            )  # the original before its copies
            if not hits:
                _anomaly(
                    db,
                    "unknown_reference",
                    ln["id"],
                    f"{ln['counterparty']} : référence {ln['reference']}",
                )
                continue
            inv = hits[0]
            if inv["id"] in blocked:
                _anomaly(
                    db,
                    "invoice_on_hold",
                    ln["id"],
                    f"{inv['creditor']} : paiement de {inv['id']}, elle-même en anomalie",
                )
            elif inv["id"] in paid:
                _anomaly(
                    db,
                    "duplicate_payment",
                    ln["id"],
                    f"{inv['creditor']} : déjà payée par {paid[inv['id']]}",
                )
            elif (Decimal(inv["amount"]), inv["currency"]) != (amount, ln["currency"]):
                _anomaly(
                    db,
                    "amount_mismatch",
                    ln["id"],
                    f"{inv['creditor']} : facture {inv['amount']} {inv['currency']}, "
                    f"payé {amount} {ln['currency']}",
                )
            else:
                paid[inv["id"]] = ln["id"]
                db.execute(
                    "INSERT INTO match VALUES (?,?,?)",
                    (ln["id"], inv["id"], "reference"),
                )
            continue
        fits = [
            i
            for i in invoices
            if i["id"] not in blocked
            and payee
            and i["iban"] == payee
            and i["currency"] == ln["currency"]
            and Decimal(i["amount"]) == amount
        ]
        open_bills = [i for i in fits if i["id"] not in paid]
        if len(open_bills) == 1:
            paid[open_bills[0]["id"]] = ln["id"]
            db.execute(
                "INSERT INTO match VALUES (?,?,?)",
                (ln["id"], open_bills[0]["id"], "iban_montant"),
            )
        elif open_bills:
            ids = ", ".join(i["id"] for i in open_bills)
            _anomaly(
                db,
                "ambiguous_payment",
                ln["id"],
                f"{ln['counterparty']} {amount} : plusieurs factures possibles ({ids})",
            )
        elif fits:
            first = fits[0]
            _anomaly(
                db,
                "duplicate_payment",
                ln["id"],
                f"{first['creditor']} : même compte et même montant que {first['id']}, "
                f"déjà payée par {paid[first['id']]}",
            )


def _overdue(db: sqlite3.Connection, closing: date | None) -> None:
    if closing is None:
        return
    blocked = _blocked(db)
    rows = db.execute(
        "SELECT * FROM invoice WHERE due_date < ? AND id NOT IN (SELECT invoice_id FROM match)",
        (closing.isoformat(),),
    )
    for inv in rows.fetchall():
        if inv["id"] not in blocked:
            _anomaly(
                db,
                "unpaid_overdue",
                inv["id"],
                f"{inv['creditor']} {inv['amount']} : échue le {inv['due_date']}",
            )


def _propose_from_rules(db: sqlite3.Connection) -> None:
    """Propose what rules and matches allow, once: a rejected proposal is not proposed again."""

    def ever(item_id: str, column: str, value: str) -> bool:
        sql = f"SELECT 1 FROM entry WHERE item_id = ? AND {column} = ?"
        return db.execute(sql, (item_id, value)).fetchone() is not None

    for item in items_to_classify(db):
        if item.kind != "invoice" or ever(item.id, "origin", "rule"):
            continue
        r = db.execute(
            "SELECT * FROM rule WHERE iban = ?", (item.facts["iban"],)
        ).fetchone()
        # A rule that does not fit this bill (e.g. no VAT code for a bill without S1) proposes
        # nothing: the bill stays in the list to classify, visible to the agent and to a person.
        if r:
            with contextlib.suppress(BooksError):
                source = f"règle fournisseur ({r['source']})"
                _insert_entry(db, item, r["account"], r["vat_code"], source, "rule")
    for m in db.execute("SELECT * FROM match").fetchall():
        if ever(m["bank_id"], "kind", "payment"):
            continue
        inv = db.execute(
            "SELECT * FROM invoice WHERE id = ?", (m["invoice_id"],)
        ).fetchone()
        ln = db.execute(
            "SELECT * FROM bank_line WHERE id = ?", (m["bank_id"],)
        ).fetchone()
        label = f"Paiement {inv['creditor']} {inv['number'] or inv['reference']}"
        entry = ledger.payment(
            date.fromisoformat(ln["booking_date"]), label, Decimal(ln["amount"])
        )
        why = f"rapproché par {m['method']}"
        _store(db, m["bank_id"], "payment", "match", None, None, why, entry)


# --- reading -------------------------------------------------------------------------------------


def _undated_bill_date(db: sqlite3.Connection, invoice_id: str) -> str:
    """A bill without a date takes the date it was paid, else the statement date."""
    paid = db.execute(
        "SELECT b.booking_date FROM match m JOIN bank_line b ON b.id = m.bank_id WHERE m.invoice_id = ?",
        (invoice_id,),
    ).fetchone()
    return paid[0] if paid else _closing_date(db)


def _closing_date(db: sqlite3.Connection) -> str:
    row = db.execute("SELECT value FROM meta WHERE key = 'closing_date'").fetchone()
    if row is None:
        raise BooksError(
            "aucun relevé bancaire chargé : la date de l'écriture est inconnue"
        )
    return row[0]


def _live_entry(db: sqlite3.Connection, item_id: str, kind: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM entry WHERE item_id = ? AND kind = ? AND status != 'rejected'",
        (item_id, kind),
    ).fetchone()


def _rejected_only(db: sqlite3.Connection, item_id: str, kind: str) -> bool:
    rows = db.execute(
        "SELECT status FROM entry WHERE item_id = ? AND kind = ?", (item_id, kind)
    ).fetchall()
    return bool(rows) and all(r["status"] == "rejected" for r in rows)


def _invoice_facts(inv: sqlite3.Row) -> dict[str, Any]:
    vat = json.loads(inv["vat"]) if inv["vat"] else None
    return {
        "fournisseur": inv["creditor"],
        "iban": inv["iban"],
        "montant": inv["amount"],
        "devise": inv["currency"],
        "numero": inv["number"],
        "date": inv["invoice_date"],
        "message": inv["message"],
        "tva_de_la_facture": [{"taux": r, "net": n} for r, n in vat]
        if vat
        else "non indiquée : code TVA à choisir",
    }


def items_to_classify(db: sqlite3.Connection) -> list[Item]:
    """Invoices without a rule and bank lines without a match: what needs a classification."""
    blocked = _blocked(db)
    items = []
    for inv in db.execute("SELECT * FROM invoice ORDER BY id"):
        if inv["id"] not in blocked and not _live_entry(db, inv["id"], "invoice"):
            items.append(Item(inv["id"], "invoice", _invoice_facts(inv)))
    # A matched line leaves the list, unless a person rejected its payment entry.
    matched = {
        r["bank_id"]
        for r in db.execute("SELECT bank_id FROM match")
        if not _rejected_only(db, r["bank_id"], "payment")
    }
    for ln in db.execute("SELECT * FROM bank_line ORDER BY booking_date, id"):
        if ln["id"] in matched or ln["id"] in blocked:
            continue
        if not _live_entry(db, ln["id"], "bank"):
            facts = {
                "date": ln["booking_date"],
                "sens": "entrée" if ln["credit"] else "sortie",
                "montant": ln["amount"],
                "devise": ln["currency"],
                "contrepartie": ln["counterparty"],
                "texte": ln["text"],
                "reference": ln["reference"],
            }
            items.append(Item(ln["id"], "bank", facts))
    return items


def _entry_dict(e: sqlite3.Row) -> dict[str, Any]:
    return {
        "ecriture": e["id"],
        "piece": e["item_id"],
        "statut": {
            "proposed": "proposée",
            "approved": "validée",
            "rejected": "rejetée",
        }[e["status"]],
        "origine": ORIGINS[e["origin"]],
        "date": e["entry_date"],
        "libelle": e["label"],
        "compte": e["account"],
        "code_tva": e["vat_code"],
        "justification": e["rationale"],
        "lignes": json.loads(e["lines"]),
        "note": e["note"],
    }


def entries(db: sqlite3.Connection, status: str | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM entry", ()
    if status:
        sql, args = sql + " WHERE status = ?", (status,)
    return [_entry_dict(e) for e in db.execute(sql + " ORDER BY id", args)]


def anomalies(db: sqlite3.Connection, rule: str | None = None) -> list[dict[str, str]]:
    sql, args = "SELECT * FROM anomaly", ()
    if rule:
        sql, args = sql + " WHERE rule = ?", (rule,)
    order = " ORDER BY CASE severity WHEN 'haute' THEN 0 ELSE 1 END, rule, item_id"
    return [
        {
            "regle": a["rule"],
            "gravite": a["severity"],
            "piece": a["item_id"],
            "constat": a["message"],
        }
        for a in db.execute(sql + order, args)
    ]


def overview(db: sqlite3.Connection) -> dict[str, Any]:
    def count(sql: str) -> int:
        return db.execute(sql).fetchone()[0]

    by_status = dict(
        db.execute("SELECT status, COUNT(*) FROM entry GROUP BY status").fetchall()
    )
    return {
        "documents": {
            "factures": count("SELECT COUNT(*) FROM invoice"),
            "lignes_bancaires": count("SELECT COUNT(*) FROM bank_line"),
            "paiements_rapproches": count("SELECT COUNT(*) FROM match"),
            "anomalies": count("SELECT COUNT(*) FROM anomaly"),
        },
        "a_classer": len(items_to_classify(db)),
        "ecritures": {
            "proposees": by_status.get("proposed", 0),
            "validees": by_status.get("approved", 0),
            "rejetees": by_status.get("rejected", 0),
        },
        "date_du_releve": (
            db.execute("SELECT value FROM meta WHERE key = 'closing_date'").fetchone()
            or [None]
        )[0],
    }


def explain(db: sqlite3.Connection, item_id: str) -> dict[str, Any]:
    inv = db.execute("SELECT * FROM invoice WHERE id = ?", (item_id,)).fetchone()
    ln = db.execute("SELECT * FROM bank_line WHERE id = ?", (item_id,)).fetchone()
    found = [a for a in anomalies(db) if a["piece"] == item_id]
    if not (inv or ln or found):
        raise BooksError(f"pièce inconnue : {item_id}")
    out: dict[str, Any] = {"piece": item_id, "anomalies": found}
    if inv:
        out["facture"] = _invoice_facts(inv) | {
            "reference": inv["reference"],
            "echeance": inv["due_date"],
        }
        m = db.execute(
            "SELECT * FROM match WHERE invoice_id = ?", (item_id,)
        ).fetchone()
        out["paiement"] = dict(m) if m else None
    if ln:
        out["ligne_bancaire"] = dict(ln) | {"credit": bool(ln["credit"])}
        m = db.execute("SELECT * FROM match WHERE bank_id = ?", (item_id,)).fetchone()
        out["facture_rapprochee"] = m["invoice_id"] if m else None
    out["ecritures"] = [
        _entry_dict(e)
        for e in db.execute("SELECT * FROM entry WHERE item_id = ?", (item_id,))
    ]
    return out


# --- decisions -----------------------------------------------------------------------------------


def _store(
    db: sqlite3.Connection,
    item_id: str,
    kind: str,
    origin: str,
    account: str | None,
    vat_code: str | None,
    rationale: str,
    entry: ledger.Entry,
) -> int:
    lines = [
        {"compte": ln.account, "debit": f"{ln.debit:.2f}", "credit": f"{ln.credit:.2f}"}
        for ln in entry.lines
    ]
    cur = db.execute(
        "INSERT INTO entry (item_id, kind, origin, status, account, vat_code, rationale, entry_date, label,"
        " lines, created_at) VALUES (?,?,?,'proposed',?,?,?,?,?,?,?)",
        (item_id, kind, origin, account, vat_code, rationale, entry.date.isoformat(), entry.label,
         json.dumps(lines), _now()),
    )  # fmt: skip
    return int(cur.lastrowid or 0)


def _shares(
    gross: Decimal, invoice_vat: list | None, vat_code: str | None
) -> tuple[list[ledger.VatShare], str]:
    if invoice_vat:
        parts = [
            (Decimal(r), None if n is None else Decimal(n)) for r, n in invoice_vat
        ]
        if vat_code is not None and (
            len(parts) > 1 or ledger.VAT_CODES.get(vat_code) != parts[0][0]
        ):
            rates = ", ".join(f"{r} %" for r, _ in parts)
            raise BooksError(
                f"la facture indique elle-même sa TVA ({rates}) : ne pas passer de code_tva"
            )
        return ledger.split_vat(gross, parts), "S1"
    if vat_code is None:
        raise BooksError(f"code_tva obligatoire, parmi {', '.join(ledger.VAT_CODES)}")
    if vat_code not in ledger.VAT_CODES:
        raise BooksError(
            f"code_tva inconnu : {vat_code} (attendus : {', '.join(ledger.VAT_CODES)})"
        )
    return ledger.split_vat(gross, [(ledger.VAT_CODES[vat_code], None)]), vat_code


def _insert_entry(
    db: sqlite3.Connection,
    item: Item,
    account: str,
    vat_code: str | None,
    rationale: str,
    origin: str,
) -> int:
    f = item.facts
    if f["devise"] != "CHF":
        raise BooksError(
            f"{item.id} est en {f['devise']} : conversion non prise en charge, à traiter à la main"
        )
    gross = Decimal(f["montant"])
    invoice_vat = [[v["taux"], v["net"]] for v in f["tva_de_la_facture"]] if item.kind == "invoice" and isinstance(
        f["tva_de_la_facture"], list
    ) else None  # fmt: skip
    try:
        shares, code = _shares(gross, invoice_vat, vat_code)
        if item.kind == "invoice":
            on = date.fromisoformat(f["date"] or _undated_bill_date(db, item.id))
            label = f"Facture {f['fournisseur']} {f['numero'] or ''}".strip()
            entry = ledger.expense(on, label, gross, account, shares, ledger.PAYABLES)
        elif f["sens"] == "sortie":
            entry = ledger.expense(
                date.fromisoformat(f["date"]), f"{f['contrepartie']} {f['texte']}".strip(), gross, account, shares,
                ledger.BANK,
            )  # fmt: skip
        else:
            label = f"{f['contrepartie']} {f['texte']}".strip()
            entry = ledger.income(
                date.fromisoformat(f["date"]), label, gross, account, shares
            )
    except EntryError as exc:
        raise BooksError(str(exc)) from exc
    return _store(db, item.id, item.kind, origin, account, code, rationale, entry)


def propose(
    db: sqlite3.Connection,
    item_id: str,
    account: str,
    vat_code: str | None,
    rationale: str,
    origin: str = "agent",
) -> dict:
    """A classification, turned into an entry by the ledger. It stays proposed until a person decides.
    This is the agent's only write; an accountant can use it too (origin "human")."""
    if len(rationale.strip()) < 10:
        raise BooksError(
            "justification obligatoire : dire en une phrase pourquoi ce compte et ce code TVA"
        )
    item = next((i for i in items_to_classify(db) if i.id == item_id), None)
    if item is None:
        detail = explain(db, item_id)  # raises for an unknown id
        holding = [a for a in detail["anomalies"] if a["regle"] not in NON_BLOCKING]
        if holding:
            raise BooksError(
                f"{item_id} est bloquée par une anomalie ({holding[0]['regle']}) : à un humain"
            )
        raise BooksError(
            f"{item_id} a déjà une écriture proposée ou validée, ou n'en demande pas"
        )
    with db:
        entry_id = _insert_entry(db, item, account, vat_code, rationale.strip(), origin)
    return _entry_dict(
        db.execute("SELECT * FROM entry WHERE id = ?", (entry_id,)).fetchone()
    )


def approve(
    db: sqlite3.Connection, entry_ids: list[int], remember: bool = False, note: str = ""
) -> int:
    """A person validates. With `remember`, an approved invoice classification becomes a supplier rule."""
    with db:
        n = 0
        for eid in entry_ids:
            e = db.execute("SELECT * FROM entry WHERE id = ?", (eid,)).fetchone()
            if e is None or e["status"] != "proposed":
                raise BooksError(f"écriture {eid} introuvable ou déjà décidée")
            db.execute(
                "UPDATE entry SET status = 'approved', decided_at = ?, note = ? WHERE id = ?",
                (_now(), note, eid),
            )
            n += 1
            if (
                remember
                and e["kind"] == "invoice"
                and e["origin"] in ("agent", "human")
            ):
                iban = db.execute(
                    "SELECT iban FROM invoice WHERE id = ?", (e["item_id"],)
                ).fetchone()["iban"]
                code = None if e["vat_code"] == "S1" else e["vat_code"]
                db.execute(
                    "INSERT OR REPLACE INTO rule VALUES (?,?,?,?)",
                    (
                        iban,
                        e["account"],
                        code,
                        f"validée le {_now()[:10]}",
                    ),
                )
    return n


def reject(db: sqlite3.Connection, entry_id: int, note: str) -> None:
    if not note.strip():
        raise BooksError(
            "un rejet se motive : la raison sert à la prochaine proposition"
        )
    with db:
        cur = db.execute(
            "UPDATE entry SET status = 'rejected', decided_at = ?, note = ? WHERE id = ? AND status = 'proposed'",
            (_now(), note.strip(), entry_id),
        )
        if not cur.rowcount:
            raise BooksError(f"écriture {entry_id} introuvable ou déjà décidée")


def evaluate(
    db: sqlite3.Connection, expected: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Compare the live classification of each item with the expected one (account, and VAT code
    when the expected answer gives one)."""
    rows = []
    for item_id, want in expected.items():
        e = db.execute(
            "SELECT * FROM entry WHERE item_id = ? AND kind IN ('invoice','bank') AND status != 'rejected'",
            (item_id,),
        ).fetchone()
        got = {"compte": e["account"], "code_tva": e["vat_code"]} if e else None
        ok = (
            bool(got)
            and got["compte"] == want["compte"]
            and want.get("code_tva") in (None, got["code_tva"])
        )
        rows.append({"piece": item_id, "attendu": want, "obtenu": got, "juste": ok})
    return {"justes": sum(r["juste"] for r in rows), "total": len(rows), "detail": rows}
