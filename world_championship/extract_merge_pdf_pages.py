#!/usr/bin/env python3
"""Extract page ranges from World Championship PDFs and merge them.

Examples:
    python3 world_championship/extract_merge_pdf_pages.py \
        --range world_championship_2022.pdf:1-3,7 \
        --range world_championship_2023.pdf:10-12 \
        --output world_championship/merged/world_championship_selected.pdf

Page ranges are 1-based and inclusive. Ranges are emitted in the same order as
the --range arguments and page fragments inside each argument.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pdfplumber


DEFAULT_INPUT_DIR = Path("raws/world_championship")
DEFAULT_OUTPUT = Path("world_championship/merged/world_championship_selected.pdf")


@dataclass(frozen=True)
class PageRange:
    pdf_path: Path
    start_page: int
    end_page: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract selected 1-based page ranges from PDFs and merge them."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing PDF files. Default: {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "--range",
        dest="range_specs",
        action="append",
        required=True,
        help=(
            "PDF and pages to include, formatted as PDF:pages. "
            "Examples: world_championship_2022.pdf:1-5,9 or "
            "world_championship_2022:1-5. Can be supplied more than once."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Merged PDF output path. Default: {DEFAULT_OUTPUT}",
    )
    return parser.parse_args()


def require_ghostscript() -> str:
    gs = shutil.which("gs")
    if not gs:
        raise RuntimeError("Ghostscript executable 'gs' was not found on PATH.")
    return gs


def resolve_pdf(input_dir: Path, raw_name: str) -> Path:
    candidate = Path(raw_name)
    candidates = []
    if candidate.is_absolute() or candidate.exists():
        candidates.append(candidate)
    else:
        candidates.append(input_dir / raw_name)
        if candidate.suffix.lower() != ".pdf":
            candidates.append(input_dir / f"{raw_name}.pdf")

    for path in candidates:
        if path.exists() and path.is_file():
            return path

    tried = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Could not find PDF for {raw_name!r}. Tried: {tried}")


def parse_page_fragment(fragment: str) -> tuple[int, int]:
    fragment = fragment.strip()
    if not fragment:
        raise ValueError("Empty page range fragment")
    if "-" in fragment:
        start_text, end_text = fragment.split("-", 1)
        start_page = int(start_text.strip())
        end_page = int(end_text.strip())
    else:
        start_page = end_page = int(fragment)

    if start_page < 1 or end_page < 1:
        raise ValueError(f"Page numbers must be >= 1: {fragment!r}")
    if start_page > end_page:
        raise ValueError(f"Page range start must be <= end: {fragment!r}")
    return start_page, end_page


def parse_range_specs(input_dir: Path, specs: list[str]) -> list[PageRange]:
    ranges: list[PageRange] = []
    for spec in specs:
        if ":" not in spec:
            raise ValueError(f"Range spec must be formatted as PDF:pages: {spec!r}")
        pdf_name, pages_text = spec.split(":", 1)
        pdf_path = resolve_pdf(input_dir, pdf_name.strip())
        for fragment in pages_text.split(","):
            start_page, end_page = parse_page_fragment(fragment)
            ranges.append(
                PageRange(
                    pdf_path=pdf_path,
                    start_page=start_page,
                    end_page=end_page,
                )
            )
    return ranges


def page_count(pdf_path: Path) -> int:
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def validate_ranges(ranges: list[PageRange]) -> None:
    counts: dict[Path, int] = {}
    for page_range in ranges:
        counts.setdefault(page_range.pdf_path, page_count(page_range.pdf_path))
        count = counts[page_range.pdf_path]
        if page_range.end_page > count:
            raise ValueError(
                f"{page_range.pdf_path} has {count} page(s), but requested "
                f"{page_range.start_page}-{page_range.end_page}."
            )


def run_ghostscript(gs: str, args: list[str]) -> None:
    completed = subprocess.run(
        [gs, *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Ghostscript failed with exit code "
            f"{completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )


def extract_range(gs: str, page_range: PageRange, output_path: Path) -> None:
    run_ghostscript(
        gs,
        [
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            f"-dFirstPage={page_range.start_page}",
            f"-dLastPage={page_range.end_page}",
            f"-sOutputFile={output_path}",
            str(page_range.pdf_path),
        ],
    )


def merge_pdfs(gs: str, inputs: list[Path], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_ghostscript(
        gs,
        [
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            f"-sOutputFile={output_path}",
            *[str(path) for path in inputs],
        ],
    )


def main() -> None:
    args = parse_args()
    gs = require_ghostscript()
    ranges = parse_range_specs(args.input_dir, args.range_specs)
    if not ranges:
        raise SystemExit("No page ranges were supplied.")
    validate_ranges(ranges)

    with tempfile.TemporaryDirectory(prefix="world_championship_pages_") as temp_dir:
        temp_path = Path(temp_dir)
        extracted_files: list[Path] = []
        for index, page_range in enumerate(ranges, start=1):
            output = temp_path / f"{index:04d}_{page_range.pdf_path.stem}_{page_range.start_page}-{page_range.end_page}.pdf"
            extract_range(gs, page_range, output)
            extracted_files.append(output)

        merge_pdfs(gs, extracted_files, args.output)

    total_pages = sum(page_range.end_page - page_range.start_page + 1 for page_range in ranges)
    print(f"Wrote {total_pages} selected page(s) to {args.output}")


if __name__ == "__main__":
    main()
