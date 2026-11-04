"""Development entry point for the packaged SQLite fixture builder."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from decor2hl7.i18n import Translator
from decor2hl7.sqlite_fixture import create_source


def main() -> int:
    t = Translator()
    parser = argparse.ArgumentParser(description=t.text("cli.sqlite_fixture_description"))
    parser.add_argument("--fixture", required=True, type=Path, help=t.text("cli.sqlite_fixture_fixture_help"))
    parser.add_argument("--output", required=True, type=Path, help=t.text("cli.sqlite_fixture_output_help"))
    parser.add_argument("--written-at", required=True, help=t.text("cli.sqlite_fixture_written_at_help"))
    args = parser.parse_args()
    try:
        result = create_source(args.fixture, args.output, written_at=args.written_at)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    print(json.dumps({"bundle": str(args.output.resolve()), **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
