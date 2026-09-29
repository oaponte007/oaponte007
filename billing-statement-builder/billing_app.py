"""Coastal HPC Billing Statement Builder -- a small desktop form that asks
for everything the billing-statement template needs and generates a filled
.docx for the customer.

Run directly with Python (Tkinter ships with the standard python.org
Windows installer, so `python billing_app.py` already works as a normal
Windows program with no extra install beyond `pip install python-docx`),
or package it into a standalone .exe with PyInstaller -- see
build_windows_exe.bat / README.md.
"""

from __future__ import annotations

import json
import os
import sys
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import theme
from statement_builder import ActivityLine, StatementData, build_statement, compute_totals, money

APP_NAME = "Coastal HPC Billing Statement Builder"
TEMPLATE_FILENAME = "Jo-Wayne_Billing_Statement_Template.docx"


def resource_path(relative: str) -> str:
    """Resolves a bundled file's path whether running as a plain script or
    as a PyInstaller --onefile exe (which unpacks data files to a temp
    dir named in sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def settings_path() -> str:
    """Where the remembered "your company" fields live between runs.
    %APPDATA% on Windows; falls back to the home directory elsewhere."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "CoastalHPC")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "billing_builder_settings.json")


def load_settings() -> dict:
    try:
        with open(settings_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict) -> None:
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # not saving a "remember this" convenience is never fatal


