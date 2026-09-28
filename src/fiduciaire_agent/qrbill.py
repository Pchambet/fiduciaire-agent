"""Swiss QR-bill: read and validate the payload of the QR code (SIX Implementation Guidelines 2.3).

The input is the decoded text of the QR code, not the image: decoding the image is a solved problem
(any scanner library) and is left out on purpose. What matters to a fiduciary is what comes after:
checking that the bill is well formed before anything is booked on it.

Also reads the Swico S1 "billing information" block, which carries the invoice number, date,
the supplier's VAT number and the VAT breakdown per rate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

_MOD10_TABLE = (0, 9, 4, 6, 8, 2, 7, 1, 3, 5)
_CURRENCIES = ("CHF", "EUR")
_MAX_AMOUNT = Decimal("999999999.99")


class QrBillError(ValueError):
    """The payload is not a valid Swiss QR-bill. The message says why, in French, for the user."""


@dataclass(frozen=True)
class Address:
    name: str
    street: str
    building: str
    postal_code: str
    town: str
    country: str


@dataclass(frozen=True)
class VatPart:
    rate: Decimal  # percent, e.g. 8.1
    net: (
        Decimal | None
    )  # amount the rate applies to, excluding VAT; None if the bill gives the rate only


@dataclass(frozen=True)
class BillInfo:
    invoice_number: str | None
    invoice_date: date | None
    vat_number: str | None  # CHE-123.456.789
    vat_parts: tuple[VatPart, ...]
    payment_days: int | None  # net payment term, from the /40/ conditions


@dataclass(frozen=True)
class QrBill:
    iban: str
    creditor: Address
    amount: Decimal | None
    currency: str
    debtor: Address | None
    reference_type: str  # QRR, SCOR or NON
    reference: str
    message: str
    bill_info: BillInfo | None


# --- check digits -------------------------------------------------------------------------------


def _mod97(text: str) -> int:
    digits = "".join(str(int(c, 36)) for c in text)
    return int(digits) % 97


def iban_is_valid(iban: str) -> bool:
    iban = iban.replace(" ", "").upper()
    if not re.fullmatch(r"(CH|LI)\d{2}[0-9A-Z]{17}", iban):
        return False
    return _mod97(iban[4:] + iban[:4]) == 1


def is_qr_iban(iban: str) -> bool:
    """A QR-IBAN has an institution id (positions 5 to 9) between 30000 and 31999."""
    iid = iban.replace(" ", "")[4:9]
    return iid.isdigit() and 30000 <= int(iid) <= 31999


def make_iban(iid: str, account: str, country: str = "CH") -> str:
    bban = f"{iid:0>5}{account:0>12}"
    check = 98 - _mod97(bban + country + "00")
    return f"{country}{check:02d}{bban}"


def _mod10_recursive(digits: str) -> int:
    carry = 0
    for d in digits:
        carry = _MOD10_TABLE[(carry + int(d)) % 10]
    return (10 - carry) % 10


def qrr_is_valid(reference: str) -> bool:
    return bool(re.fullmatch(r"\d{27}", reference)) and _mod10_recursive(
        reference[:26]
    ) == int(reference[26])


def make_qrr(number: str) -> str:
    body = number.zfill(26)
    return body + str(_mod10_recursive(body))


def scor_is_valid(reference: str) -> bool:
    ref = reference.replace(" ", "").upper()
    return (
        bool(re.fullmatch(r"RF\d{2}[0-9A-Z]{1,21}", ref))
        and _mod97(ref[4:] + ref[:4]) == 1
    )


# --- payload ------------------------------------------------------------------------------------


def _address(lines: list[str], start: int) -> Address | None:
    kind, *rest = lines[start : start + 7]
    if not kind:
        return None
    if kind != "S":
        raise QrBillError(
            f"type d'adresse « {kind} » refusé : seules les adresses structurées (S) sont admises"
        )
    return Address(*rest)


def _amount(text: str) -> Decimal | None:
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise QrBillError(f"montant illisible : « {text} »") from exc
    if (
        not amount.is_finite()
        or not Decimal("0.01") <= amount <= _MAX_AMOUNT
        or amount != amount.quantize(Decimal("0.01"))
    ):
        raise QrBillError(f"montant hors limites : {text}")
    return amount


def parse(payload: str) -> QrBill:
    lines = payload.replace("\r\n", "\n").rstrip("\n").split("\n")
    if lines[0] != "SPC":
        raise QrBillError("ce n'est pas une QR-facture suisse (en-tête SPC absent)")
    if len(lines) < 31 or lines[30] != "EPD":
        raise QrBillError(
            "structure incomplète : 31 lignes attendues, terminées par EPD"
        )
    if lines[1] != "0200":
        raise QrBillError(f"version {lines[1]} non prise en charge (0200 attendue)")
    if lines[2] != "1":
        raise QrBillError(f"type de codage « {lines[2]} » refusé (1 = UTF-8 attendu)")
    if any(lines[11:18]):
        raise QrBillError(
            "le bloc « créancier final » doit rester vide (réservé par SIX)"
        )

    iban = lines[3]
    if not iban_is_valid(iban):
        raise QrBillError(f"IBAN invalide : {iban}")
    currency = lines[19]
    if currency not in _CURRENCIES:
        raise QrBillError(f"devise « {currency} » refusée (CHF ou EUR)")

    ref_type, reference = lines[27], lines[28]
    if is_qr_iban(iban):
        if ref_type != "QRR":
            raise QrBillError("un QR-IBAN exige une référence QR (QRR)")
        if not qrr_is_valid(reference):
            raise QrBillError(
                f"référence QR invalide (chiffre de contrôle) : {reference}"
            )
    elif ref_type == "QRR":
        raise QrBillError("une référence QR (QRR) exige un QR-IBAN")
    elif ref_type == "SCOR" and not scor_is_valid(reference):
        raise QrBillError(f"référence créancier invalide (ISO 11649) : {reference}")
    elif ref_type == "NON" and reference:
        raise QrBillError("type de référence NON mais une référence est présente")
    elif ref_type not in ("SCOR", "NON"):
        raise QrBillError(f"type de référence inconnu : {ref_type}")

    creditor = _address(lines, 4)
    if creditor is None:
        raise QrBillError("créancier absent")
    info = lines[31] if len(lines) > 31 and lines[31] else None
    return QrBill(
        iban=iban,
        creditor=creditor,
        amount=_amount(lines[18]),
        currency=currency,
        debtor=_address(lines, 20),
        reference_type=ref_type,
        reference=reference,
        message=lines[29],
        bill_info=parse_s1(info) if info else None,
    )


def build_payload(
    *,
    iban: str,
    creditor: Address,
    amount: Decimal | None,
    currency: str,
    debtor: Address | None,
    reference_type: str,
    reference: str,
    message: str = "",
    bill_info: str = "",
) -> str:
    """The inverse of `parse`, without validation: used to write the demo data and the tests."""

    def addr(a: Address | None) -> list[str]:
        return (
            ["S", a.name, a.street, a.building, a.postal_code, a.town, a.country]
            if a
            else [""] * 7
        )

    lines = ["SPC", "0200", "1", iban, *addr(creditor), *[""] * 7]
    lines += ["" if amount is None else str(amount), currency, *addr(debtor)]
    lines += [reference_type, reference, message, "EPD"]
    if bill_info:
        lines.append(bill_info)
    return "\n".join(lines)


# --- Swico S1 -----------------------------------------------------------------------------------


def _yymmdd(text: str) -> date:
    return date(2000 + int(text[:2]), int(text[2:4]), int(text[4:6]))


def parse_s1(text: str) -> BillInfo:
    if not text.startswith("//S1/"):
        raise QrBillError("informations de facture dans un format autre que Swico S1")
    parts = [p.replace("\\/", "/") for p in re.split(r"(?<!\\)/", text[5:])]
    if len(parts) % 2:
        raise QrBillError("bloc S1 mal formé (étiquette sans valeur)")
    tags = dict(zip(parts[::2], parts[1::2], strict=True))
    try:
        vat_parts: tuple[VatPart, ...] = ()
        if "32" in tags:
            vat_parts = tuple(
                VatPart(Decimal(rate), Decimal(net))
                if sep
                else VatPart(Decimal(rate), None)
                for rate, sep, net in (p.partition(":") for p in tags["32"].split(";"))
            )
        uid = tags.get("30")
        days = None
        if "40" in tags:
            # "2:10;0:30" = 2 % discount at 10 days, net at 30 days
            days = max(int(p.partition(":")[2]) for p in tags["40"].split(";"))
        return BillInfo(
            invoice_number=tags.get("10"),
            invoice_date=_yymmdd(tags["11"]) if "11" in tags else None,
            vat_number=f"CHE-{uid[:3]}.{uid[3:6]}.{uid[6:9]}" if uid else None,
            vat_parts=vat_parts,
            payment_days=days,
        )
    except (InvalidOperation, ValueError) as exc:
        raise QrBillError(f"bloc S1 illisible : {text}") from exc
