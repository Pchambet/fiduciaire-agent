"""A demo month for a fictitious client, with known answers.

Thirteen supplier QR-bills and one camt.053 statement for September 2026. Every name is invented and
carries « Démo ». Seven anomalies are planted on purpose; `EXPECTED_ANOMALIES` lists them and a test
requires the controls to find all of them and nothing else. `EXPECTED_CLASSIFICATION` is the answer
key for the nine documents no rule covers, used to score the agent (`fidu evaluer`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from xml.sax.saxutils import escape

from .qrbill import Address, build_payload, make_iban, make_qrr

CLIENT = Address("Atelier Démo Sàrl", "Chemin de la Démo", "3", "1227", "Carouge", "CH")
CLIENT_IBAN = make_iban("00700", "000012345678")


def _addr(name: str, town: str, pc: str) -> Address:
    return Address(name, "Rue de la Démo", "1", pc, town, "CH")


@dataclass(frozen=True)
class Supplier:
    key: str
    address: Address
    iban: str


SUPPLIERS = {
    s.key: s
    for s in [
        Supplier(
            "papeterie",
            _addr("Papeterie Démo SA", "Genève", "1204"),
            make_iban("30808", "000000000101"),
        ),
        Supplier(
            "informatique",
            _addr("Informatique Démo SA", "Lancy", "1212"),
            make_iban("30808", "000000000102"),
        ),
        Supplier(
            "energie",
            _addr("Énergie Démo SA", "Genève", "1211"),
            make_iban("00700", "000000000103"),
        ),
        Supplier(
            "telecom",
            _addr("Télécom Démo SA", "Lausanne", "1003"),
            make_iban("30808", "000000000104"),
        ),
        Supplier(
            "librairie",
            _addr("Librairie Démo", "Genève", "1205"),
            make_iban("00700", "000000000105"),
        ),
        Supplier(
            "hotel",
            _addr("Hôtel Démo", "Zurich", "8001"),
            make_iban("30808", "000000000106"),
        ),
        Supplier(
            "traiteur",
            _addr("Traiteur Démo Sàrl", "Carouge", "1227"),
            make_iban("30808", "000000000107"),
        ),
        Supplier(
            "assurance",
            _addr("Assurances Démo SA", "Nyon", "1260"),
            make_iban("30808", "000000000108"),
        ),
        Supplier(
            "garage",
            _addr("Garage Démo SA", "Plan-les-Ouates", "1228"),
            make_iban("30808", "000000000109"),
        ),
        Supplier(
            "imprimerie",
            _addr("Imprimerie Démo Sàrl", "Genève", "1207"),
            make_iban("30808", "000000000110"),
        ),
        Supplier(
            "nettoyage",
            _addr("Nettoyage Démo Sàrl", "Vernier", "1214"),
            make_iban("30808", "000000000111"),
        ),
    ]
}


@dataclass(frozen=True)
class Bill:
    file: str
    supplier: str
    amount: D
    number: str
    day: date
    message: str
    vat: (
        str  # the /32/ tag of Swico S1, "" when the bill carries no billing information
    )
    ref_type: str = "QRR"
    ref_number: str = ""

    @property
    def reference(self) -> str:
        if self.ref_type == "QRR":
            return make_qrr(self.ref_number)
        return {"SCOR": "RF18539007547034", "NON": ""}[self.ref_type]


BILLS = [
    Bill("papeterie-2026-0917", "papeterie", D("1081.00"), "2026-0917", date(2026, 9, 1),
         "Fournitures de bureau septembre", "8.1:1000", ref_number="1010917"),
    Bill("informatique-4471", "informatique", D("1621.50"), "4471", date(2026, 9, 2),
         "Licences logicielles, renouvellement annuel", "8.1:1500", ref_number="1024471"),
    Bill("informatique-4388", "informatique", D("540.50"), "4388", date(2026, 8, 10),
         "Remplacement d'un écran", "8.1:500", ref_number="1024388"),
    Bill("energie-2026-09", "energie", D("432.40"), "E-2026-09", date(2026, 9, 3),
         "Électricité de l'atelier, août", "8.1", ref_type="SCOR"),
    Bill("telecom-889201", "telecom", D("162.15"), "889201", date(2026, 9, 10),
         "Abonnement internet et téléphonie, septembre", "8.1:150", ref_number="104889201"),
    Bill("librairie-551", "librairie", D("102.60"), "551", date(2026, 9, 4),
         "Ouvrages de référence : TVA, droit des sociétés", "2.6:100", ref_type="NON"),
    Bill("hotel-7730", "hotel", D("311.40"), "7730", date(2026, 9, 9),
         "Deux nuitées, séminaire client à Zurich", "3.8:300", ref_number="1067730"),
    Bill("traiteur-126", "traiteur", D("370.10"), "126", date(2026, 9, 11),
         "Apéritif clients du 18.09 : boissons et mets livrés", "8.1:200;2.6:150", ref_number="107126"),
    Bill("assurance-rc-2027", "assurance", D("1250.00"), "RC-2027-331", date(2026, 9, 1),
         "Prime responsabilité civile entreprise 2026-2027", "0", ref_number="108331"),
    Bill("garage-3190", "garage", D("864.80"), "", date(2026, 9, 12),
         "Service et pneus de la camionnette", "", ref_number="1093190"),
    # --- planted anomalies ---
    Bill("imprimerie-6612", "imprimerie", D("486.45"), "6612", date(2026, 9, 14),
         "Cartes de visite et flyers", "8.1:450", ref_number="1106612"),  # check digit broken below
    Bill("nettoyage-0925", "nettoyage", D("1100.00"), "0925", date(2026, 9, 25),
         "Nettoyage des locaux, septembre", "8.1:1000", ref_number="1110925"),  # 1000 + 8.1 % is 1081
    Bill("papeterie-2026-0917-copie", "papeterie", D("1081.00"), "2026-0917", date(2026, 9, 1),
         "Fournitures de bureau septembre", "8.1:1000", ref_number="1010917"),  # received twice
]  # fmt: skip


@dataclass(frozen=True)
class Move:
    ref: str
    day: date
    amount: D
    credit: bool
    counterparty: str = ""
    iban: str = ""
    reference: str = ""
    text: str = ""


def _paid(bill_file: str, ref: str, day: date, amount: D | None = None) -> Move:
    b = next(b for b in BILLS if b.file == bill_file)
    s = SUPPLIERS[b.supplier]
    return Move(
        ref, day, amount or b.amount, False, s.address.name, s.iban, b.reference
    )


MOVES = [
    Move("BK-0903-01", date(2026, 9, 3), D("2400.00"), False, "Régie Démo SA", make_iban("00700", "000000000201"),
         text="Ordre permanent : loyer de l'atelier, septembre"),
    _paid("papeterie-2026-0917", "BK-0905-01", date(2026, 9, 5)),
    _paid("informatique-4471", "BK-0908-01", date(2026, 9, 8)),
    _paid("informatique-4471", "BK-0909-01", date(2026, 9, 9)),  # planted: paid twice
    _paid("energie-2026-09", "BK-0910-01", date(2026, 9, 10)),
    Move("BK-0912-01", date(2026, 9, 12), D("102.60"), False, "Librairie Démo", SUPPLIERS["librairie"].iban,
         text="Facture 551"),  # no structured reference: matched on account and amount
    _paid("hotel-7730", "BK-0915-01", date(2026, 9, 15)),
    _paid("traiteur-126", "BK-0916-01", date(2026, 9, 16)),
    _paid("assurance-rc-2027", "BK-0918-01", date(2026, 9, 18)),
    _paid("garage-3190", "BK-0920-01", date(2026, 9, 20)),
    _paid("telecom-889201", "BK-0922-01", date(2026, 9, 22), D("150.00")),  # planted: 150 paid on 162.15
    Move("BK-0924-01", date(2026, 9, 24), D("540.00"), False, "Fournisseur Démo Inconnu",
         make_iban("30808", "000000000299"), make_qrr("1999999")),  # planted: no bill carries this reference
    Move("BK-0925-01", date(2026, 9, 25), D("3243.00"), True, "Client Démo SA", text="Facture A-2026-031"),
    Move("BK-0925-02", date(2026, 9, 25), D("1081.00"), True, "Client Démo Deux Sàrl", text="Facture A-2026-034"),
    Move("BK-0930-01", date(2026, 9, 30), D("15.00"), False, text="Frais de tenue de compte, septembre"),
]  # fmt: skip

OPENING = D("25000.00")

EXPECTED_ANOMALIES = {
    ("qr_invalid", "F-imprimerie-6612"),
    ("vat_inconsistent", "F-nettoyage-0925"),
    ("duplicate_invoice", "F-papeterie-2026-0917-copie"),
    ("duplicate_payment", "B-BK-0909-01"),
    ("amount_mismatch", "B-BK-0922-01"),
    ("unknown_reference", "B-BK-0924-01"),
    ("unpaid_overdue", "F-informatique-4388"),
}

EXPECTED_CLASSIFICATION = {
    "F-librairie-551": {"compte": "6500"},
    "F-hotel-7730": {"compte": "6640"},
    "F-traiteur-126": {"compte": "6640"},
    "F-assurance-rc-2027": {"compte": "6300"},
    "F-garage-3190": {"compte": "6200", "code_tva": "TVA81"},
    "B-BK-0903-01": {"compte": "6000", "code_tva": "EXO"},
    "B-BK-0925-01": {"compte": "1100", "code_tva": "EXO"},
    "B-BK-0925-02": {"compte": "1100", "code_tva": "EXO"},
    "B-BK-0930-01": {"compte": "6900", "code_tva": "EXO"},
}

RULES = [
    {"iban": SUPPLIERS["papeterie"].iban, "compte": "6500"},
    {"iban": SUPPLIERS["informatique"].iban, "compte": "6570"},
    {"iban": SUPPLIERS["energie"].iban, "compte": "6400"},
    {"iban": SUPPLIERS["telecom"].iban, "compte": "6510"},
]


def payload(b: Bill) -> str:
    s = SUPPLIERS[b.supplier]
    tags = []
    if b.number:
        tags.append(f"/10/{b.number}")
    if b.vat:
        tags += [f"/11/{b.day:%y%m%d}", f"/32/{b.vat}", "/40/0:30"]
    text = build_payload(
        iban=s.iban,
        creditor=s.address,
        amount=b.amount,
        currency="CHF",
        debtor=CLIENT,
        reference_type=b.ref_type,
        reference=b.reference,
        message=b.message,
        bill_info="//S1" + "".join(tags) if tags else "",
    )
    if b.file == "imprimerie-6612":  # a mistyped last digit of the QR reference
        ref = b.reference
        text = text.replace(ref, ref[:-1] + str((int(ref[-1]) + 1) % 10))
    return text


def statement_xml(moves: list[Move], opening: D = OPENING) -> str:
    closing = opening + sum((m.amount if m.credit else -m.amount for m in moves), D(0))

    def bal(code: str, amount: D, day: str) -> str:
        return (
            f'<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">{amount}</Amt>'
            f"<CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>{day}</Dt></Dt></Bal>"
        )

    def entry(m: Move) -> str:
        party = "Dbtr" if m.credit else "Cdtr"
        related = (
            f"<{party}><Pty><Nm>{escape(m.counterparty)}</Nm></Pty></{party}>"
            if m.counterparty
            else ""
        )
        if m.iban:
            related += f"<{party}Acct><Id><IBAN>{m.iban}</IBAN></Id></{party}Acct>"
        rmt = ""
        if m.reference:
            rmt += f"<Strd><CdtrRefInf><Ref>{m.reference}</Ref></CdtrRefInf></Strd>"
        if m.text:
            rmt += f"<Ustrd>{escape(m.text)}</Ustrd>"
        return (
            f'<Ntry><Amt Ccy="CHF">{m.amount}</Amt><CdtDbtInd>{"CRDT" if m.credit else "DBIT"}</CdtDbtInd>'
            f"<Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>{m.day}</Dt></BookgDt><AcctSvcrRef>{m.ref}</AcctSvcrRef>"
            f"<NtryDtls><TxDtls><RltdPties>{related}</RltdPties>"
            f"{f'<RmtInf>{rmt}</RmtInf>' if rmt else ''}</TxDtls></NtryDtls></Ntry>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
        "<GrpHdr><MsgId>DEMO-2026-09</MsgId><CreDtTm>2026-09-30T23:00:00</CreDtTm></GrpHdr>"
        f"<Stmt><Id>DEMO-2026-09</Id><Acct><Id><IBAN>{CLIENT_IBAN}</IBAN></Id></Acct>"
        + bal("OPBD", opening, "2026-08-31")
        + bal("CLBD", closing, "2026-09-30")
        + "".join(entry(m) for m in moves)
        + "</Stmt></BkToCstmrStmt></Document>\n"
    )


def write(folder: Path) -> Path:
    """Write the demo month into `folder` (factures/, banque/, regles.json). The answer key stays in
    this module: nothing the agent can reach should contain it."""
    (folder / "factures").mkdir(parents=True, exist_ok=True)
    (folder / "banque").mkdir(parents=True, exist_ok=True)
    for b in BILLS:
        (folder / "factures" / f"{b.file}.txt").write_text(payload(b), encoding="utf-8")
    (folder / "banque" / "releve-2026-09.xml").write_text(
        statement_xml(MOVES), encoding="utf-8"
    )
    (folder / "regles.json").write_text(
        json.dumps(RULES, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return folder
