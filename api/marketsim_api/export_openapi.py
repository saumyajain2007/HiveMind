"""Write generated API artefacts, or check that they are up to date.

    uv run python -m marketsim_api.export_openapi          # write
    uv run python -m marketsim_api.export_openapi --check  # exit 1 if any is stale (CI)

Artefacts:
  api/openapi.json                              -> web types (`pnpm -C web gen:api`)
  web/src/mocks/fixtures/config-schema.json     -> mock API responses, so the mock
  web/src/mocks/fixtures/config-defaults.json      server never drifts from the real one
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .main import create_app
from .routes.config import get_defaults, get_schema
from .settings import Settings

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "api" / "openapi.json"
FIXTURES = ROOT / "web" / "src" / "mocks" / "fixtures"


def _dump(obj: object) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def render() -> str:
    app = create_app(Settings(data_dir=Path("unused"), cors_origins=[], log_json=False))
    return _dump(app.openapi())


def render_all() -> dict[Path, str]:
    return {
        OUT: render(),
        FIXTURES / "config-schema.json": _dump(get_schema().model_dump(mode="json")),
        FIXTURES / "config-defaults.json": _dump(get_defaults().model_dump(mode="json")),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if any generated file is stale")
    args = ap.parse_args()
    stale = []
    for path, text in render_all().items():
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        names = ", ".join(str(p.relative_to(ROOT)) for p in stale)
        print(f"out of date: {names}; run: uv run python -m marketsim_api.export_openapi", file=sys.stderr)
        return 1
    if args.check:
        print("generated API files are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
