from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_CATALOG = Path("data/catalogs/standardhidraulicasau_catalog.jsonl")
DEFAULT_OUTPUT = Path("/tmp/standardhidraulicasau_catalog_with_images.jsonl")
IKANSAS_1_VIA_IMAGE_URL = "https://www.standardhidraulica.com/Images/boxes/ikansas1via.jpg"


def clean_spaces(value: object) -> str:
    return " ".join(str(value or "").split())


def _looks_like_ikansas_1_via(row: dict) -> bool:
    text = clean_spaces(f"{row.get('name', '')} {row.get('source_url', '')}").casefold()
    return "ikansas" in text and ("1 via" in text or "1 vía" in text)


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if clean_spaces(line):
            rows.append(json.loads(line))
    return rows


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    temp_path.replace(path)


def backfill(catalog_path: Path, output_path: Path) -> dict[str, int | str]:
    rows = load_rows(catalog_path)
    rows_updated = 0

    for row in rows:
        if clean_spaces(row.get("image_url", "")):
            continue

        if _looks_like_ikansas_1_via(row):
            row["image_url"] = IKANSAS_1_VIA_IMAGE_URL
            rows_updated += 1

    write_rows(output_path, rows)

    return {
        "total_rows": len(rows),
        "source_urls": len({clean_spaces(row.get("source_url", "")) for row in rows if clean_spaces(row.get("source_url", ""))}),
        "rows_updated": rows_updated,
        "image_url_empty": sum(1 for row in rows if not clean_spaces(row.get("image_url", ""))),
        "output": str(output_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill image_url for Standard Hidraulica catalog rows.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Standard Hidraulica JSONL catalog path")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="Output JSONL path")
    parser.add_argument("--in-place", action="store_true", help="Overwrite the source catalog")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    catalog_path = Path(args.catalog)
    output_path = catalog_path if args.in_place else Path(args.out)

    summary = backfill(catalog_path, output_path)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
