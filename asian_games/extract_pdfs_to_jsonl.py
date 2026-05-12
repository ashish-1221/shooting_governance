#!/usr/bin/env python3
"""Extract Asian Games PDF content into page-level JSONL records.

Each output line is one PDF page. The record includes source metadata, page
location details, full text, word coordinates, and detected tables so the
extracted data can be traced back to its original page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pdfplumber


DEFAULT_INPUT_DIR = Path("raws/asian_games")
DEFAULT_OUTPUT_DIR = Path("asian_games/jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract every page from PDFs into JSONL with page metadata."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing PDFs. Default: {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for JSONL outputs. Default: {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "--combined-output",
        type=Path,
        default=None,
        help="Optional single JSONL file containing records from all PDFs.",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        action="append",
        default=None,
        help="Specific PDF path to extract. Can be supplied more than once.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Write indented JSON records. Useful for debugging, larger files.",
    )
    return parser.parse_args()


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_pdf_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    return {str(key): value for key, value in metadata.items() if value is not None}


def normalize_bbox(value: Any) -> list[float] | None:
    if value is None:
        return None
    try:
        return [float(item) for item in value]
    except TypeError:
        return None


def extract_words(page: Any) -> list[dict[str, Any]]:
    words = page.extract_words(
        keep_blank_chars=False,
        use_text_flow=True,
        extra_attrs=["fontname", "size"],
    )
    normalized: list[dict[str, Any]] = []
    for index, word in enumerate(words, start=1):
        normalized.append(
            {
                "word_index": index,
                "text": word.get("text", ""),
                "bbox": {
                    "x0": word.get("x0"),
                    "top": word.get("top"),
                    "x1": word.get("x1"),
                    "bottom": word.get("bottom"),
                },
                "fontname": word.get("fontname"),
                "size": word.get("size"),
                "upright": word.get("upright"),
                "direction": word.get("direction"),
            }
        )
    return normalized


def extract_tables(page: Any) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for table_index, table in enumerate(page.find_tables(), start=1):
        rows = table.extract()
        tables.append(
            {
                "table_index": table_index,
                "bbox": normalize_bbox(table.bbox),
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
                "rows": rows,
            }
        )
    return tables


def page_record(
    pdf_path: Path,
    pdf_sha256: str,
    pdf_metadata: dict[str, Any],
    page: Any,
    page_number: int,
    page_count: int,
) -> dict[str, Any]:
    text = page.extract_text(layout=True, x_tolerance=1, y_tolerance=3) or ""
    words = extract_words(page)
    tables = extract_tables(page)

    return {
        "schema_version": "1.0",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "pdf_path": str(pdf_path),
            "pdf_file_name": pdf_path.name,
            "pdf_stem": pdf_path.stem,
            "pdf_sha256": pdf_sha256,
            "pdf_metadata": pdf_metadata,
        },
        "page": {
            "page_number": page_number,
            "page_index": page_number - 1,
            "page_count": page_count,
            "width": page.width,
            "height": page.height,
            "rotation": page.rotation,
            "bbox": normalize_bbox(page.bbox),
            "cropbox": normalize_bbox(getattr(page, "cropbox", None)),
            "mediabox": normalize_bbox(getattr(page, "mediabox", None)),
        },
        "content": {
            "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "char_count": len(text),
            "word_count": len(words),
            "table_count": len(tables),
            "words": words,
            "tables": tables,
        },
    }


def iter_pdf_paths(input_dir: Path, explicit_pdfs: Iterable[Path] | None) -> list[Path]:
    if explicit_pdfs:
        paths = [path for path in explicit_pdfs]
    else:
        paths = sorted(input_dir.glob("*.pdf"))

    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_text = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"PDF file(s) not found: {missing_text}")

    return paths


def write_pdf_jsonl(pdf_path: Path, output_path: Path, pretty: bool = False) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_sha256 = file_sha256(pdf_path)

    with pdfplumber.open(pdf_path) as pdf, output_path.open("w", encoding="utf-8") as out:
        pdf_metadata = clean_pdf_metadata(pdf.metadata)
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            record = page_record(
                pdf_path=pdf_path,
                pdf_sha256=pdf_sha256,
                pdf_metadata=pdf_metadata,
                page=page,
                page_number=page_number,
                page_count=page_count,
            )
            if pretty:
                out.write(json.dumps(record, ensure_ascii=False, indent=2))
            else:
                out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            out.write("\n")

    return page_count


def write_combined_jsonl(
    pdf_paths: list[Path], combined_output: Path, pretty: bool = False
) -> int:
    combined_output.parent.mkdir(parents=True, exist_ok=True)
    total_pages = 0

    with combined_output.open("w", encoding="utf-8") as out:
        for pdf_path in pdf_paths:
            pdf_sha256 = file_sha256(pdf_path)
            with pdfplumber.open(pdf_path) as pdf:
                pdf_metadata = clean_pdf_metadata(pdf.metadata)
                page_count = len(pdf.pages)
                total_pages += page_count
                for page_number, page in enumerate(pdf.pages, start=1):
                    record = page_record(
                        pdf_path=pdf_path,
                        pdf_sha256=pdf_sha256,
                        pdf_metadata=pdf_metadata,
                        page=page,
                        page_number=page_number,
                        page_count=page_count,
                    )
                    if pretty:
                        out.write(json.dumps(record, ensure_ascii=False, indent=2))
                    else:
                        out.write(
                            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        )
                    out.write("\n")

    return total_pages


def main() -> None:
    args = parse_args()
    pdf_paths = iter_pdf_paths(args.input_dir, args.pdf)
    if not pdf_paths:
        raise SystemExit(f"No PDF files found in {args.input_dir}")

    total_pages = 0
    for pdf_path in pdf_paths:
        output_path = args.output_dir / f"{pdf_path.stem}.jsonl"
        page_count = write_pdf_jsonl(pdf_path, output_path, pretty=args.pretty)
        total_pages += page_count
        print(f"Wrote {page_count} page records: {output_path}")

    if args.combined_output:
        combined_pages = write_combined_jsonl(
            pdf_paths, args.combined_output, pretty=args.pretty
        )
        print(f"Wrote {combined_pages} combined page records: {args.combined_output}")

    print(f"Done. Extracted {total_pages} pages from {len(pdf_paths)} PDF(s).")


if __name__ == "__main__":
    main()
