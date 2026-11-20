"""Regenerate the checked-in browser catalog after editing messages.json."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "interfaz"
catalog = json.loads((root / "messages.json").read_text(encoding="utf-8"))
if not isinstance(catalog, dict) or not all(
    isinstance(k, str) and isinstance(v, str) for k, v in catalog.items()
):
    raise ValueError("The message catalog must map strings to strings")
(root / "messages.js").write_text(
    "// Generated from messages.json by tools/build_i18n.py.\n// Edit the JSON catalog, not this browser asset.\nconst MESSAGES="
    + json.dumps(catalog, ensure_ascii=False, indent=2)
    + ";\n",
    encoding="utf-8",
)
print("Generated browser catalog:", len(catalog), "messages")
