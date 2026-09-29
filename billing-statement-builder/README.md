# Coastal HPC Billing Statement Builder

A small Windows program that asks for everything the billing statement
template needs — statement info, your company info, the customer, account
summary, statement activity line items, payment info, and notes/terms —
then generates a filled-in `.docx` for that customer, using
`Jo-Wayne_Billing_Statement_Template.docx` as the base (layout and
branding stay exactly as in the template; the logo, color theme, and font
can all be swapped per company, everything else is placeholder text and
numbers being filled in).

This is meant to be handed to whoever will actually use it — each
company's info, logo, color, and font choices are saved locally on
*their* machine (`%APPDATA%\CoastalHPC\billing_builder_settings.json`),
never anywhere shared, so two different companies running the same copy
of this program each just set it up once for themselves.

The *program itself* carries Coastal HPC's own branding regardless of who
runs it — its window/taskbar icon and the `.exe` file's own icon are
Coastal HPC's logo (`coastal_hpc_logo.png`), separate from whatever logo a
customer sets for their own generated statements.

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

No Windows machine handy? `.github/workflows/build-billing-exe.yml`
builds it on a GitHub-hosted Windows runner on every push to this folder
and uploads it as a workflow artifact — good for your own testing, but
see the next section before handing that particular download to a
customer.

## Giving this to customers: cut a release, don't hand out a raw build

```bash
git tag v1.0.0
git push origin v1.0.0
```

pushing a `v*` tag runs `.github/workflows/release-billing-exe.yml`,
which builds the exe once and publishes it as a **GitHub Release** asset
— a stable `github.com` URL that doesn't expire, and (unlike the
per-push artifact) the exact same file every time, so it's the one to
actually send customers to. Bump the version and re-tag (`v1.0.1`, …)
only when you mean to ship a real update — see the next section for why
that matters.

## "This file is dangerous" — Chrome / Google Safe Browsing, and Windows

There are actually **two separate systems** that can flag this, and it's
worth knowing which one a customer hit, because the fix differs slightly:

- **Chrome's own download warning** ("This file is dangerous" / "Chrome
  blocked this file because it could harm your device") is **Google Safe
  Browsing**, evaluated the moment the file is *downloaded* — before
  Windows ever sees it. It's driven by the file's hash reputation and the
  download URL's reputation, not by anything Windows-specific.
- **Windows SmartScreen / Defender** evaluates separately, when the
  `.exe` is *run*, using its own reputation system.

Both boil down to the same root cause — **an unsigned, freshly-built
file has zero reputation anywhere the first time anyone sees its exact
bytes** — but that also means both share the same real fixes, and one of
them is something already fixed here:

**1. Distribute a stable, versioned release, not a fresh CI artifact
every time.** This was the biggest actual problem: every push was
producing a *brand-new* `.exe` (PyInstaller embeds a build timestamp, so
the file's hash changes every single build) downloaded from a temporary,
auto-expiring Actions-artifact blob URL that Google/Microsoft have never
seen before and never will again — that's close to the worst-case shape
for triggering both systems, independent of anything actually in the
file. Fixed: pushing a version tag (`git tag v1.0.0 && git push origin
v1.0.0`) now builds the exe once and publishes it as a **GitHub Release**
asset instead — a permanent URL on `github.com` itself (a long-established,
generally-trusted domain), and critically, the *same file* every time
customers download that release, so real reputation can actually
accumulate across everyone who downloads and runs it, instead of resetting
to zero on every code change. Don't re-tag/re-release for every tweak —
cut a new version only when you actually mean to ship an update.

**2. Sign it.** This is the actual permanent fix for both systems at
once, immediately, without waiting on reputation to build up: a purchased
code-signing certificate (roughly $70–500/year from a CA like
DigiCert/Sectigo/SSL.com, or Azure Trusted Signing as a cheaper
subscription) run through `signtool sign` as part of the build. That
needs buying and holding a real certificate under Coastal HPC's identity
— not something obtainable from here — but the release workflow is ready
to add a signing step the moment there's a certificate to use.

**For anyone who hits the warning before either of those is in place:**
- Chrome: click the download's **⌵** menu → **Keep** (or **Keep
  dangerous file**) if you trust the source.
- Windows, running the exe: **More info** → **Run anyway** on the blue
  "Windows protected your PC" screen; or if Defender quarantines it,
  Windows Security → Virus & threat protection → Protection history →
  **Restore**.
- Either way, that's a judgment call for whoever's running it to make
  about the source — not something to talk anyone into blindly; the
  source here is plain, readable Python (`statement_builder.py`/
  `billing_app.py`), not obfuscated, if anyone wants to check for
  themselves first.

The `.exe` also carries real version metadata (Company/Product/File
description, visible under right-click → Properties → Details) instead of
shipping blank — good practice, though on its own it doesn't move either
system's warning; reputation and signing are what actually do.

## Using it

