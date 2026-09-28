# Coastal HPC Billing Statement Builder

A small Windows program that asks for everything the billing statement
template needs — statement info, your company info, the customer, account
summary, statement activity line items, payment info, and notes/terms —
then generates a filled-in `.docx` for that customer, using
`Jo-Wayne_Billing_Statement_Template.docx` as the base (logo, layout, and
branding stay exactly as in the template; only the placeholder text and
numbers change).

## Running it (no build required)

You don't have to build an `.exe` at all — Python from
[python.org](https://www.python.org/downloads/) already includes Tkinter,
so this runs as a normal double-clickable-enough Windows program once
Python is installed:

```bat
pip install -r requirements.txt
python billing_app.py
```

Keep `billing_app.py`, `statement_builder.py`, and
`Jo-Wayne_Billing_Statement_Template.docx` together in the same folder —
the template is loaded relative to the script.

## Building a standalone .exe (no Python needed to run it)

Run `build_windows_exe.bat` **on a Windows machine** (PyInstaller builds
for whatever OS it runs on — it can't cross-compile a Windows .exe from
Linux/Mac). It installs `pyinstaller` and produces
`dist\Coastal HPC Billing Statement Builder.exe`, a single file you can
copy anywhere and double-click; the template is bundled inside it.

## Using it

1. **Statement** — statement number and date.
2. **Your Company (Coastal HPC)** — address/phone/email/website. Check
   "Remember these company fields for next time" and it's pre-filled on
   every future run (saved to `%APPDATA%\CoastalHPC\billing_builder_settings.json`,
   not to this folder, so it survives moving/rebuilding the app).
3. **Bill To** — the customer being billed.
4. **Account Summary** — enter Previous Balance, Payments/Credits, and
   Past Due yourself (those come from your books, not from this form).
   **New Charges** and **Amount Due** are calculated automatically from the
   Statement Activity lines below — the label updates live once you click
   "Recalculate totals above from these lines" — using
   `Amount Due = Previous Balance − Payments/Credits + New Charges`.
5. **Statement Activity** — add one line per invoice/charge or payment:
   type Date / Invoice # (or `PAYMENT`) / Description / an amount in
   *either* Charges *or* Payments, then click **Add line**. Add as many
   lines as the customer needs — the generated document grows or shrinks
   its table to fit (the template ships with 5 sample rows; add more or
   fewer, it adjusts either way). Select a row and click **Remove
   selected** to delete it.
6. **Payment Information** — payment methods, who checks are payable to,
   payment instructions, and the due date.
7. **Notes / Terms** — anything else (late-fee policy, PO references, a
   thank-you note). Multiple lines are fine.
8. Click **Generate Statement...**, pick where to save it, and it offers
   to open the finished `.docx` right away.

**Reset Form** clears the customer/activity/payment/notes fields for the
next customer, but keeps your company info.

## Files

| File | Purpose |
|---|---|
| `billing_app.py` | The Tkinter GUI — the actual "program." |
| `statement_builder.py` | Document-filling logic, kept separate from the GUI so it's usable/testable on its own. |
| `Jo-Wayne_Billing_Statement_Template.docx` | The base template — logo, layout, and branding come from here unchanged. |
| `requirements.txt` | The one dependency: `python-docx`. |
| `build_windows_exe.bat` | Builds the standalone `.exe` (run on Windows). |
| `test_gui_smoke.py` | A headless test that drives the actual GUI (fills fields, adds/removes activity lines, generates a document) and checks the result — run with `pip install python-docx` then `python test_gui_smoke.py` (needs a display, or `xvfb-run` on Linux) if you change the code and want to re-verify it. |

## Notes on the math

- **New Charges** = sum of every Statement Activity line's Charge amount.
- **Amount Due** = Previous Balance − Payments/Credits + New Charges.
- **Past Due** is entered as its own figure (informational — how much of
  the balance is already overdue) and is *not* added into Amount Due,
  matching how the template presents it as a separate summary column.
- The **Total Amount Due** shown in the Payment Information box always
  mirrors Account Summary's Amount Due.

If your bookkeeping treats any of this differently, the Account Summary
fields are always yours to edit after clicking Recalculate — nothing is
locked.
