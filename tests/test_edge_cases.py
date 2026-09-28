"""Edge cases found by an independent review of the code, one test each."""

from dataclasses import replace
from datetime import date

import pytest

from fiduciaire_agent import books, camt, demo, qrbill
from fiduciaire_agent.books import BooksError
from fiduciaire_agent.demo import BILLS, SUPPLIERS, Move

DAY = date(2026, 9, 20)


def bill(name, **over):
    return replace(next(b for b in BILLS if b.file == name), **over)


def pay(b, ref, amount=None, **over):
    s = SUPPLIERS[b.supplier]
    move = Move(
        ref, DAY, amount or b.amount, False, s.address.name, s.iban, b.reference
    )
    return replace(move, **over)


def month(tmp_path, bills, moves, rules=()):
    folder = tmp_path / "mois"
    (folder / "factures").mkdir(parents=True)
    (folder / "banque").mkdir()
    for b in bills:
        (folder / "factures" / f"{b.file}.txt").write_text(demo.payload(b), "utf-8")
    (folder / "banque" / "releve.xml").write_text(demo.statement_xml(moves), "utf-8")
    db = books.connect(tmp_path / "livres.db")
    if rules:
        db.executemany("INSERT INTO rule VALUES (?,?,?,'test')", rules)
        db.commit()
    books.ingest(db, folder)
    return folder, db


def found(db):
    return {(a["regle"], a["piece"]) for a in books.anomalies(db)}


def test_same_qr_reference_at_two_suppliers_is_not_a_double_payment(tmp_path):
    a = bill("papeterie-2026-0917", ref_number="1")
    b = bill("hotel-7730", ref_number="1")
    _, db = month(tmp_path, [a, b], [pay(b, "P1"), pay(a, "P2")])
    assert found(db) == set()
    matched = dict(db.execute("SELECT bank_id, invoice_id FROM match").fetchall())
    assert matched == {"B-P1": "F-hotel-7730", "B-P2": "F-papeterie-2026-0917"}


def test_second_identical_payment_without_reference_is_flagged(tmp_path):
    b = bill("librairie-551")
    moves = [pay(b, "P1"), pay(b, "P2")]
    _, db = month(tmp_path, [b], moves)
    assert found(db) == {("duplicate_payment", "B-P2")}
    assert "B-P2" not in {i.id for i in books.items_to_classify(db)}


def test_two_open_bills_fitting_one_payment_is_flagged_not_guessed(tmp_path):
    b1 = bill("librairie-551")
    b2 = bill("librairie-551", file="librairie-552", number="552")
    _, db = month(tmp_path, [b1, b2], [pay(b1, "P1")])
    assert ("ambiguous_payment", "B-P1") in found(db)
    assert db.execute("SELECT COUNT(*) FROM match").fetchone()[0] == 0


def test_payment_in_another_currency_is_not_matched(tmp_path):
    b = bill("hotel-7730")
    folder, db = month(tmp_path, [b], [])
    xml = demo.statement_xml([pay(b, "P1")]).replace(
        'Ccy="CHF">311.40', 'Ccy="EUR">311.40'
    )
    (folder / "banque" / "releve.xml").write_text(xml, "utf-8")
    books.ingest(db, folder)
    assert found(db) == {("amount_mismatch", "B-P1")}


def test_payment_of_a_bill_on_hold_is_not_an_unknown_reference(tmp_path):
    b = bill("nettoyage-0925")
    _, db = month(tmp_path, [b], [pay(b, "P1")])
    assert found(db) == {
        ("vat_inconsistent", "F-nettoyage-0925"),
        ("invoice_on_hold", "B-P1"),
    }


def test_a_rejection_survives_the_next_ingest(tmp_path):
    b = bill("papeterie-2026-0917")
    rule = (SUPPLIERS["papeterie"].iban, "6500", None)
    folder, db = month(tmp_path, [b], [pay(b, "P1")], [rule])
    for e in books.entries(db, "proposed"):
        books.reject(db, e["ecriture"], "à revoir")
    books.ingest(db, folder)
    assert books.entries(db, "proposed") == []
    # both documents come back to classification instead
    assert {i.id for i in books.items_to_classify(db)} == {
        "F-papeterie-2026-0917",
        "B-P1",
    }


