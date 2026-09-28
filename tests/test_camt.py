from datetime import date
from decimal import Decimal

import pytest

from fiduciaire_agent import camt

# Written by hand, independently of the demo generator, so a bug shared by writer and reader shows.
STATEMENT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08">
 <BkToCstmrStmt><GrpHdr><MsgId>M1</MsgId></GrpHdr>
  <Stmt>
   <Acct><Id><IBAN>CH5604835012345678009</IBAN></Id></Acct>
   <Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1000.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-08-31</Dt></Dt></Bal>
   <Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="CHF">1638.00</Amt>
        <CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-09-30</Dt></Dt></Bal>
   <Ntry>
    <Amt Ccy="CHF">162.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
    <BookgDt><Dt>2026-09-10</Dt></BookgDt><AcctSvcrRef>B-100</AcctSvcrRef>
    <NtryDtls><TxDtls>
     <RltdPties><Cdtr><Pty><Nm>Papeterie Démo SA</Nm></Pty></Cdtr>
      <CdtrAcct><Id><IBAN>CH4431999123000889012</IBAN></Id></CdtrAcct></RltdPties>
     <RmtInf><Strd><CdtrRefInf><Tp><CdOrPrtry><Prtry>QRR</Prtry></CdOrPrtry></Tp>
      <Ref>210000000003139471430009017</Ref></CdtrRefInf></Strd></RmtInf>
    </TxDtls></NtryDtls>
   </Ntry>
   <Ntry>
    <Amt Ccy="CHF">800.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>
    <BookgDt><Dt>2026-09-15</Dt></BookgDt><AcctSvcrRef>B-101</AcctSvcrRef>
    <NtryDtls>
     <TxDtls><Amt Ccy="CHF">500.00</Amt><RltdPties><Dbtr><Pty><Nm>Client Un</Nm></Pty></Dbtr></RltdPties></TxDtls>
     <TxDtls><Amt Ccy="CHF">300.00</Amt><RltdPties><Dbtr><Pty><Nm>Client Deux</Nm></Pty></Dbtr></RltdPties>
      <RmtInf><Ustrd>Facture 77</Ustrd></RmtInf></TxDtls>
    </NtryDtls>
   </Ntry>
  </Stmt>
 </BkToCstmrStmt>
</Document>"""


def test_reads_debit_with_qr_reference():
    s = camt.parse(STATEMENT)[0]
    assert s.iban == "CH5604835012345678009" and s.closing_date == date(2026, 9, 30)
    line = s.lines[0]
    assert (line.id, line.credit, line.amount) == ("B-100", False, Decimal("162.00"))
    assert line.reference == "210000000003139471430009017"
    assert (line.counterparty, line.counterparty_iban) == (
        "Papeterie Démo SA",
        "CH4431999123000889012",
    )


def test_batch_booking_is_split_per_transaction():
    s = camt.parse(STATEMENT)[0]
    assert [(ln.id, ln.amount, ln.counterparty) for ln in s.lines[1:]] == [
        ("B-101/1", Decimal("500.00"), "Client Un"),
        ("B-101/2", Decimal("300.00"), "Client Deux"),
    ]
    assert s.lines[2].text == "Facture 77"


def test_balance_gap_detects_a_missing_line():
    assert camt.parse(STATEMENT)[0].balance_gap() == 0
    broken = STATEMENT.replace("1638.00", "1600.00")
    assert camt.parse(broken)[0].balance_gap() == Decimal("38.00")


def test_version_04_party_without_pty_level():
    old = STATEMENT.replace("camt.053.001.08", "camt.053.001.04").replace(
        "<Cdtr><Pty><Nm>Papeterie Démo SA</Nm></Pty></Cdtr>",
        "<Cdtr><Nm>Papeterie Démo SA</Nm></Cdtr>",
    )
    assert camt.parse(old)[0].lines[0].counterparty == "Papeterie Démo SA"


@pytest.mark.parametrize(
    "xml,reason", [("<a>", "illisible"), ("<Document/>", "camt.053")]
)
def test_unreadable_statements(xml, reason):
    with pytest.raises(camt.CamtError, match=reason):
        camt.parse(xml)
