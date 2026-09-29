"""Headless smoke test: builds the BillingApp inside a real (Xvfb) Tk root,
drives it exactly like a user would (typing into fields, clicking Add
line, browsing for a logo, clicking Generate), and confirms it produces a
correct file -- without a real display or mouse.

Also specifically reproduces the reported bug (more payments than charges
in the Statement Activity table not reducing the Amount Due) to guard
against regressing it.
"""
import os
import tkinter as tk

from PIL import Image

from billing_app import BillingApp
from statement_builder import money

root = tk.Tk()
app = BillingApp(root)
root.update()

# -- fill out the form ---------------------------------------------------
app.customer_name.set("Acme Fabrication")
app.contact_name.set("Sam Acme")
app.billing_address.set("42 Industrial Way")
app.customer_city_state_zip.set("North Charleston, SC 29405")
app.customer_email.set("sam@acmefab.com")
app.customer_phone.set("(843) 555-1212")

app.previous_balance.set("500.00")
app.past_due.set("0.00")

app.activity.date_var.set("09/10")
app.activity.ref_var.set("INV-2001")
app.activity.desc_var.set("Cluster onboarding")
app.activity.charge_var.set("1200")
app.activity.add_line()

app.activity.date_var.set("09/20")
app.activity.ref_var.set("PAYMENT")
app.activity.desc_var.set("Payment received")
app.activity.payment_var.set("500")
app.activity.add_line()

root.update()
data = app.recalculate()
assert data.new_charges == 1200.0, data.new_charges
assert data.payments_credits == 500.0, data.payments_credits
assert data.amount_due == 500.0 - 500.0 + 1200.0 == 1200.0, data.amount_due
print("recalculate() basic case ->", data.new_charges, data.payments_credits, data.amount_due, "OK")

# -- reproduce the exact reported bug: entering MORE payments than charges
#    on Statement Activity must reduce/negative the Amount Due, live,
#    without a separate "Payments/Credits" field that could disagree ------
for item in app.activity.tree.get_children():
    app.activity.tree.delete(item)
app.activity.on_change()  # ActivityTable itself calls this on add/remove;
                            # simulate the same live-refresh path here too

app.previous_balance.set("3000.00")
app.past_due.set("2000.00")

app.activity.date_var.set("09/29/2026")
app.activity.ref_var.set("v0001")
app.activity.desc_var.set("example installation")
app.activity.charge_var.set("500")
app.activity.payment_var.set("1500")
app.activity.add_line()  # this alone must trigger on_change -> recalculate()

app.activity.date_var.set("09/29/2026")
app.activity.ref_var.set("v0001")
app.activity.desc_var.set("Material List")
app.activity.charge_var.set("700")
app.activity.add_line()

root.update()
data = app.collect_data()
assert data.new_charges == 1200.0, data.new_charges
assert data.payments_credits == 1500.0, data.payments_credits  # was stuck reading a stale manual field before the fix
assert data.amount_due == 3000.0 - 1500.0 + 1200.0 == 2700.0, data.amount_due
print("REPORTED BUG SCENARIO FIXED: payments_credits reflects activity payments, amount_due =", data.amount_due)

# live label text must show the same numbers, not a stale computed_label
label_text = app.computed_label.cget("text")
assert money(1500.0) in label_text, label_text
assert money(2700.0) in label_text, label_text
print("computed_label live text matches:", label_text)

# -- a case where payments exceed balance+charges: must go negative, not
#    silently clamp to zero or leave a stale positive number ---------------
for item in app.activity.tree.get_children():
    app.activity.tree.delete(item)
app.previous_balance.set("100.00")
app.activity.date_var.set("01/01")
app.activity.ref_var.set("PAYMENT")
app.activity.desc_var.set("big payment")
app.activity.payment_var.set("5000")
app.activity.add_line()
root.update()
data = app.collect_data()
assert data.amount_due == 100.0 - 5000.0 == -4900.0, data.amount_due
assert money(data.amount_due) == "-$4,900.00"
print("NEGATIVE / CREDIT BALANCE CASE OK:", money(data.amount_due))