def test_missing_net_amount_in_a_mixed_rate_bill_is_an_anomaly(tmp_path):
    b = bill("traiteur-126", vat="8.1:200;2.6")
    rule = (SUPPLIERS["traiteur"].iban, "6640", None)
    _, db = month(tmp_path, [b], [], [rule])  # must not crash with a supplier rule
    assert ("vat_inconsistent", "F-traiteur-126") in found(db)


def test_ledger_errors_reach_the_caller_as_books_errors(db):
    db.execute(
        'UPDATE invoice SET vat = \'[["8.1", "1"], ["2.6", null]]\' WHERE id = \'F-hotel-7730\''
    )
    with pytest.raises(BooksError, match="plusieurs taux"):
        books.propose(db, "F-hotel-7730", "6640", None, "Nuitées d'un séminaire client")


def test_statement_loaded_twice_is_a_clear_error(world):
    folder, db = world
    src = folder / "banque" / "releve-2026-09.xml"
    (folder / "banque" / "copie.xml").write_bytes(src.read_bytes())
    with pytest.raises(BooksError, match="chargé deux fois"):
        books.ingest(db, folder)


STMT = """<Stmt><Acct><Id><IBAN>{iban}</IBAN></Id></Acct>
<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-08-31</Dt></Dt></Bal>
<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">{closing}</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-09-30</Dt></Dt></Bal>
{entries}</Stmt>"""
FEE = """<Ntry><Amt Ccy="CHF">15.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>{sts}</Cd></Sts>
<BookgDt><Dt>2026-09-30</Dt></BookgDt><AddtlNtryInf>Frais</AddtlNtryInf></Ntry>"""


def doc(*stmts):
    body = "".join(stmts)
    return f'<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>{body}</BkToCstmrStmt></Document>'


def test_every_statement_of_a_file_is_read():
    s = camt.parse(doc(STMT.format(iban="CH1", closing="85.00", entries=FEE.format(sts="BOOK")),
                       STMT.format(iban="CH2", closing="100.00", entries="")))  # fmt: skip
    assert [(x.iban, len(x.lines)) for x in s] == [("CH1", 1), ("CH2", 0)]


def test_lines_without_bank_reference_get_content_ids_that_survive_an_insertion():
    one = camt.parse(
        doc(STMT.format(iban="CH1", closing="85.00", entries=FEE.format(sts="BOOK")))
    )
    rent = FEE.format(sts="BOOK").replace("15.00", "2400.00").replace("Frais", "Loyer")
    two = camt.parse(
        doc(
            STMT.format(
                iban="CH1", closing="-2315.00", entries=rent + FEE.format(sts="BOOK")
            )
        )
    )
    assert one[0].lines[0].id == two[0].lines[1].id
    twice = camt.parse(
        doc(
            STMT.format(iban="CH1", closing="70.00", entries=FEE.format(sts="BOOK") * 2)
        )
    )
    assert len({ln.id for ln in twice[0].lines}) == 2


def test_pending_entries_are_left_out():
    s = camt.parse(
        doc(STMT.format(iban="CH1", closing="100.00", entries=FEE.format(sts="PDNG")))
    )
    assert s[0].lines == () and s[0].balance_gap() == 0


def test_unreadable_amount_is_a_camt_error():
    with pytest.raises(camt.CamtError, match="illisible"):
        camt.parse(doc(STMT.format(iban="CH1", closing="abc", entries="")))


@pytest.mark.parametrize(
    "line,value,reason",
    [(2, "2", "codage"), (11, "S", "créancier final")],
)
def test_qr_header_and_reserved_block(line, value, reason):
    lines = demo.payload(bill("hotel-7730")).split("\n")
    lines[line] = value
    with pytest.raises(qrbill.QrBillError, match=reason):
        qrbill.parse("\n".join(lines))


def test_cli_accepts_an_id_also_picked_by_origin(world, capsys):
    from fiduciaire_agent.cli import main

    _, db = world
    base = db.execute("PRAGMA database_list").fetchone()["file"]
    first = books.entries(db, "proposed")[0]["ecriture"]
    assert main(["--base", base, "valider", str(first), "--origine", "regle"]) == 0
    assert "5 écriture(s) validée(s)" in capsys.readouterr().out
