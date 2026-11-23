"""Write the OpenAPI spec to api/openapi.json, or check that it is up to date.

    uv run python -m marketsim_api.export_openapi          # write
    uv run python -m marketsim_api.export_openapi --check  # exit 1 if stale (CI)

The web app generates its TypeScript types from this file (`pnpm -C web gen:api`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .main import create_app
from .settings import Settings

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def render() -> str:
    app = create_app(Settings(data_dir=Path("unused"), cors_origins=[], log_json=False))
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if api/openapi.json is stale")
    args = ap.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(
                f"{OUT} is out of date; run: uv run python -m marketsim_api.export_openapi", file=sys.stderr
            )
            return 1
        print(f"{OUT} is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
