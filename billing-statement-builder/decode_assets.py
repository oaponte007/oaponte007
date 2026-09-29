"""Decodes every *.b64 companion file in this directory into its real
binary form, if not already present.

Binary assets (the docx template, the app logo) are committed to the repo
as base64 text rather than as binary files, so a Windows checkout's
line-ending conversion can never corrupt them (see README). This is the
build-time counterpart to billing_app.py's own ensure_decoded(): run once
before packaging so pyinstaller has real files on disk to bundle. Safe to
run repeatedly -- it only writes a file that isn't already there.
"""

from __future__ import annotations

import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent


def decode_all() -> None:
    for b64_path in sorted(HERE.glob("*.b64")):
        real_path = b64_path.with_suffix("")  # strip the trailing .b64
        if real_path.exists():
            continue
        real_path.write_bytes(base64.b64decode(b64_path.read_text()))
        print(f"decoded {b64_path.name} -> {real_path.name}")


if __name__ == "__main__":
    decode_all()
