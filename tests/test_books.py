import json
from decimal import Decimal

import pytest

from fiduciaire_agent import books, demo
from fiduciaire_agent.books import BooksError


def test_every_planted_anomaly_is_found_and_nothing_else(db):
    found = {(a["regle"], a["piece"]) for a in books.anomalies(db)}
    assert found == demo.EXPECTED_ANOMALIES


def test_overview_of_the_demo_month(db):
    o = books.overview(db)
    assert o["documents"] == {
        "factures": 12,
        "lignes_bancaires": 15,
        "paiements_rapproches": 8,
        "anomalies": 7,
    }
    assert o["date_du_releve"] == "2026-09-30"
    # 5 invoices booked by supplier rules + 8 matched payments, all waiting for a person
    assert o["ecritures"] == {"proposees": 13, "validees": 0, "rejetees": 0}


def test_every_document_of_the_month_takes_exactly_one_path(db):
    # The triage the README shows: 28 documents, each booked by code, sent to the agent,
    # or held for a person (the overdue invoice is flagged but still booked).
    docs = {
        r[0]
        for r in db.execute("SELECT id FROM invoice UNION SELECT id FROM bank_line")
    }
    docs |= {a["piece"] for a in books.anomalies(db, "qr_invalid")}
    booked = {e["piece"] for e in books.entries(db, "proposed")}
    to_classify = {i.id for i in books.items_to_classify(db)}
    held = {
        a["piece"] for a in books.anomalies(db) if a["regle"] not in books.NON_BLOCKING
    }
    assert (len(docs), len(booked), len(to_classify), len(held)) == (28, 13, 9, 6)
    assert booked | to_classify | held == docs
    assert len(booked) + len(to_classify) + len(held) == len(docs)


def test_what_is_left_to_classify_is_exactly_what_no_rule_covers(db):
    assert {i.id for i in books.items_to_classify(db)} == set(
        demo.EXPECTED_CLASSIFICATION
    )


def test_payment_without_reference_is_matched_on_account_and_amount(db):
    assert books.explain(db, "B-BK-0912-01")["facture_rapprochee"] == "F-librairie-551"
    m = db.execute("SELECT method FROM match WHERE bank_id = 'B-BK-0912-01'").fetchone()
    assert m["method"] == "iban_montant"


def test_an_overdue_invoice_is_still_booked(db):
    e = books.explain(db, "F-informatique-4388")
    assert [a["regle"] for a in e["anomalies"]] == ["unpaid_overdue"]
    assert (
        e["ecritures"][0]["origine"] == "règle"
        and e["ecritures"][0]["compte"] == "6570"
    )


def test_rule_entry_splits_vat_from_the_bill(db):
    e = books.explain(db, "F-papeterie-2026-0917")["ecritures"][0]
    assert e["code_tva"] == "S1"
    assert e["lignes"] == [
        {"compte": "6500", "debit": "1000.00", "credit": "0.00"},
        {"compte": "1171", "debit": "81.00", "credit": "0.00"},
        {"compte": "2000", "debit": "0.00", "credit": "1081.00"},
    ]


def test_every_stored_entry_balances(db):
    for e in books.entries(db):
        lines = e["lignes"]
        assert sum(Decimal(ln["debit"]) for ln in lines) == sum(
            Decimal(ln["credit"]) for ln in lines
        )


def test_agent_proposal_on_a_mixed_rate_bill(db):
    e = books.propose(
        db,
        "F-traiteur-126",
        "6640",
        None,
        "Apéritif offert à des clients : représentation",
    )
    assert (
        e["statut"] == "proposée" and e["origine"] == "agent" and e["code_tva"] == "S1"
    )
    assert [(ln["compte"], ln["debit"]) for ln in e["lignes"][:4]] == [
        ("6640", "200.00"),
        ("1171", "16.20"),
        ("6640", "150.00"),
        ("1171", "3.90"),
    ]


def test_agent_proposal_on_a_bill_without_vat_information(db):
    with pytest.raises(BooksError, match="code_tva obligatoire"):
        books.propose(
            db, "F-garage-3190", "6200", None, "Entretien du véhicule utilitaire"
        )
    e = books.propose(
        db, "F-garage-3190", "6200", "TVA81", "Entretien du véhicule utilitaire"
    )
    assert e["lignes"][0] == {"compte": "6200", "debit": "800.00", "credit": "0.00"}
    assert (
        e["date"] == "2026-09-20"
    )  # an undated bill takes the date it was paid (found by the agent's first run)


def test_bank_lines_book_against_the_bank(db):
    rent = books.propose(
        db, "B-BK-0903-01", "6000", "EXO", "Ordre permanent de loyer, loyer exonéré"
    )
    assert rent["lignes"] == [
        {"compte": "6000", "debit": "2400.00", "credit": "0.00"},
        {"compte": "1020", "debit": "0.00", "credit": "2400.00"},
    ]
    cash_in = books.propose(
        db, "B-BK-0925-01", "1100", "EXO", "Encaissement de la facture A-2026-031"
    )
    assert cash_in["lignes"][0] == {
        "compte": "1020",
        "debit": "3243.00",
        "credit": "0.00",
    }


