"""Generates app_icon.ico -- the .exe's file/taskbar icon -- from the
Coastal HPC logo. Run before pyinstaller in build_windows_exe.bat and
both GitHub Actions workflows, so the logic lives in one place instead of
being copy-pasted into three build scripts.

The source logo is a wide mark+wordmark lockup, not pre-cropped to a
square, so nothing about the actual artwork is guessed at or cropped:
it's padded onto a square white canvas (matching its own background) and
Pillow downsamples that into every icon size Windows actually uses. At
very small sizes (16x16) a full mark+wordmark logo reads as a blurry
color blob rather than crisp detail -- normal and expected for a
non-icon-specific source logo, not a bug in this script.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from decode_assets import decode_all

HERE = Path(__file__).resolve().parent
LOGO_PNG = HERE / "coastal_hpc_logo.png"
ICON_OUT = HERE / "app_icon.ico"

ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def build_icon() -> Path | None:
    decode_all()  # ensures LOGO_PNG exists (if its .b64 is committed) first
    if not LOGO_PNG.exists():
        # The logo is optional cosmetic branding, not a build requirement:
        # skip it rather than failing the whole build when it isn't
        # present yet (build_windows_exe.bat / the workflows only pass
        # --icon to pyinstaller when this actually produced a file).
        print(f"{LOGO_PNG.name} not found (and no .b64 to decode it from); "
              f"skipping app icon generation")
        return None
    with Image.open(LOGO_PNG) as img:
        img = img.convert("RGBA")
        side = max(img.width, img.height)
        canvas = Image.new("RGBA", (side, side), (255, 255, 255, 255))
        offset = ((side - img.width) // 2, (side - img.height) // 2)
        canvas.paste(img, offset, img)
        canvas.save(ICON_OUT, format="ICO", sizes=ICON_SIZES)
    return ICON_OUT


if __name__ == "__main__":
    path = build_icon()
    print(f"wrote {path}" if path else "no icon written")
