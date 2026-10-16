"""Write the /api/v1 OpenAPI contract to docs/openapi-v1.json.

Run after an intentional API change:
    python scripts/export_openapi.py
tests/test_api_contract.py fails while the committed file and the live schema differ,
so every contract change shows up in review as a diff of this file.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("TDM_AUTH_MODE", "development")

SNAPSHOT = os.path.join(ROOT, "docs", "openapi-v1.json")


def current_schema() -> dict:
    from api.main import app
    app.openapi_schema = None
    return app.openapi()


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    with open(SNAPSHOT, "w", encoding="utf-8", newline="\n") as f:
        f.write(render(current_schema()))
    print(f"Wrote {SNAPSHOT}")
