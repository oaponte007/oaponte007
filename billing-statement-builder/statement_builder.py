"""Fills the Coastal HPC billing statement template with real data.

Kept separate from the GUI (billing_app.py) so the document-generation
logic can be tested/used on its own -- the GUI just collects a dict and
calls build_statement().

The template's placeholder cells hold either:
  (a) a single self-contained value (e.g. a table cell that is just
      "$0.00" or "[MM/DD]") -- replaced wholesale via set_cell_text(), or
  (b) a mix of literal label text and a bracketed placeholder sharing one
      run (e.g. "Statement #: [000001]") -- replaced via a targeted
      substring swap on just the run(s) containing that bracket text, so
      the surrounding label/formatting is untouched.
Word stores a Shift+Enter line break as <w:br/> inside a run; python-docx's
Run.text getter/setter round-trip that as a literal "\\n", which is why
plain string replace on run.text is safe here without special-casing line
breaks.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

import docx


@dataclass
class ActivityLine:
    date: str = ""
    reference: str = ""          # invoice # / "PAYMENT" / etc.
    description: str = ""
    charge: Optional[float] = None
    payment: Optional[float] = None


@dataclass
class StatementData:
    # statement header
    statement_number: str = ""
    statement_date: str = ""

    # your company (Coastal HPC)
    company_name: str = "COASTAL HPC"
    company_address: str = ""
    company_phone: str = ""
    company_email: str = ""
    company_website: str = ""

    # bill to
    customer_name: str = ""
    contact_name: str = ""
    billing_address: str = ""
    customer_city_state_zip: str = ""
    customer_email: str = ""
    customer_phone: str = ""

    # account summary (previous_balance/payments_credits/past_due entered;
    # new_charges/amount_due are normally computed by the GUI before this
    # is called, but can be overridden)
    previous_balance: float = 0.0
    payments_credits: float = 0.0
    new_charges: float = 0.0
    past_due: float = 0.0
    amount_due: float = 0.0

    activity: List[ActivityLine] = field(default_factory=list)

    payment_methods: str = "ACH / Check / Card / Online"
    payable_to: str = "Coastal HPC"
    payment_instructions: str = ""
    payment_due_date: str = ""

    notes_terms: str = ""


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def compute_totals(data: StatementData) -> None:
    """Fills new_charges/amount_due from the activity lines + entered
    previous balance/payments/credits. Called by the GUI's "Recalculate"
    action and again just before writing, so it's always internally
    consistent even if the user edited fields out of order."""
    data.new_charges = sum(a.charge or 0.0 for a in data.activity)
    data.amount_due = data.previous_balance - data.payments_credits + data.new_charges


# ---------------------------------------------------------------------------
# low-level docx helpers
# ---------------------------------------------------------------------------

def set_paragraph_text(paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for r in paragraph.runs[1:]:
            r.text = ""
    else:
        paragraph.add_run(text)


def set_cell_text(cell, text: str) -> None:
    paragraphs = cell.paragraphs
    set_paragraph_text(paragraphs[0], text)
    for extra_p in paragraphs[1:]:
        for r in extra_p.runs:
            r.text = ""


def replace_in_cell(cell, replacements: dict) -> None:
    """Substring-replaces each old->new pair in every run of every
    paragraph in `cell`, leaving runs that don't contain a match (and thus
    their formatting/line breaks) completely untouched."""
    for p in cell.paragraphs:
        for r in p.runs:
            text = r.text
            changed = False
            for old, new in replacements.items():
                if old in text:
                    text = text.replace(old, new)
                    changed = True
            if changed:
                r.text = text


def replace_in_paragraph(paragraph, replacements: dict) -> None:
    for r in paragraph.runs:
        text = r.text
        changed = False
        for old, new in replacements.items():
            if old in text:
                text = text.replace(old, new)
                changed = True
        if changed:
            r.text = text


def clone_row_before(table, template_row_index: int, before_row_index: int):
    src_tr = table.rows[template_row_index]._tr
    new_tr = deepcopy(src_tr)
    table.rows[before_row_index]._tr.addprevious(new_tr)


def remove_row(table, row_index: int) -> None:
    tr = table.rows[row_index]._tr
    tr.getparent().remove(tr)


# ---------------------------------------------------------------------------
# the actual fill
# ---------------------------------------------------------------------------

def build_statement(template_path: str, data: StatementData, output_path: str) -> None:
    compute_totals(data)
    doc = docx.Document(template_path)
    tables = doc.tables

    # --- table 0: statement number / date -----------------------------
    header_cell = tables[0].rows[0].cells[1]
    replace_in_cell(header_cell, {
        "[000001]": data.statement_number or "000001",
        "[MM/DD/YYYY]": data.statement_date or "",
    })

    # --- table 1: your company (left) / bill to (right) ---------------
    company_cell = tables[1].rows[0].cells[0]
    set_paragraph_text(company_cell.paragraphs[0], data.company_name or "COASTAL HPC")
    phone_email = "  |  ".join(v for v in (data.company_phone, data.company_email) if v)
    replace_in_cell(company_cell, {
        "[City, State ZIP]": data.company_address or "",
        "[Phone]  |  [Email]": phone_email,
        "[Website]": data.company_website or "",
    })

    customer_cell = tables[1].rows[0].cells[1]
    email_phone = " / ".join(v for v in (data.customer_email, data.customer_phone) if v)
    replace_in_cell(customer_cell, {
        "[Customer / Company Name]": data.customer_name or "",
        "[Contact Name]": data.contact_name or "",
        "[Billing Address]": data.billing_address or "",
        "[City, State ZIP]": data.customer_city_state_zip or "",
        "[Email / Phone]": email_phone,
    })

    # --- table 2: account summary --------------------------------------
    summary_row = tables[2].rows[1]
    for cell, value in zip(
        summary_row.cells,
        (data.previous_balance, data.payments_credits, data.new_charges,
         data.past_due, data.amount_due),
    ):
        set_cell_text(cell, money(value))

    # --- table 3: statement activity -----------------------------------
    activity_table = tables[3]
    total_row_index = len(activity_table.rows) - 1
    body_row_count = total_row_index - 1  # rows between header (0) and total row
    n_items = len(data.activity)

    if n_items > body_row_count:
        for _ in range(n_items - body_row_count):
            clone_row_before(activity_table, 1, total_row_index)
            total_row_index += 1
    elif n_items < body_row_count:
        for _ in range(body_row_count - n_items):
            remove_row(activity_table, total_row_index - 1)
            total_row_index -= 1

    for i, item in enumerate(data.activity):
        row = activity_table.rows[1 + i]
        set_cell_text(row.cells[0], item.date)
        set_cell_text(row.cells[1], item.reference)
        set_cell_text(row.cells[2], item.description)
        set_cell_text(row.cells[3], money(item.charge) if item.charge is not None else "")
        set_cell_text(row.cells[4], money(item.payment) if item.payment is not None else "")

    total_row = activity_table.rows[total_row_index]
    total_charges = sum(a.charge or 0.0 for a in data.activity)
    total_payments = sum(a.payment or 0.0 for a in data.activity)
    set_cell_text(total_row.cells[3], money(total_charges))
    set_cell_text(total_row.cells[4], money(total_payments))

    # --- table 4: payment information ----------------------------------
    payment_info_cell = tables[4].rows[0].cells[0]
    replace_in_cell(payment_info_cell, {
        "[ACH / Check / Card / Online]": data.payment_methods or "",
        "Coastal HPC": data.payable_to or "Coastal HPC",
        "[Insert payment instructions]": data.payment_instructions or "",
    })

    payment_due_cell = tables[4].rows[0].cells[1]
    replace_in_cell(payment_due_cell, {
        "[11/08/1977]": data.payment_due_date or "",
    })
    for p in payment_due_cell.paragraphs:
        for r in p.runs:
            if "$0.00" in r.text:
                r.text = r.text.replace("$0.00", money(data.amount_due))

    # --- notes / terms (a plain paragraph, not a table cell) -----------
    placeholder = ("[Add payment terms, late-fee policy, project notes, "
                    "purchase order references, or a thank-you message here.]")
    for p in doc.paragraphs:
        if placeholder in p.text:
            set_paragraph_text(p, data.notes_terms or "")
            break

    doc.save(output_path)
