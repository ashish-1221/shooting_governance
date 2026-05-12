#!/usr/bin/env python3
"""Parse G. V. Mavalankar/Salgaonkar result PDFs into a compact CSV."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pypdfium2 as pdfium


DEFAULT_INPUT_DIR = Path("raws/gv_salvaonkar_shooting_championship")
DEFAULT_OUTPUT_CSV = Path("gv_salvaonkar_shooting_championship/gv_salvaonkar_results.csv")
FIELDS = [
    "championship_name",
    "event_name",
    "round_name",
    "state",
    "rank",
    "name",
    "total",
]

SUMMARY_PREFIXES = (
    "Summary:",
    "Total Competitors",
    "Legend:",
    "Page ",
    "DNS ",
    ": Did Not",
    "Disqualification",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse GV Salvaonkar result PDFs to CSV.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    return parser.parse_args()


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def visible_lines(page: object) -> list[str]:
    textpage = page.get_textpage()
    text = textpage.get_text_range() or ""
    return [compact(line) for line in text.splitlines() if compact(line)]


def clean_name(value: str) -> str:
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\bP?SHM\d+\b", " ", value)
    value = re.sub(r"^m\s+CHAMPIONSHIP\s+CHENNAI\s+TAMILNADU\s*", " ", value, flags=re.I)
    return compact(value)


def is_id_line(line: str) -> bool:
    return bool(re.fullmatch(r"\(?P?SHM[A-Z0-9]*\)?", line.replace(" ", "")))


def is_summary_line(line: str) -> bool:
    return line.startswith(SUMMARY_PREFIXES)


def is_header_line(line: str) -> bool:
    return (
        line in {"Series", "Score"}
        or line.startswith(("Comp ", "No. Shooter", "SrNo ", "1 2 3 4 5", "1 2 3 4 5 6"))
    )


def looks_like_championship(line: str) -> bool:
    upper = line.upper()
    return "MAVALANKAR" in upper


def extract_header(lines: list[str]) -> tuple[str | None, str | None]:
    championship: str | None = None
    event: str | None = None
    for index, line in enumerate(lines):
        if looks_like_championship(line):
            championship = line
            if "CHAMPIONSHIP" not in line.upper() and index + 1 < len(lines):
                championship = compact(f"{line} {lines[index + 1]}")
        if line.upper() == "QUALIFICATION RESULT":
            for candidate in lines[index + 1 : index + 5]:
                if not is_header_line(candidate):
                    event = candidate
                    break
    return championship, event


def score_token(value: str) -> bool:
    return bool(re.fullmatch(r"(?:DNS|DNF|DSQ|-?\d+(?:-\d+x|-)?|\d+x|-)", value))


def rank_token(value: str) -> bool:
    return bool(re.fullmatch(r"(?:-|[IVXLCDM]+|\d+)", value))


def valid_state(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z.]*", value))


def parse_total_rank(tail: list[str]) -> tuple[str, str]:
    if "DNS" in tail:
        return "DNS", "-"
    if "DNF" in tail:
        return "DNF", "-"
    if "DSQ" in tail:
        return "DSQ", "-"
    if tail and tail[-1] == "C" and len(tail) >= 3:
        rank = tail[-2] if rank_token(tail[-2]) else ""
        if len(tail) >= 4 and re.fullmatch(r"\d+", tail[-3]):
            return tail[-4], rank
        return tail[-3], rank
    for token in reversed(tail):
        if re.fullmatch(r"\d+(?:-\d+x|-)?", token):
            return token, ""
    return "", ""


def row_prefix(line: str) -> tuple[list[str], list[str], int] | None:
    if not re.match(r"^\d+\s+", line):
        return None
    tokens = line.split()
    if len(tokens) < 2:
        return None
    if len(tokens) == 2 and tokens[1] == "C":
        return None

    if len(tokens) >= 5 and all(token.isdigit() for token in tokens[:4]):
        name_start = 4
    elif len(tokens) >= 4 and tokens[0].isdigit() and tokens[1].isdigit():
        name_start = 2
    else:
        name_start = 1
    return tokens[name_start:], tokens, name_start


def parse_inline_row(
    line: str,
    championship: str,
    event: str,
) -> dict[str, str] | None:
    prefix = row_prefix(line)
    if not prefix:
        return None
    name_and_tail, tokens, name_start = prefix

    first_score = None
    for index in range(2, len(name_and_tail)):
        if score_token(name_and_tail[index]):
            first_score = index
            break
    if first_score is None or first_score <= 0:
        return None

    state = name_and_tail[first_score - 1]
    name = clean_name(" ".join(name_and_tail[: first_score - 1]))
    tail = name_and_tail[first_score:]
    total, rank = parse_total_rank(tail)
    if not rank and name_start > 1:
        rank = tokens[0]

    if not name or not valid_state(state) or not total:
        return None
    return {
        "championship_name": championship,
        "event_name": event,
        "round_name": "",
        "state": state,
        "rank": rank,
        "name": name,
        "total": total,
    }


def pending_from_row_start(line: str, championship: str, event: str) -> dict[str, str] | None:
    prefix = row_prefix(line)
    if not prefix:
        return None
    name_and_tail, tokens, name_start = prefix
    if any(score_token(token) for token in name_and_tail):
        return None
    name = clean_name(" ".join(name_and_tail))
    if not name:
        return None
    return {
        "championship_name": championship,
        "event_name": event,
        "round_name": "",
        "state": "",
        "rank": tokens[0] if name_start > 1 else "",
        "name": name,
        "total": "",
    }


def parse_state_score_line(line: str) -> tuple[str, str, str] | None:
    tokens = line.split()
    if len(tokens) < 2 or score_token(tokens[0]) or not valid_state(tokens[0]):
        return None
    if not any(score_token(token) for token in tokens[1:]):
        return None
    total, rank = parse_total_rank(tokens[1:])
    if not total:
        return None
    return tokens[0], total, rank


def append_continuation(record: dict[str, str], line: str) -> None:
    if is_id_line(line) or is_summary_line(line) or is_header_line(line):
        return
    if re.fullmatch(r"\d+x", line):
        if record["total"].endswith("-"):
            record["total"] += line
        return
    if record["total"] and re.fullmatch(r"(?:[IVXLCDM]+|\d+)\s+C", line):
        parts = line.split()
        if not record["rank"]:
            record["rank"] = parts[0]
        return
    state_scores = parse_state_score_line(line)
    if state_scores:
        state, total, rank = state_scores
        record["state"] = state
        record["total"] = total
        record["rank"] = rank
        return
    if record["total"].endswith("-"):
        match = re.search(r"\b(\d+x)\b", line)
        if match:
            record["total"] += match.group(1)
            line = compact(line[: match.start()] + " " + line[match.end() :])
    if not line or score_token(line) or re.search(r"\d", line):
        return
    addition = clean_name(line)
    if addition:
        record["name"] = clean_name(f"{record['name']} {addition}")


def parse_pdf(pdf_path: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    active_championship = ""
    active_event = ""
    pending: dict[str, str] | None = None

    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for page in pdf:
            lines = visible_lines(page)
            championship, event = extract_header(lines)
            if championship:
                active_championship = championship
            if event:
                active_event = event
            if not active_championship or not active_event:
                continue

            for line in lines:
                if (
                    looks_like_championship(line)
                    or line.upper() == "QUALIFICATION RESULT"
                    or line == active_event
                    or is_header_line(line)
                    or is_summary_line(line)
                ):
                    continue
                parsed = parse_inline_row(line, active_championship, active_event)
                if parsed:
                    records.append(parsed)
                    pending = None
                    continue
                pending_start = pending_from_row_start(line, active_championship, active_event)
                if pending_start:
                    records.append(pending_start)
                    pending = pending_start
                    continue
                if pending:
                    append_continuation(pending, line)
                    if pending["state"] and pending["total"] and pending["rank"]:
                        pending = None
    finally:
        pdf.close()

    bad_name_markers = ("Penalty Total", "SrNo", "Shooter Name", "Rank Rem", "Summary", "Legend")
    return [
        record
        for record in records
        if record["state"]
        and record["total"]
        and not any(marker in record["name"] for marker in bad_name_markers)
    ]


def write_csv(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    args = parse_args()
    pdf_paths = sorted(args.input_dir.glob("*.pdf"))
    if not pdf_paths:
        raise SystemExit(f"No PDFs found in {args.input_dir}")

    records: list[dict[str, str]] = []
    for pdf_path in pdf_paths:
        parsed = parse_pdf(pdf_path)
        records.extend(parsed)
        print(f"Parsed {len(parsed)} rows from {pdf_path}")
    write_csv(args.output_csv, records)
    print(f"Wrote {len(records)} rows: {args.output_csv}")


if __name__ == "__main__":
    main()
