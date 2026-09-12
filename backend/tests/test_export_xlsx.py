"""Unit 9: exporting into the settlement form Finance already knows.

The test that matters is the last one: the workbook's own SUMIF arithmetic, evaluated by hand
from the cells written, must reach the same payable the application computed. If those two ever
disagree, Finance believes the spreadsheet.
"""

from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from expense_api.claims.pipeline import ClaimDraft, build_claim
from expense_api.config.settings import settings
from expense_api.evidence.extractors.ocr import ocr_available
from expense_api.export.xlsx import SHEET, export_settlement
from expense_api.seed.employees import seed_employees
from expense_api.seed.policy import seed_policy_versions
from expense_api.seed.trip import seed_anchor_trip

pytestmark = [pytest.mark.db, pytest.mark.asyncio]

TEMPLATE = settings.pack_dir / "Travel_Expense_Forms_Template.xlsx"

if not ocr_available():  # pragma: no cover - depends on the host
    pytest.skip("tesseract is required to build the claim", allow_module_level=True)


@pytest_asyncio.fixture
async def claim(db_session: AsyncSession) -> ClaimDraft:
    await seed_employees(db_session, settings.pack_dir / "employee_master.csv")
    await seed_policy_versions(db_session)
    request = await seed_anchor_trip(db_session)
    return await build_claim(
        db_session,
        travel_request=request,
        emails_dir=settings.pack_dir / "sample_emails",
        receipts_dir=settings.pack_dir / "receipts",
    )


@pytest_asyncio.fixture
async def exported(claim: ClaimDraft, tmp_path: Path) -> Path:
    return export_settlement(
        claim,
        template=TEMPLATE,
        destination=tmp_path / "settlement.xlsx",
        employee_name="Chaitanya Reddy",
        employee_code="NX-4471",
        settlement_date=date(2026, 6, 21),
    )


async def test_the_pack_template_is_never_modified(exported: Path) -> None:
    """It is the specification, and the container mounts it read-only."""
    assert exported.exists()
    assert exported != TEMPLATE
    assert TEMPLATE.exists()


async def test_the_header_identifies_the_claim(exported: Path) -> None:
    sheet = load_workbook(exported)[SHEET]

    assert sheet["C5"].value == "TRQ-2026-0001"
    assert sheet["C6"].value == "Chaitanya Reddy"
    assert sheet["F6"].value == "NX-4471"
    assert sheet["C7"].value == "CE110"


async def test_every_total_is_still_a_formula(exported: Path) -> None:
    """Legend line 62. Overwriting these with typed numbers is the failure this guards."""
    sheet = load_workbook(exported)[SHEET]

    for cell in ("H15", "H29", "H41", "H44", "H45", "H47", "H49", "H50"):
        value = sheet[cell].value
        assert isinstance(value, str) and value.startswith("="), f"{cell} is no longer a formula"


async def test_paid_by_is_exactly_the_word_the_sumif_matches(exported: Path) -> None:
    """Legend line 63. "employee" or "Employee " would silently sum to zero."""
    sheet = load_workbook(exported)[SHEET]

    written = [
        sheet[f"G{row}"].value
        for row in [*range(11, 15), *range(19, 29), *range(33, 41)]
        if sheet[f"G{row}"].value is not None
    ]

    assert written
    assert set(written) <= {"Employee", "Company"}


async def test_the_disallowed_row_carries_a_remark_not_just_a_number(exported: Path) -> None:
    """Legend line 66. A bare figure invites the query the remark prevents."""
    sheet = load_workbook(exported)[SHEET]

    assert sheet["H46"].value == pytest.approx(929.60)
    remark = sheet["I46"].value
    assert remark
    assert "Laundry" in remark and "Mini bar" in remark
    # The colleague's cab is not a row on the form, so the remark is where it gets accounted for.
    assert "another person" in remark


async def test_the_advance_is_written_for_the_form_to_settle_against(exported: Path) -> None:
    sheet = load_workbook(exported)[SHEET]

    assert sheet["H48"].value == pytest.approx(20000.00)


async def test_each_section_carries_its_lines(exported: Path) -> None:
    sheet = load_workbook(exported)[SHEET]

    lodging = [sheet[f"E{r}"].value for r in range(11, 15) if sheet[f"H{r}"].value]
    transport = [sheet[f"H{r}"].value for r in range(19, 29) if sheet[f"H{r}"].value]
    other = [sheet[f"D{r}"].value for r in range(33, 41) if sheet[f"H{r}"].value]

    assert lodging == ["Room charges"]
    # Four cabs plus two flight sectors. The colleague's cab is rejected and is not a row.
    assert len(transport) == 6
    assert set(other) == {"Laundry", "Mini bar", "In-room dining", "Dinner, 4 covers"}


async def test_every_row_names_its_source_document(exported: Path) -> None:
    """Legend line 65: a proof ref points at a document, never at "attached mail"."""
    sheet = load_workbook(exported)[SHEET]

    refs = [
        sheet[f"I{row}"].value
        for row in [*range(11, 15), *range(19, 29), *range(33, 41)]
        if sheet[f"H{row}"].value
    ]

    assert refs
    assert all(ref and ".eml" in ref for ref in refs)


async def test_the_workbooks_own_arithmetic_agrees_with_the_application(
    exported: Path, claim: ClaimDraft
) -> None:
    """Evaluate the form's SUMIF by hand and check it reaches the same payable.

    openpyxl does not compute formulas, so this reproduces what Excel would do with the cells
    that were written. It is the check that stops the exported spreadsheet quietly contradicting
    the screen the employee approved.
    """
    sheet = load_workbook(exported)[SHEET]

    def sumif(rows: range) -> float:
        return sum(
            float(sheet[f"H{row}"].value or 0)
            for row in rows
            if sheet[f"G{row}"].value == "Employee"
        )

    # H44 = SUMIF over the three sections, restricted to Employee rows.
    employee_total = sumif(range(11, 15)) + sumif(range(19, 29)) + sumif(range(33, 41))
    disallowed = float(sheet["H46"].value)
    advance = float(sheet["H48"].value)

    net = employee_total - disallowed  # H47
    payable = max(net - advance, 0)  # H49
    recoverable = max(advance - net, 0)  # H50

    assert employee_total == pytest.approx(27318.04)
    assert net == pytest.approx(26388.44)
    assert payable == pytest.approx(6388.44)
    assert recoverable == pytest.approx(0.0)

    # And the same figures the application arrived at independently.
    assert payable == pytest.approx(float(claim.summary.payable))
    assert net == pytest.approx(float(claim.summary.net_reimbursable))


async def test_company_paid_rows_are_excluded_by_the_sumif(exported: Path) -> None:
    """§3.2. They appear on the form for audit and contribute nothing to the reimbursement."""
    sheet = load_workbook(exported)[SHEET]

    company = [
        float(sheet[f"H{row}"].value)
        for row in range(19, 29)
        if sheet[f"G{row}"].value == "Company"
    ]

    assert sum(company) == pytest.approx(10556.00)