def parse_money(text: str, field_label: str) -> float:
    text = (text or "").strip().replace("$", "").replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"'{field_label}' needs to be a number (you entered: {text!r})")


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable frame -- Tkinter has no built-in one, this
    is the standard canvas+scrollbar pattern."""

    def __init__(self, parent):
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas)

        self.body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)


class LabeledEntry(ttk.Frame):
    def __init__(self, parent, label, default="", width=40):
        super().__init__(parent)
        ttk.Label(self, text=label, width=22, anchor="w").pack(side="left")
        self.var = tk.StringVar(value=default)
        ttk.Entry(self, textvariable=self.var, width=width).pack(side="left", fill="x", expand=True)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)


class LabeledText(ttk.Frame):
    def __init__(self, parent, label, height=3, default=""):
        super().__init__(parent)
        ttk.Label(self, text=label, anchor="w").pack(anchor="w")
        self.text = tk.Text(self, height=height, width=60, wrap="word")
        self.text.pack(fill="x", expand=True)
        if default:
            self.text.insert("1.0", default)

    def get(self) -> str:
        return self.text.get("1.0", "end").rstrip("\n")

    def set(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)


class ActivityTable(ttk.Frame):
    """The Statement Activity line-item editor: a Treeview list plus
    entry fields + Add/Remove buttons underneath it."""

    COLUMNS = ("date", "reference", "description", "charge", "payment")
    HEADINGS = ("Date", "Invoice #", "Description", "Charges", "Payments")

    def __init__(self, parent, on_change=None):
        super().__init__(parent)
        self.on_change = on_change or (lambda: None)

        self.tree = ttk.Treeview(self, columns=self.COLUMNS, show="headings", height=6)
        for col, heading, width in zip(self.COLUMNS, self.HEADINGS, (70, 80, 260, 80, 80)):
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, anchor="w")
        self.tree.pack(fill="x", expand=True)

        entry_row = ttk.Frame(self)
        entry_row.pack(fill="x", pady=(4, 0))

        self.date_var = tk.StringVar()
        self.ref_var = tk.StringVar()
        self.desc_var = tk.StringVar()
        self.charge_var = tk.StringVar()
        self.payment_var = tk.StringVar()

        ttk.Entry(entry_row, textvariable=self.date_var, width=9).pack(side="left", padx=2)
        ttk.Entry(entry_row, textvariable=self.ref_var, width=10).pack(side="left", padx=2)
        ttk.Entry(entry_row, textvariable=self.desc_var, width=32).pack(side="left", padx=2)
        ttk.Entry(entry_row, textvariable=self.charge_var, width=10).pack(side="left", padx=2)
        ttk.Entry(entry_row, textvariable=self.payment_var, width=10).pack(side="left", padx=2)

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", pady=(4, 0))
        ttk.Label(entry_row, text="  (date, invoice#/PAYMENT, description, charge $, payment $)",
                  foreground="#666").pack(side="left")
        ttk.Button(button_row, text="Add line", command=self.add_line).pack(side="left")
        ttk.Button(button_row, text="Remove selected", command=self.remove_selected).pack(side="left", padx=(6, 0))

    def add_line(self):
        date_ = self.date_var.get().strip()
        desc = self.desc_var.get().strip()
        if not date_ and not desc:
            return  # nothing typed, nothing to add
        try:
            charge = parse_money(self.charge_var.get(), "Charge") if self.charge_var.get().strip() else None
            payment = parse_money(self.payment_var.get(), "Payment") if self.payment_var.get().strip() else None
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        self.tree.insert("", "end", values=(
            date_, self.ref_var.get().strip(), desc,
            f"{charge:.2f}" if charge is not None else "",
            f"{payment:.2f}" if payment is not None else "",
        ))
        for v in (self.date_var, self.ref_var, self.desc_var, self.charge_var, self.payment_var):
            v.set("")
        self.on_change()

    def remove_selected(self):
        for item in self.tree.selection():
            self.tree.delete(item)
        self.on_change()

    def get_lines(self) -> list[ActivityLine]:
        lines = []
        for item in self.tree.get_children():
            d, ref, desc, charge, payment = self.tree.item(item, "values")
            lines.append(ActivityLine(
                date=d, reference=ref, description=desc,
                charge=float(charge) if charge else None,
                payment=float(payment) if payment else None,
            ))
        return lines

    def total_charges(self) -> float:
        return sum((float(v[3]) if v[3] else 0.0) for v in
                   (self.tree.item(i, "values") for i in self.tree.get_children()))

    def total_payments(self) -> float:
        return sum((float(v[4]) if v[4] else 0.0) for v in
                   (self.tree.item(i, "values") for i in self.tree.get_children()))


class BillingApp(ttk.Frame):
    def __init__(self, root):
        super().__init__(root)
        self.root = root
        self.pack(fill="both", expand=True)

        scroller = ScrollableFrame(self)
        scroller.pack(fill="both", expand=True)
        form = scroller.body

        settings = load_settings()

        # -- statement info --------------------------------------------
        section(form, "Statement")
        self.statement_number = LabeledEntry(form, "Statement #", settings.get("last_statement_number", "1"))
        self.statement_number.pack(fill="x", pady=2)
        self.statement_date = LabeledEntry(form, "Statement Date (MM/DD/YYYY)", date.today().strftime("%m/%d/%Y"))
        self.statement_date.pack(fill="x", pady=2)

        # -- your company -------------------------------------------------
        section(form, "Your Company")
        self.company_name = LabeledEntry(form, "Company Name", settings.get("company_name", ""))
        self.company_name.pack(fill="x", pady=2)
        self.company_address = LabeledEntry(form, "City, State ZIP", settings.get("company_address", ""))
        self.company_address.pack(fill="x", pady=2)
        self.company_phone = LabeledEntry(form, "Phone", settings.get("company_phone", ""))
        self.company_phone.pack(fill="x", pady=2)
        self.company_email = LabeledEntry(form, "Email", settings.get("company_email", ""))
        self.company_email.pack(fill="x", pady=2)
        self.company_website = LabeledEntry(form, "Website", settings.get("company_website", ""))
        self.company_website.pack(fill="x", pady=2)

        logo_row = ttk.Frame(form)
        logo_row.pack(fill="x", pady=2)
        ttk.Label(logo_row, text="Company Logo", width=22, anchor="w").pack(side="left")
        self.company_logo_path = tk.StringVar(value=settings.get("company_logo_path", ""))
        self.logo_preview_label = ttk.Label(logo_row)
        self.logo_preview_label.pack(side="left", padx=(0, 8))
        button_col = ttk.Frame(logo_row)
        button_col.pack(side="left")
        ttk.Button(button_col, text="Browse...", command=self.browse_logo).pack(anchor="w")
        ttk.Button(button_col, text="Clear (use template default)", command=self.clear_logo).pack(anchor="w", pady=(2, 0))
        self._logo_preview_image = None  # keep a reference so Tk doesn't garbage-collect it
        self.update_logo_preview()
        ttk.Label(form, text="Replaces the logo on the statement, fit to the same fixed size the "
                               "template uses -- any image works, it won't be stretched out of shape.",
                  foreground="#666", wraplength=560, justify="left").pack(anchor="w", pady=(0, 4))

        theme_row = ttk.Frame(form)
        theme_row.pack(fill="x", pady=2)
        ttk.Label(theme_row, text="Color Theme", width=22, anchor="w").pack(side="left")
        saved_theme = settings.get("color_theme", theme.DEFAULT_COLOR_THEME)
        self.color_theme_var = tk.StringVar(
            value=saved_theme if saved_theme in theme.COLOR_THEMES else theme.DEFAULT_COLOR_THEME)
        ttk.Combobox(theme_row, textvariable=self.color_theme_var, state="readonly", width=28,
                     values=list(theme.COLOR_THEMES.keys())).pack(side="left")

        font_row = ttk.Frame(form)
        font_row.pack(fill="x", pady=2)
        ttk.Label(font_row, text="Font", width=22, anchor="w").pack(side="left")
        saved_font = settings.get("font_choice", theme.DEFAULT_FONT)
        self.font_choice_var = tk.StringVar(
            value=saved_font if saved_font in theme.FONT_CHOICES else theme.DEFAULT_FONT)
        ttk.Combobox(font_row, textvariable=self.font_choice_var, state="readonly", width=28,
                     values=list(theme.FONT_CHOICES.keys())).pack(side="left")

        self.remember_company = tk.BooleanVar(value=True)
        ttk.Checkbutton(form, text="Remember these company fields (including logo, color, and font) for next time",
                         variable=self.remember_company).pack(anchor="w", pady=(2, 8))

        # -- bill to -----------------------------------------------------
        section(form, "Bill To (Customer)")
        self.customer_name = LabeledEntry(form, "Customer / Company Name")
        self.customer_name.pack(fill="x", pady=2)
        self.contact_name = LabeledEntry(form, "Contact Name")
        self.contact_name.pack(fill="x", pady=2)
        self.billing_address = LabeledEntry(form, "Billing Address")
        self.billing_address.pack(fill="x", pady=2)
        self.customer_city_state_zip = LabeledEntry(form, "City, State ZIP")
        self.customer_city_state_zip.pack(fill="x", pady=2)
        self.customer_email = LabeledEntry(form, "Email")
        self.customer_email.pack(fill="x", pady=2)
        self.customer_phone = LabeledEntry(form, "Phone")
        self.customer_phone.pack(fill="x", pady=2)

        # -- account summary ----------------------------------------------
        section(form, "Account Summary")
        self.previous_balance = LabeledEntry(form, "Previous Balance", "0.00")
        self.previous_balance.pack(fill="x", pady=2)
        self.past_due = LabeledEntry(form, "Past Due", "0.00")
        self.past_due.pack(fill="x", pady=2)

        computed_row = ttk.Frame(form)
        computed_row.pack(fill="x", pady=(4, 8))
        ttk.Label(computed_row, text="Payments/Credits and New Charges are always the sums of the "
                                       "Statement Activity lines below -- they can't drift out of sync "
                                       "with what's on the table. Amount Due updates live.",
                  foreground="#666", wraplength=560, justify="left").pack(anchor="w")
        self.computed_label = ttk.Label(
            computed_row,
            text="Payments/Credits: $0.00     New Charges: $0.00     Amount Due: $0.00",
            font=("", 10, "bold"))
        self.computed_label.pack(anchor="w", pady=(2, 0))

        # -- statement activity ---------------------------------------------
        section(form, "Statement Activity")
        self.activity = ActivityTable(form, on_change=self.recalculate)
        self.activity.pack(fill="x", pady=2)

        # -- payment information -------------------------------------------
        section(form, "Payment Information")
        self.payment_methods = LabeledEntry(form, "Payment Methods", "ACH / Check / Card / Online")
        self.payment_methods.pack(fill="x", pady=2)
        self.payable_to = LabeledEntry(form, "Make Checks Payable To", settings.get("payable_to", ""))
        self.payable_to.pack(fill="x", pady=2)
        self.payment_instructions = LabeledText(form, "Payment Link / Instructions", height=2)
        self.payment_instructions.pack(fill="x", pady=2)
        self.payment_due_date = LabeledEntry(
            form, "Payment Due Date (MM/DD/YYYY)",
            (date.today() + timedelta(days=30)).strftime("%m/%d/%Y"))
        self.payment_due_date.pack(fill="x", pady=2)

        # -- notes ------------------------------------------------------------
        section(form, "Notes / Terms")
        self.notes_terms = LabeledText(form, "", height=4)
        self.notes_terms.pack(fill="x", pady=2)

        # -- actions -----------------------------------------------------------
        action_row = ttk.Frame(form)
        action_row.pack(fill="x", pady=16)
        ttk.Button(action_row, text="Generate Statement...", command=self.generate).pack(side="left")
        ttk.Button(action_row, text="Reset Form", command=self.reset_form).pack(side="left", padx=(8, 0))

        # Wired last, once every widget collect_data()/recalculate() touch
        # actually exists. previous_balance is the only manually-typed
        # field the totals depend on; the activity table drives its own
        # recalculate() via the on_change callback given to ActivityTable above.
        self.previous_balance.var.trace_add("write", lambda *a: self.recalculate())
        self.recalculate()

    # -- behavior -------------------------------------------------------------

    def recalculate(self):
        """Recomputes payments_credits/new_charges/amount_due via
        statement_builder.compute_totals -- the exact same function
        generate() uses -- so the live preview and the generated document
        can never disagree. Silently leaves the last good display alone if
        a field is mid-edit and not parseable yet (e.g. a lone "-" while
        typing a negative number) rather than popping an error on every
        keystroke; Generate still validates loudly."""
        try:
            data = self.collect_data()
        except ValueError:
            return None
        self.computed_label.configure(
            text=f"Payments/Credits: {money(data.payments_credits)}     "
                  f"New Charges: {money(data.new_charges)}     "
                  f"Amount Due: {money(data.amount_due)}"
        )
        return data

    def collect_data(self) -> StatementData:
        previous_balance = parse_money(self.previous_balance.get(), "Previous Balance")
        past_due = parse_money(self.past_due.get(), "Past Due")

        data = StatementData(
            statement_number=self.statement_number.get(),
            statement_date=self.statement_date.get(),
            company_name=self.company_name.get(),
            company_address=self.company_address.get(),
            company_phone=self.company_phone.get(),
            company_email=self.company_email.get(),
            company_website=self.company_website.get(),
            company_logo_path=self.company_logo_path.get().strip() or None,
            customer_name=self.customer_name.get(),
            contact_name=self.contact_name.get(),
            billing_address=self.billing_address.get(),
            customer_city_state_zip=self.customer_city_state_zip.get(),
            customer_email=self.customer_email.get(),
            customer_phone=self.customer_phone.get(),
            previous_balance=previous_balance,
            past_due=past_due,
            activity=self.activity.get_lines(),
            payment_methods=self.payment_methods.get(),
            payable_to=self.payable_to.get(),
            payment_instructions=self.payment_instructions.get(),
            payment_due_date=self.payment_due_date.get(),
            notes_terms=self.notes_terms.get(),
            color_theme=self.color_theme_var.get(),
            font_choice=self.font_choice_var.get(),
        )
        compute_totals(data)
        return data

    def generate(self):
        if not self.customer_name.get():
            messagebox.showerror(APP_NAME, "Customer / Company Name is required.")
            return
        try:
            data = self.collect_data()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return

        default_name = f"{data.customer_name} - Statement {data.statement_number or ''}.docx".strip()
        out_path = filedialog.asksaveasfilename(
            title="Save billing statement",
            defaultextension=".docx",
            initialfile=default_name,
            filetypes=[("Word document", "*.docx")],
        )
        if not out_path:
            return

        try:
            build_statement(resource_path(TEMPLATE_FILENAME), data, out_path)
        except Exception as exc:  # a bad template path/permissions error, etc.
            messagebox.showerror(APP_NAME, f"Could not build the statement:\n{exc}")
            return

        if self.remember_company.get():
            save_settings({
                "company_name": data.company_name,
                "company_address": data.company_address,
                "company_phone": data.company_phone,
                "company_email": data.company_email,
                "company_website": data.company_website,
                "company_logo_path": data.company_logo_path or "",
                "payable_to": data.payable_to,
                "color_theme": data.color_theme,
                "font_choice": data.font_choice,
                "last_statement_number": data.statement_number,
            })

        if messagebox.askyesno(APP_NAME, f"Saved:\n{out_path}\n\nOpen it now?"):
            open_file(out_path)

    def reset_form(self):
        if messagebox.askyesno(APP_NAME, "Clear the Bill To, Account Summary, Activity, "
                                            "Payment, and Notes fields? (Your company info is kept.)"):
            for entry in (self.customer_name, self.contact_name, self.billing_address,
                          self.customer_city_state_zip, self.customer_email, self.customer_phone):
                entry.set("")
            for entry in (self.previous_balance, self.past_due):
                entry.set("0.00")
            for item in self.activity.tree.get_children():
                self.activity.tree.delete(item)
            self.payment_instructions.set("")
            self.notes_terms.set("")
            self.recalculate()

    def browse_logo(self):
        path = filedialog.askopenfilename(
            title="Choose a company logo",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with Image.open(path):
                pass  # just confirm PIL can read it before committing to it
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not read that image file:\n{exc}")
            return
        self.company_logo_path.set(path)
        self.update_logo_preview()

    def clear_logo(self):
        self.company_logo_path.set("")
        self.update_logo_preview()

    def update_logo_preview(self):
        path = self.company_logo_path.get().strip()
        box = (110, 74)
        if not path:
            self.logo_preview_label.configure(image="", text="(template default)")
            self._logo_preview_image = None
            return
        try:
            with Image.open(path) as img:
                preview = img.convert("RGBA")
                scale = min(box[0] / preview.width, box[1] / preview.height)
                size = (max(1, round(preview.width * scale)), max(1, round(preview.height * scale)))
                preview = preview.resize(size, Image.LANCZOS)
        except Exception:
            self.logo_preview_label.configure(image="", text="(could not preview)")
            self._logo_preview_image = None
            return
        self._logo_preview_image = ImageTk.PhotoImage(preview)
        self.logo_preview_label.configure(image=self._logo_preview_image, text="")


def section(parent, title: str) -> None:
    ttk.Separator(parent).pack(fill="x", pady=(12, 4))
    ttk.Label(parent, text=title, font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))


def open_file(path: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except OSError:
        pass


def main():
    root = tk.Tk()
    root.title(APP_NAME)
    root.geometry("720x760")
    BillingApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