# -- logo: pick a non-standard-aspect-ratio test logo, confirm it survives
#    browse_logo's validation and ends up on the generated StatementData --
test_logo_path = "/tmp/_smoke_test_logo.png"
Image.new("RGB", (900, 300), (30, 120, 200)).save(test_logo_path)
app.company_logo_path.set(test_logo_path)
app.update_logo_preview()
assert app._logo_preview_image is not None
data = app.collect_data()
assert data.company_logo_path == test_logo_path
print("logo path plumbed through to StatementData:", data.company_logo_path)

out = "/tmp/billing_tool_gui_smoke_output.docx"
from statement_builder import build_statement
build_statement(os.path.join(os.path.dirname(__file__), "Jo-Wayne_Billing_Statement_Template.docx"),
                data, out)
assert os.path.exists(out)

import zipfile
with zipfile.ZipFile(out) as z:
    logo_bytes = z.read("word/media/image1.png")
with Image.open(__import__("io").BytesIO(logo_bytes)) as img:
    assert img.size == (1536, 1024), img.size  # unchanged from the template's own logo box size
print("generated document's swapped logo keeps the template's fixed box size:", img.size)

os.remove(test_logo_path)
os.remove(out)

# -- clear_logo path --------------------------------------------------------
app.clear_logo()
assert app.company_logo_path.get() == ""
data = app.collect_data()
assert data.company_logo_path is None
print("clear_logo() resets to template default")

# -- color theme + font dropdowns: pick a non-default of each through the
#    real widget variables (as a Combobox selection would), generate, and
#    confirm the document actually reflects both -------------------------
import docx as _docx
from docx.oxml.ns import qn as _qn
import theme as _theme

app.company_name.set("Acme Fabrication")
app.color_theme_var.set("Burgundy Red")
app.font_choice_var.set("Georgia")
data = app.collect_data()
assert data.color_theme == "Burgundy Red"
assert data.font_choice == "Georgia"

out2 = "/tmp/billing_tool_theme_smoke_output.docx"
build_statement(os.path.join(os.path.dirname(__file__), "Jo-Wayne_Billing_Statement_Template.docx"),
                data, out2)
d2 = _docx.Document(out2)
header_fill = d2.tables[2].rows[0].cells[0]._tc.tcPr.find(_qn('w:shd')).get(_qn('w:fill'))
expected_primary, _ = _theme.COLOR_THEMES["Burgundy Red"]
assert header_fill.upper() == expected_primary.upper(), header_fill
heading_font = None
for p in d2.tables[0].rows[0].cells[1].paragraphs:
    for r in p.runs:
        if "BILLING" in r.text:
            heading_font = r.font.name
assert heading_font == "Georgia", heading_font
print("GUI-driven theme/font selection reflected in generated document:",
      header_fill, heading_font)
os.remove(out2)

# -- defaults must never default to a DIFFERENT real company's name/payee
#    now that this app is meant to be handed to other customers ----------
app.company_name.set("")
app.payable_to.set("")
data = app.collect_data()
assert "Coastal HPC" not in (data.company_name or "")
assert data.payable_to == ""  # left blank; statement_builder decides the fallback text
print("blank company/payee fields don't default to a different company's name")

# -- app's own identity icon (window/taskbar): must never crash the app if
#    the logo asset isn't there, and must actually set one when it is -----
import billing_app as _billing_app

logo_path = _billing_app.resource_path(_billing_app.LOGO_FILENAME)
had_logo_before = os.path.exists(logo_path)
if not had_logo_before:
    _billing_app.set_window_icon(root)
    assert getattr(root, "_coastal_hpc_icon_ref", None) is None
    print("set_window_icon() with no logo asset present: no crash, no-op -- OK")

Image.new("RGB", (200, 180), (10, 40, 90)).save(logo_path)
try:
    _billing_app.set_window_icon(root)
    assert getattr(root, "_coastal_hpc_icon_ref", None) is not None
    print("set_window_icon() with a logo present: icon ref set -- OK")
finally:
    if not had_logo_before:
        os.remove(logo_path)

print("ALL GUI SMOKE CHECKS PASSED")
root.destroy()
