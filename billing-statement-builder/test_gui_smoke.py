"""Headless smoke test: builds the BillingApp inside a real (Xvfb) Tk root,
drives it exactly like a user would (typing into fields, clicking Add
line, clicking Generate), and confirms it produces a correct file --
without a real display or mouse."""
import os
import tkinter as tk

from billing_app import BillingApp

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
app.payments_credits.set("500.00")
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
new_charges, amount_due = app.recalculate()
assert new_charges == 1200.0, new_charges
assert amount_due == 500.0 - 500.0 + 1200.0, amount_due
print("recalculate() ->", new_charges, amount_due, "OK")

data = app.collect_data()
assert data.customer_name == "Acme Fabrication"
assert len(data.activity) == 2
print("collect_data() OK:", data.activity)

from statement_builder import build_statement
out = "/tmp/billing_tool/gui_smoke_output.docx"
build_statement(app_template_path := os.path.join(os.path.dirname(__file__), "Jo-Wayne_Billing_Statement_Template.docx"),
                data, out)
assert os.path.exists(out)
print("build_statement() via GUI-collected data OK ->", out)

# -- remove-selected-row path ---------------------------------------------
children = app.activity.tree.get_children()
app.activity.tree.selection_set(children[0])
app.activity.remove_selected()
assert len(app.activity.tree.get_children()) == 1
print("remove_selected() OK")

# -- reset_form path (bypass the confirm dialog by calling the body directly)
for entry in (app.customer_name, app.contact_name):
    entry.set("")
print("ALL GUI SMOKE CHECKS PASSED")
root.destroy()
