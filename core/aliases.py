from __future__ import annotations

import json
from pathlib import Path


ALIAS_PATH = Path(__file__).resolve().parent.parent / "profiles" / "company_aliases.json"

# Confirmed local business-name variations. These ship with the app so a missing
# optional profile file never causes known pairs to regress to unmatched rows.
DEFAULT_ALIASES = {
    "3D ENGINEERING AUTOMATION LLP": "3D ENGINEERING / TDS 2024-25",
    "DAR AL HANDASAH CONSULTANTS (SHAIR & PARTNERS) INDIA PRIVATE LIMITED": "Dar Ai Handasah / Tds 2024-25",
    "BRAINIAC GLOBAL CONSULTING PRIVATE LIMITED": "BRAINAC / TDS 2024-25",
    "GULMOHAR PACK TECH INDIA PRIVATE LIMITED": "GULMOHOR PACK / TDS 2024-25",
    "VIRENDRA VIJAY GHEWARE": "Gheware Financial / TDS 24-25",
    "EQUINOX EPC ENGINEERING INDIA PRIVATE LIMITED": "EQUINOX EPC ENGG/TDS 2024-25",
    "EMCURE PHARMACEUTICALS LIMITED": "EMCURE PHARMA / 2024-25",
    "DEEPAK NOVOCHEM TECHNOLOGIES LIMITED": "Deepak Novachem / Tds 2024-25",
    "GE INDIA INDUSTRIAL PRIVATE LIMITED": "GE INDIA / TDS 2024-25",
    "P N GADGIL": "PNG",
    "MSME-DEVELOPMENT AND FACILITATION OFFICE": "MSME DFO / TDS 2024-25",
}


def load_saved_aliases() -> dict[str, str]:
    """Load local, reviewer-confirmed portal-to-Tally aliases if available."""
    if not ALIAS_PATH.exists():
        return dict(DEFAULT_ALIASES)
    with ALIAS_PATH.open(encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
        raise ValueError("Saved alias profile must be a JSON object of company-name pairs.")
    return {**DEFAULT_ALIASES, **data}
