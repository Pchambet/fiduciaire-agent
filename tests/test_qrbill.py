from datetime import date
from decimal import Decimal

import pytest

from fiduciaire_agent import qrbill
from fiduciaire_agent.qrbill import Address, QrBillError

CREDITOR = Address(
    "Papeterie Démo SA", "Rue de l'Exemple", "12", "1204", "Genève", "CH"
)
DEBTOR = Address("Atelier Démo Sàrl", "Chemin du Test", "3", "1227", "Carouge", "CH")
QR_IBAN = qrbill.make_iban("30808", "000000001234")
IBAN = qrbill.make_iban("00700", "000000005678")


def payload(**over):
    fields = {
        "iban": QR_IBAN,
        "creditor": CREDITOR,
        "amount": Decimal("1081.00"),
        "currency": "CHF",
        "debtor": DEBTOR,
        "reference_type": "QRR",
        "reference": qrbill.make_qrr("2026090001"),
        "message": "Facture 2026-0917",
        "bill_info": "//S1/10/2026-0917/11/260915/30/106017086/32/8.1:1000/40/0:30",
    }
    fields.update(over)
    return qrbill.build_payload(**fields)


def test_iban_checksum():
    assert qrbill.iban_is_valid("CH4431999123000889012")  # SIX example QR-IBAN
    assert not qrbill.iban_is_valid("CH4431999123000889013")
    assert qrbill.iban_is_valid(QR_IBAN) and qrbill.is_qr_iban(QR_IBAN)
    assert qrbill.iban_is_valid(IBAN) and not qrbill.is_qr_iban(IBAN)


def test_qrr_mod10_recursive():
    # Reference from the SIX implementation guidelines example
    assert qrbill.qrr_is_valid("210000000003139471430009017")
    assert not qrbill.qrr_is_valid("210000000003139471430009018")
    assert qrbill.qrr_is_valid(qrbill.make_qrr("123"))
    assert len(qrbill.make_qrr("123")) == 27


def test_scor_iso11649():
    assert qrbill.scor_is_valid("RF18539007547034")
    assert not qrbill.scor_is_valid("RF19539007547034")


def test_parse_full_bill():
    bill = qrbill.parse(payload())
    assert bill.iban == QR_IBAN and bill.creditor == CREDITOR and bill.debtor == DEBTOR
    assert bill.amount == Decimal("1081.00") and bill.currency == "CHF"
    assert bill.reference_type == "QRR" and qrbill.qrr_is_valid(bill.reference)
    info = bill.bill_info
    assert info.invoice_number == "2026-0917"
    assert info.invoice_date == date(2026, 9, 15)
    assert info.vat_number == "CHE-106.017.086"
    assert info.vat_parts == (qrbill.VatPart(Decimal("8.1"), Decimal(1000)),)
    assert info.payment_days == 30


def test_parse_accepts_crlf_and_trailing_newline():
    assert qrbill.parse(payload().replace("\n", "\r\n") + "\r\n").amount == Decimal(
        "1081.00"
    )


def test_s1_multiple_rates_and_escaped_slash():
    info = qrbill.parse_s1(r"//S1/10/A\/12/32/8.1:200;2.6:150")
    assert info.invoice_number == "A/12"
    assert info.vat_parts == (
        qrbill.VatPart(Decimal("8.1"), Decimal(200)),
        qrbill.VatPart(Decimal("2.6"), Decimal(150)),
    )


def test_s1_single_rate_without_net_amount():
    assert qrbill.parse_s1("//S1/32/8.1").vat_parts == (
        qrbill.VatPart(Decimal("8.1"), None),
    )


def test_amount_may_be_left_blank_by_creditor():
    assert qrbill.parse(payload(amount=None)).amount is None


@pytest.mark.parametrize(
    "over,reason",
    [
        ({"reference": "210000000003139471430009018"}, "chiffre de contrôle"),
        ({"iban": IBAN}, "QR-IBAN"),
        ({"reference_type": "SCOR", "reference": "RF18539007547034"}, "QR-IBAN"),
        ({"currency": "USD"}, "devise"),
        ({"amount": Decimal(0)}, "montant"),
        ({"amount": Decimal("10.005")}, "montant"),
    ],
)
def test_invalid_bills_are_rejected_with_a_reason(over, reason):
    with pytest.raises(QrBillError, match=reason):
        qrbill.parse(payload(**over))


def test_normal_iban_with_scor_and_non():
    assert qrbill.parse(
        payload(iban=IBAN, reference_type="SCOR", reference="RF18539007547034")
    ).reference
    assert (
        qrbill.parse(payload(iban=IBAN, reference_type="NON", reference="")).reference
        == ""
    )


def test_not_a_qr_bill():
    with pytest.raises(QrBillError, match="SPC"):
        qrbill.parse("BCD\n002\n1\nSCT")
