"""Coastal HPC's visual identity for this report -- the same navy/cyan
theme and logo already established and verified in
billing-statement-builder/, reused here for consistency across every
Coastal HPC deliverable rather than inventing a second brand.
"""
from __future__ import annotations

from pathlib import Path

from ..decode_assets import decode_all

COMPANY_NAME = "Coastal HPC"
WEBSITE = "www.coastal-hpc.com"
SLOGAN = "Where High Performance Meets High Security."

PRIMARY_HEX = "0B1E33"  # navy -- matches billing-statement-builder's theme
ACCENT_HEX = "00BFEF"  # cyan
ACCENT_TINT_HEX = "EAF8FC"

SEVERITY_COLORS = {
    "critical": "C00000",
    "high": "E36C09",
    "medium": "C9A227",
    "low": "2E7D32",
    "unknown": "6B6B6B",
}
SEVERITY_ORDER = ["critical", "high", "medium", "low", "unknown"]
SEVERITY_LABELS = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
    "unknown": "UNKNOWN",
}

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "coastal_hpc_logo.png"


def ensure_logo() -> Path | None:
    decode_all(ASSETS_DIR.parent)
    return LOGO_PATH if LOGO_PATH.exists() else None
