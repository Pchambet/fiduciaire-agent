from datetime import date
from decimal import Decimal as D

import pytest

from fiduciaire_agent import ledger
from fiduciaire_agent.ledger import EntryError, Line, VatShare

DAY = date(2026, 9, 15)


def lines(entry):
    return [(ln.account, ln.debit, ln.credit) for ln in entry.lines]


def test_split_with_net_amounts_from_s1():
    shares = ledger.split_vat(D("370.10"), [(D("8.1"), D(200)), (D("2.6"), D(150))])
    assert shares == [
        VatShare(D("8.1"), D(200), D("16.20")),
        VatShare(D("2.6"), D(150), D("3.90")),
    ]


def test_split_extracts_vat_from_gross():
    assert ledger.split_vat(D("1081.00"), [(D("8.1"), None)]) == [
        VatShare(D("8.1"), D("1000.00"), D("81.00"))
    ]


def test_rounding_residue_goes_to_largest_share():
    shares = ledger.split_vat(D("370.12"), [(D("8.1"), D(200)), (D("2.6"), D(150))])
    assert shares[0].net == D("200.02") and sum(s.net + s.vat for s in shares) == D(
        "370.12"
    )


def test_inconsistent_vat_is_refused():
    with pytest.raises(EntryError, match="TVA incohérente"):
        ledger.split_vat(D("1100.00"), [(D("8.1"), D(1000))])


def test_invoice_entry_uses_1171_for_operating_expenses():
    shares = ledger.split_vat(D("1081.00"), [(D("8.1"), D(1000))])
    e = ledger.expense(DAY, "Papeterie", D("1081.00"), "6500", shares, ledger.PAYABLES)
    assert lines(e) == [
        ("6500", D(1000), 0),
        ("1171", D("81.00"), 0),
        ("2000", 0, D("1081.00")),
    ]


def test_material_goes_to_1170():
    shares = ledger.split_vat(D("108.10"), [(D("8.1"), None)])
    e = ledger.expense(DAY, "Matériel", D("108.10"), "4000", shares, ledger.PAYABLES)
    assert e.lines[1].account == "1170"


def test_exempt_expense_has_no_vat_line():
    e = ledger.expense(
        DAY,
        "Loyer",
        D(2500),
        "6000",
        ledger.split_vat(D(2500), [(D(0), None)]),
        ledger.BANK,
    )
    assert lines(e) == [("6000", D(2500), 0), ("1020", 0, D(2500))]


def test_income_with_vat_due_and_receivable_settlement():
    e = ledger.income(
        DAY,
        "Vente",
        D("108.10"),
        "3400",
        ledger.split_vat(D("108.10"), [(D("8.1"), None)]),
    )
    assert lines(e) == [
        ("1020", D("108.10"), 0),
        ("3400", 0, D("100.00")),
        ("2200", 0, D("8.10")),
    ]
    with pytest.raises(EntryError, match="débiteur"):
        ledger.income(
            DAY,
            "Client",
            D("108.10"),
            "1100",
            ledger.split_vat(D("108.10"), [(D("8.1"), None)]),
        )


@pytest.mark.parametrize("account", ["1020", "3400", "9999"])
def test_expense_refuses_non_expense_accounts(account):
    with pytest.raises(EntryError, match="charges"):
        ledger.expense(
            DAY, "x", D(10), account, [VatShare(D(0), D(10), D(0))], ledger.BANK
        )


@pytest.mark.parametrize(
    "bad,reason",
    [
        ((Line("6500", D(10), D(0)), Line("1020", D(0), D(9))), "déséquilibrée"),
        ((Line("6500", D(10), D(0)), Line("9999", D(0), D(10))), "inconnu"),
        ((Line("6500", D(10), D(10)),), "invalide"),
        ((Line("6500", D("10.001"), D(0)), Line("1020", D(0), D("10.001"))), "centime"),
    ],
)
def test_invariants(bad, reason):
    with pytest.raises(EntryError, match=reason):
        ledger.check(ledger.Entry(DAY, "x", bad))
