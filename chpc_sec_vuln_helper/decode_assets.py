"""Decodes every committed *.b64 binary asset back into its real file,
if not already present. Same pattern as billing-statement-builder's
decode_assets.py -- binary assets are committed as base64 text so
Windows checkout line-ending conversion can never corrupt them.
"""
from __future__ import annotations

import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent


def decode_all(root: Path = HERE) -> list[Path]:
    decoded = []
    for b64_path in root.rglob("*.b64"):
        real_path = b64_path.with_suffix("")
        if not real_path.exists():
            real_path.write_bytes(base64.b64decode(b64_path.read_text()))
        decoded.append(real_path)
    return decoded


if __name__ == "__main__":
    for path in decode_all():
        print(f"decoded {path}")
