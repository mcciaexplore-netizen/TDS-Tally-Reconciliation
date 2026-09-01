from __future__ import annotations

import json
from pathlib import Path


ALIAS_PATH = Path(__file__).resolve().parent.parent / "profiles" / "company_aliases.json"


def load_saved_aliases() -> dict[str, str]:
    """Load local, reviewer-confirmed portal-to-Tally aliases if available."""
    if not ALIAS_PATH.exists():
        return {}
    with ALIAS_PATH.open(encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in data.items()):
        raise ValueError("Saved alias profile must be a JSON object of company-name pairs.")
    return data
