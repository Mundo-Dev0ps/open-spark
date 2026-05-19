#!/usr/bin/env python3
"""Dump the FastAPI schema to openapi.yaml at the repo root.

Run locally or in CI:  python scripts/export_openapi.py
CI then `git diff --exit-code openapi.yaml` to ensure it's in sync.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# Mock mode + env secrets so importing/creating the app needs no OBS,
# no keyring, no real keys.
import os  # noqa: E402

os.environ.setdefault("OPENSPARK_MOCK_OBS", "1")
os.environ.setdefault("OPENSPARK_USE_ENV_SECRETS", "1")
os.environ.setdefault("OPENSPARK_LOG_JSON", "0")

from open_spark.config import Settings  # noqa: E402
from open_spark.main import create_app  # noqa: E402

try:
    import yaml  # noqa: E402
except ImportError:
    yaml = None


def main() -> int:
    app = create_app(Settings(mock_obs=True))
    schema = app.openapi()
    out = REPO / "openapi.yaml"
    if yaml is not None:
        out.write_text(
            yaml.safe_dump(schema, sort_keys=True, allow_unicode=True),
            encoding="utf-8",
        )
    else:
        import json

        out.write_text(
            json.dumps(schema, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print("PyYAML missing — wrote JSON content into openapi.yaml")
    print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
