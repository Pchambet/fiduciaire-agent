"""ISO 20022 camt.053 bank statement (Swiss Payment Standards): the bank lines to reconcile.

Namespace-agnostic, so it reads the versions Swiss banks deliver (.001.04 and .001.08). A batch entry
(one booking, several transactions) is split into one line per transaction, which is how incoming
QR payments usually arrive.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


class CamtError(ValueError):
    """The statement cannot be read. The message says why, in French, for the user."""


@dataclass(frozen=True)
class BankLine:
    id: str  # bank reference of the booking, suffixed by the transaction index for batch bookings
    booking_date: date
    amount: Decimal  # always positive
    currency: str
    credit: bool  # True = money in
    reference: str  # structured creditor reference (QRR or SCOR), or ""
    counterparty: str
    counterparty_iban: str
    text: str  # unstructured remittance information and booking text


@dataclass(frozen=True)
class Statement:
    iban: str
    opening: Decimal
    closing: Decimal
    closing_date: date
    lines: tuple[BankLine, ...]

    def balance_gap(self) -> Decimal:
        """Opening + credits - debits - closing: 0 when the statement is complete."""
        moves = sum(
            (ln.amount if ln.credit else -ln.amount for ln in self.lines), Decimal(0)
        )
        return self.opening + moves - self.closing


def _text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path)
    return (found.text or "").strip() if found is not None else ""


def _balance(stmt: ET.Element, code: str) -> tuple[Decimal, date]:
    for bal in stmt.findall("{*}Bal"):
        if _text(bal, "{*}Tp/{*}CdOrPrtry/{*}Cd") == code:
            amount = Decimal(_text(bal, "{*}Amt"))
            if _text(bal, "{*}CdtDbtInd") == "DBIT":
                amount = -amount
            return amount, date.fromisoformat(_text(bal, "{*}Dt/{*}Dt")[:10])
    raise CamtError(f"solde {code} absent du relevé")


def _content_id(entry: ET.Element, seen: dict[str, int]) -> str:
    """Without a bank reference, an id from the entry's content (stable if the statement is
    reissued with other lines), numbered when identical entries repeat."""
    raw = ET.tostring(entry, encoding="unicode")
    digest = hashlib.sha1(" ".join(raw.split()).encode()).hexdigest()[:10]
    seen[digest] = seen.get(digest, 0) + 1
    return f"x{digest}" if seen[digest] == 1 else f"x{digest}-{seen[digest]}"


def _booked(entry: ET.Element) -> bool:
    """Only booked entries count: pending or informational ones are not in the balances."""
    status = _text(entry, "{*}Sts/{*}Cd") or _text(entry, "{*}Sts")
    return status in ("", "BOOK")


def _lines(entry: ET.Element, seen: dict[str, int]) -> list[BankLine]:
    credit = _text(entry, "{*}CdtDbtInd") == "CRDT"
    booked = date.fromisoformat(_text(entry, "{*}BookgDt/{*}Dt")[:10])
    base_id = _text(entry, "{*}AcctSvcrRef") or _content_id(entry, seen)
    info = _text(entry, "{*}AddtlNtryInf")
    amt = entry.find("{*}Amt")
    if amt is None:
        raise CamtError(f"écriture {base_id} sans montant")
    currency = amt.get("Ccy", "")
    transactions = entry.findall("{*}NtryDtls/{*}TxDtls") or [None]
    party = "Dbtr" if credit else "Cdtr"
    out = []
    for k, tx in enumerate(transactions):
        amount = _text(tx, "{*}Amt") or _text(tx, "{*}AmtDtls/{*}TxAmt/{*}Amt")
        if tx is None or not amount:
            if len(transactions) > 1:
                raise CamtError(
                    f"écriture groupée {base_id} sans montant par transaction"
                )
            amount = _text(entry, "{*}Amt")
        rp = tx.find("{*}RltdPties") if tx is not None else None
        name = _text(rp, f"{{*}}{party}/{{*}}Pty/{{*}}Nm") or _text(
            rp, f"{{*}}{party}/{{*}}Nm"
        )
        out.append(
            BankLine(
                id=base_id if len(transactions) == 1 else f"{base_id}/{k + 1}",
                booking_date=booked,
                amount=Decimal(amount),
                currency=currency,
                credit=credit,
                reference=_text(tx, "{*}RmtInf/{*}Strd/{*}CdtrRefInf/{*}Ref"),
                counterparty=name,
                counterparty_iban=_text(rp, f"{{*}}{party}Acct/{{*}}Id/{{*}}IBAN"),
                text=" · ".join(
                    t for t in (_text(tx, "{*}RmtInf/{*}Ustrd"), info) if t
                ),
            )
        )
    return out


def _statement(stmt: ET.Element) -> Statement:
    opening, _ = _balance(stmt, "OPBD")
    closing, closing_date = _balance(stmt, "CLBD")
    seen: dict[str, int] = {}
    lines = [
        ln for e in stmt.findall("{*}Ntry") if _booked(e) for ln in _lines(e, seen)
    ]
    return Statement(
        iban=_text(stmt, "{*}Acct/{*}Id/{*}IBAN"),
        opening=opening,
        closing=closing,
        closing_date=closing_date,
        lines=tuple(lines),
    )


def parse(xml: str | bytes) -> list[Statement]:
    """Every statement of the file (a file may carry several accounts or periods)."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise CamtError(f"XML illisible : {exc}") from exc
    stmts = root.findall("{*}BkToCstmrStmt/{*}Stmt")
    if not stmts:
        raise CamtError("ce n'est pas un relevé camt.053 (BkToCstmrStmt/Stmt absent)")
    try:
        return [_statement(s) for s in stmts]
    except (InvalidOperation, ValueError) as exc:
        if isinstance(exc, CamtError):
            raise
        raise CamtError(f"montant ou date illisible : {exc}") from exc