1. **Statement** — statement number and date.
2. **Your Company** — address/phone/email/website, plus a
   **Company Logo**: click **Browse...** to pick any image (PNG/JPG/etc.)
   and it replaces the template's logo, scaled to fit the exact same fixed
   box the original logo occupies — the new logo's own aspect ratio is
   always preserved (never stretched/squished), just centered and padded
   to fill that box. **Clear (use template default)** reverts to the
   template's own logo. Check "Remember these company fields (including
   the logo) for next time" and it's all pre-filled on every future run
   (saved to `%APPDATA%\CoastalHPC\billing_builder_settings.json`, not to
   this folder, so it survives moving/rebuilding the app) — handy if you
   run this for more than one company/brand, since each just re-picks its
   own logo once.

   Right below the logo, **Color Theme** and **Font** let each customer
   restyle the whole statement without touching a template file:

   | Color Theme | Font |
   |---|---|
   | Coastal Blue (default) — the template's own navy/cyan | Arial (default) |
   | Forest Green | Calibri |
   | Burgundy Red | Georgia |
   | Slate Purple | Times New Roman |
   | Sunset Orange | Verdana |

   A color theme recolors every header bar, section title, and accent
   label consistently (it's built from the template's own two brand
   colors, so picking a theme never leaves one element the old color by
   accident); ordinary body text and plain row backgrounds stay neutral
   in every theme, the same way the original does. A font applies to the
   *entire* document — heading, table contents, and the footer — and all
   five choices are fonts Windows already has, so the `.docx` never
   substitutes a missing font on someone else's machine. Both are
   remembered the same way the logo is.
3. **Bill To** — the customer being billed.
4. **Account Summary** — enter **Previous Balance** and **Past Due**
   yourself (those come from your books, not from this form).
   **Payments/Credits** and **New Charges** are always the sums of the
   Statement Activity lines below — there's no separate field for them to
   type and accidentally get out of sync with the activity table.
   **Amount Due** updates live as you edit anything, using
   `Amount Due = Previous Balance − Payments/Credits + New Charges`, and
   correctly goes negative (a credit balance) if payments exceed the
   balance plus new charges.
5. **Statement Activity** — add one line per invoice/charge or payment:
   type Date / Invoice # (or `PAYMENT`) / Description / an amount in
   *either* Charges *or* Payments, then click **Add line** — Amount Due
   above updates immediately. Add as many lines as the customer needs —
   the generated document grows or shrinks its table to fit (the template
   ships with 5 sample rows; add more or fewer, it adjusts either way).
   Select a row and click **Remove selected** to delete it.
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
| `theme.py` | The 5 color themes and 5 fonts, and the code that applies a chosen one to a python-docx `Document`. |
| `Jo-Wayne_Billing_Statement_Template.docx` | The base template — logo, layout, and branding come from here unchanged. |
| `coastal_hpc_logo.png` | Coastal HPC's own logo — this app's identity, shown as the window/taskbar icon and the `.exe` file icon. Separate from a *customer's* own logo (which goes in a generated statement, set via the in-app Company Logo picker) and from the template's Jo-Wayne logo (which prints on the statement itself). |
| `decode_assets.py` | Decodes every committed `*.b64` binary asset (the docx template, the logo) back into its real file, if not already present — used at build time and by the app itself the first time it runs from a plain checkout. |
| `make_icon.py` | Builds `app_icon.ico` (a proper multi-resolution Windows icon: 16–256px) from `coastal_hpc_logo.png`, padded onto a transparent square canvas (the logo's own background) so nothing about the logo art is cropped or flattened onto white. Skips gracefully (no error) if the logo asset is ever removed. |
| `requirements.txt` | Dependencies: `python-docx` and `Pillow` (Pillow composites a custom logo onto the template's fixed-size logo box, and builds `app_icon.ico`). |
| `build_windows_exe.bat` | Builds the standalone `.exe` (run on Windows). |
| `version_info.txt` | PyInstaller version resource (Company/Product/File description) embedded in the `.exe`'s Properties. |
| `test_gui_smoke.py` | A headless test that drives the actual GUI (fills fields, adds/removes activity lines, generates a document) and checks the result — run with `pip install python-docx` then `python test_gui_smoke.py` (needs a display, or `xvfb-run` on Linux) if you change the code and want to re-verify it. |

## Notes on the math

- **New Charges** = sum of every Statement Activity line's Charge amount.
- **Payments/Credits** = sum of every Statement Activity line's Payment
  amount — always, automatically. There is deliberately no separate,
  manually-typed Payments/Credits field: an earlier draft had one, and it
  could silently disagree with what was actually entered in the activity
  table (a payment line that didn't reduce the balance). Record every
  payment as an activity line and it's guaranteed to be reflected.
- **Amount Due** = Previous Balance − Payments/Credits + New Charges,
  recalculated live on every edit, and correctly shown as a negative
  number (a credit balance) if payments exceed the balance plus new
  charges — it is never silently clamped to zero.
- **Past Due** is entered as its own figure (informational — how much of
  the balance is already overdue) and is *not* added into Amount Due,
  matching how the template presents it as a separate summary column.
- The **Total Amount Due** shown in the Payment Information box always
  mirrors Account Summary's Amount Due.
- `billing_app.py` (the live preview) and `statement_builder.py` (the
  generated document) both call the exact same `compute_totals()`
  function — not two separate implementations of the formula — so the
  numbers on screen and the numbers in the `.docx` can never disagree.

If your bookkeeping treats Past Due differently, Previous Balance and Past
Due are always yours to edit — nothing is locked except the two figures
that are *definitionally* sums of the activity table.
