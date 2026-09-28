"""Chart of accounts, Swiss VAT and the construction of journal entries.

Entries are only ever built here, from an amount and a classification (account + VAT). Nobody,
human or agent, types the lines of an entry: an entry built by these functions balances and its
VAT is computed from the rate, so an unbalanced or miscalculated entry cannot exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ROUNDING_TOLERANCE = Decimal("0.05")

# A subset inspired by the Swiss SME chart of accounts (plan comptable PME). A real mandate uses the
# client's own chart: this dict is the only place to change.
ACCOUNTS: dict[str, str] = {
    "1020": "Banque, compte courant",
    "1100": "Créances résultant de ventes (débiteurs)",
    "1170": "Impôt préalable TVA s/matériel, marchandises, prestations",
    "1171": "Impôt préalable TVA s/investissements et autres charges d'exploitation",
    "2000": "Dettes résultant d'achats et de prestations (créanciers)",
    "2200": "TVA due",
    "3200": "Ventes de marchandises",
    "3400": "Ventes de prestations",
    "4000": "Charges de matériel",
    "4400": "Prestations de tiers",
    "6000": "Charges de locaux (loyer)",
    "6100": "Entretien, réparations",
    "6200": "Charges de véhicules",
    "6300": "Assurances-choses, droits, taxes",
    "6400": "Charges d'énergie",
    "6500": "Charges d'administration (fournitures, documentation)",
    "6510": "Téléphone, internet",
    "6570": "Informatique (logiciels, matériel, licences)",
    "6600": "Publicité",
    "6640": "Frais de voyage et de représentation",
    "6900": "Charges financières (frais bancaires, intérêts)",
}
BANK, RECEIVABLES, PAYABLES, VAT_DUE = "1020", "1100", "2000", "2200"
EXPENSE_ACCOUNTS = frozenset(a for a in ACCOUNTS if a[0] in "46")
INCOME_ACCOUNTS = frozenset(a for a in ACCOUNTS if a[0] == "3") | {RECEIVABLES}

# Swiss VAT rates since 1 January 2024.
VAT_CODES: dict[str, Decimal] = {
    "TVA81": Decimal("8.1"),  # taux normal
    "TVA26": Decimal("2.6"),  # taux réduit : denrées alimentaires, livres, médicaments
    "TVA38": Decimal("3.8"),  # taux spécial : hébergement
    "EXO": Decimal(
        0
    ),  # exclu ou exonéré : loyer, assurances, frais bancaires, encaissement débiteur
}


class EntryError(ValueError):
    """The requested entry is impossible. The message says why, in French, for the user."""


@dataclass(frozen=True)
class Line:
    account: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class Entry:
    date: date
    label: str
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class VatShare:
    rate: Decimal
    net: Decimal
    vat: Decimal


def _round(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def input_vat_account(expense_account: str) -> str:
    """Material and services (class 4) go to 1170, other operating expenses to 1171."""
    return "1170" if expense_account.startswith("4") else "1171"


def split_vat(
    gross: Decimal, parts: list[tuple[Decimal, Decimal | None]]
) -> list[VatShare]:
    """Split a gross amount by VAT rate.

    `parts` is a list of (rate, net amount or None). With net amounts (Swico S1 gives them), each
    share's VAT is computed and the total must match `gross` within five centimes; the rounding
    residue goes to the largest share so the shares add up to `gross` exactly. With a single rate
    and no net amount, VAT is extracted from the gross.
    """
    if not parts:
        raise EntryError("aucun taux de TVA")
    if len(parts) == 1 and parts[0][1] is None:
        rate = parts[0][0]
        net = _round(gross * 100 / (100 + rate))
        return [VatShare(rate, net, gross - net)]
    shares = []
    for rate, net in parts:
        if net is None:
            raise EntryError("plusieurs taux de TVA sans montant par taux")
        shares.append(VatShare(rate, net, _round(net * rate / 100)))
    residue = gross - sum(s.net + s.vat for s in shares)
    if abs(residue) > ROUNDING_TOLERANCE:
        detail = " + ".join(f"{s.net} à {s.rate} %" for s in shares)
        raise EntryError(
            f"TVA incohérente : {detail} donne {gross - residue}, la facture dit {gross}"
        )
    i = max(range(len(shares)), key=lambda k: shares[k].net)
    shares[i] = VatShare(shares[i].rate, shares[i].net + residue, shares[i].vat)
    return shares


def expense(
    on: date,
    label: str,
    gross: Decimal,
    account: str,
    shares: list[VatShare],
    against: str,
) -> Entry:
    """Expense with recoverable input VAT, against the payables (invoice) or the bank (direct debit)."""
    if account not in EXPENSE_ACCOUNTS:
        raise EntryError(f"le compte {account} n'est pas un compte de charges")
    lines = []
    for s in shares:
        lines.append(Line(account, s.net, Decimal(0)))
        if s.vat:
            lines.append(Line(input_vat_account(account), s.vat, Decimal(0)))
    lines.append(Line(against, Decimal(0), gross))
    return check(Entry(on, label, tuple(lines)))


def income(
    on: date, label: str, gross: Decimal, account: str, shares: list[VatShare]
) -> Entry:
    """Money in: revenue with VAT due, or the settlement of a receivable."""
    if account not in INCOME_ACCOUNTS:
        raise EntryError(
            f"le compte {account} n'est pas un compte de produits ou de débiteurs"
        )
    if account == RECEIVABLES and any(s.vat for s in shares):
        raise EntryError(
            "l'encaissement d'un débiteur ne porte pas de TVA : elle a été comptée à la facturation"
        )
    lines = [Line(BANK, gross, Decimal(0))]
    for s in shares:
        lines.append(Line(account, Decimal(0), s.net))
        if s.vat:
            lines.append(Line(VAT_DUE, Decimal(0), s.vat))
    return check(Entry(on, label, tuple(lines)))


def payment(on: date, label: str, amount: Decimal) -> Entry:
    return check(
        Entry(
            on,
            label,
            (Line(PAYABLES, amount, Decimal(0)), Line(BANK, Decimal(0), amount)),
        )
    )


def check(entry: Entry) -> Entry:
    """Invariants every entry must satisfy before it is stored. Raises EntryError otherwise."""
    for ln in entry.lines:
        if ln.account not in ACCOUNTS:
            raise EntryError(f"compte inconnu : {ln.account}")
        if (
            (ln.debit < 0 or ln.credit < 0)
            or (ln.debit and ln.credit)
            or not (ln.debit or ln.credit)
        ):
            raise EntryError(
                f"ligne invalide sur {ln.account} : un montant positif au débit ou au crédit"
            )
        if _round(ln.debit) != ln.debit or _round(ln.credit) != ln.credit:
            raise EntryError(f"ligne sur {ln.account} au-delà du centime")
    debit = sum((ln.debit for ln in entry.lines), Decimal(0))
    credit = sum((ln.credit for ln in entry.lines), Decimal(0))
    if debit != credit:
        raise EntryError(f"écriture déséquilibrée : débit {debit}, crédit {credit}")
    return entry
