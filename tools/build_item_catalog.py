from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dune_save_editor.catalog import catalog_from_fmodel, default_catalog_path, write_catalog  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the bundled item catalog from FModel")
    parser.add_argument("source", type=Path, help="Path to CDT_BaseItems.json")
    parser.add_argument("--output", type=Path, default=default_catalog_path())
    args = parser.parse_args()
    items = catalog_from_fmodel(args.source)
    write_catalog(items, args.output)
    print(f"Wrote {len(items)} items to {args.output}")


if __name__ == "__main__":
    main()
