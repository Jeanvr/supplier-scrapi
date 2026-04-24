from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


DEFAULT_CATALOG = Path("data/catalogs/tucaisa_catalog.jsonl")
DEFAULT_OUTPUT = Path("/tmp/tucaisa_catalog_with_images.jsonl")

C850_IMAGES = {
    "cromat": "https://www.tucai.com/wp-content/uploads/2024/04/Chrome-C850-Premium.jpg",
    "blanc": "https://www.tucai.com/wp-content/uploads/2024/04/White-C850-Premium.jpg",
    "negre": "https://www.tucai.com/wp-content/uploads/2024/04/Black-matte-C850-Premium.jpg",
    "bronze": "https://www.tucai.com/wp-content/uploads/2024/04/Antique-Bronze-C850-Premium.jpg",
    "acer": "https://www.tucai.com/wp-content/uploads/2024/04/Steel-C850-Premium.jpg",
    "dorat": "https://www.tucai.com/wp-content/uploads/2024/04/Gold-C850-Premium.jpg",
    "rosat": "https://www.tucai.com/wp-content/uploads/2024/04/Rose-Gold-C850-Premium.jpg",
}
C511_IMAGE_URL = "https://www.tucai.com/wp-content/uploads/2023/06/C-511.png"
C340_IMAGE_URL = "https://www.tucai.com/wp-content/uploads/2023/06/C340-black.png"


def clean_spaces(value: object) -> str:
    return " ".join(str(value or "").split())


def normalize_text(value: object) -> str:
    return clean_spaces(value).casefold()


def preview_ref(row: dict) -> str:
    search_text = clean_spaces(row.get("search_text", ""))
    match = re.search(r"\bTCI[A-Z0-9]+\b", search_text)
    if match:
        return match.group(0)
    return clean_spaces(row.get("supplier_ref", ""))


def _c850_image_url(row: dict) -> str:
    name = normalize_text(row.get("name", ""))

    if "negre" in name:
        return C850_IMAGES["negre"]

    for token in ("cromat", "blanc", "bronze", "acer", "dorat", "rosat"):
        if token in name:
            return C850_IMAGES[token]

    return ""


def detect_image_url(row: dict) -> str:
    name = normalize_text(row.get("name", ""))
    source_url = normalize_text(row.get("source_url", ""))

    if "c850-premium" in source_url:
        return _c850_image_url(row)

    if "c511" in source_url:
        return C511_IMAGE_URL

    if "descargas" in source_url and ("c-340" in name or "c340" in name):
        return C340_IMAGE_URL

    return ""


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


def print_preview(rows: list[dict]) -> None:
    print("referencia | nombre | source_url | image_url")
    print("--- | --- | --- | ---")
    for row in rows:
        print(
            " | ".join(
                (
                    preview_ref(row),
                    clean_spaces(row.get("name", "")),
                    clean_spaces(row.get("source_url", "")),
                    detect_image_url(row),
                )
            )
        )


def backfill(catalog_path: Path, output_path: Path) -> dict[str, int | str]:
    rows = load_rows(catalog_path)
    rows_updated = 0

    print_preview(rows)

    for row in rows:
        if clean_spaces(row.get("image_url", "")):
            continue

        image_url = detect_image_url(row)
        if image_url:
            row["image_url"] = image_url
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
    parser = argparse.ArgumentParser(description="Backfill image_url for Tucai catalog rows.")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Tucai JSONL catalog path")
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