@pytest.mark.parametrize(
    "item,account,code,reason",
    [
        ("F-hotel-7730", "6640", "TVA81", "indique elle-même sa TVA"),
        ("F-hotel-7730", "2000", None, "compte de charges"),
        ("B-BK-0925-01", "6000", "EXO", "produits ou de débiteurs"),
        ("B-BK-0903-01", "6000", "TVA99", "code_tva inconnu"),
        ("B-BK-0922-01", "6510", "TVA81", "bloquée par une anomalie"),
        ("F-papeterie-2026-0917", "6500", None, "déjà une écriture"),
        ("F-inconnue", "6500", None, "pièce inconnue"),
    ],
)
def test_proposals_the_books_refuse(db, item, account, code, reason):
    with pytest.raises(BooksError, match=reason):
        books.propose(db, item, account, code, "une justification assez longue")


def test_a_proposal_needs_a_reason(db):
    with pytest.raises(BooksError, match="justification"):
        books.propose(db, "F-hotel-7730", "6640", None, "  ")


def test_one_live_entry_per_document(db):
    books.propose(
        db, "F-hotel-7730", "6640", None, "Nuitées d'un déplacement professionnel"
    )
    with pytest.raises(BooksError, match="déjà une écriture"):
        books.propose(
            db, "F-hotel-7730", "6640", None, "Nuitées d'un déplacement professionnel"
        )


def test_reject_sends_the_document_back_to_classification(db):
    e = books.propose(
        db, "F-hotel-7730", "6500", None, "Classement volontairement faux"
    )
    with pytest.raises(BooksError, match="motive"):
        books.reject(db, e["ecriture"], "")
    books.reject(db, e["ecriture"], "C'est un déplacement : 6640")
    assert "F-hotel-7730" in {i.id for i in books.items_to_classify(db)}


@pytest.mark.parametrize("origin", ["agent", "human"])
def test_approve_and_remember_turns_a_classification_into_a_rule(
    world, tmp_path, origin
):
    folder, db = world
    e = books.propose(
        db,
        "F-hotel-7730",
        "6640",
        None,
        "Nuitées d'un déplacement professionnel",
        origin,
    )
    assert books.approve(db, [e["ecriture"]], remember=True) == 1
    with pytest.raises(BooksError, match="déjà décidée"):
        books.approve(db, [e["ecriture"]])
    # next month, the same hotel is booked by the rule, without the agent
    db2 = books.connect(tmp_path / "mois-suivant.db")
    rule = db.execute("SELECT * FROM rule WHERE account = '6640'").fetchone()
    db2.execute("INSERT INTO rule VALUES (?,?,?,?)", tuple(rule))
    books.ingest(db2, folder)
    assert books.explain(db2, "F-hotel-7730")["ecritures"][0]["origine"] == "règle"


def test_ingest_is_idempotent_and_keeps_decisions(world):
    folder, db = world
    e = books.propose(
        db, "F-hotel-7730", "6640", None, "Nuitées d'un déplacement professionnel"
    )
    books.approve(db, [e["ecriture"]])
    before = (books.anomalies(db), books.entries(db))
    books.ingest(db, folder)
    assert (books.anomalies(db), books.entries(db)) == before


def test_statement_that_does_not_balance(world):
    folder, db = world
    xml = folder / "banque" / "releve-2026-09.xml"
    xml.write_text(
        xml.read_text(encoding="utf-8").replace(
            '<Amt Ccy="CHF">15.00</Amt>', '<Amt Ccy="CHF">1.00</Amt>'
        )
    )
    books.ingest(db, folder)
    assert ("statement_balance", "R-releve-2026-09") in {
        (a["regle"], a["piece"]) for a in books.anomalies(db)
    }


def test_bill_with_blank_amount(world):
    folder, db = world
    f = folder / "factures" / "hotel-7730.txt"
    f.write_text(
        f.read_text(encoding="utf-8").replace("\n311.40\n", "\n\n"), encoding="utf-8"
    )
    books.ingest(db, folder)
    assert ("amount_missing", "F-hotel-7730") in {
        (a["regle"], a["piece"]) for a in books.anomalies(db)
    }


def test_evaluation_scores_account_and_vat_code(db):
    books.propose(
        db, "F-garage-3190", "6200", "TVA81", "Entretien du véhicule utilitaire"
    )
    books.propose(
        db,
        "B-BK-0930-01",
        "6500",
        "EXO",
        "Frais de compte classés à tort en administration",
    )
    score = books.evaluate(db, demo.EXPECTED_CLASSIFICATION)
    assert (score["justes"], score["total"]) == (1, 9)
    assert json.dumps(
        score, ensure_ascii=False
    )  # serializable, for the CLI and the MCP server


def test_remember_does_not_turn_a_bank_line_into_a_supplier_rule(db):
    e = books.propose(db, "B-BK-0930-01", "6900", "EXO", "Frais de tenue de compte")
    books.approve(db, [e["ecriture"]], remember=True)
    assert db.execute("SELECT COUNT(*) FROM rule").fetchone()[0] == len(demo.RULES)
