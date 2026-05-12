#!/usr/bin/env python3
"""Convert parsed Asian Games results to the requested compact schema."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_PARSED_DIR = Path("asian_games/parsed")
DEFAULT_OUTPUT = Path("asian_games/parsed/asian_games_results_compact.jsonl")
DEFAULT_CSV_OUTPUT = Path("asian_games/parsed/asian_games_results_compact.csv")
OUTPUT_FIELDS = [
    "championship_name",
    "event__name",
    "round_name",
    "rank",
    "name",
    "dob",
    "score",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert parsed Asian Games results to championship_name, "
            "event__name, round_name, rank, name, dob, score."
        )
    )
    parser.add_argument(
        "--parsed-dir",
        type=Path,
        default=DEFAULT_PARSED_DIR,
        help=f"Directory containing parsed JSONL files. Default: {DEFAULT_PARSED_DIR}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSONL path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--csv-output",
        type=Path,
        default=DEFAULT_CSV_OUTPUT,
        help=f"Output CSV path. Default: {DEFAULT_CSV_OUTPUT}",
    )
    return parser.parse_args()


def normalize_name(name: str | None) -> str | None:
    if not name:
        return None
    return re.sub(r"\s+", " ", name).strip().casefold()


def championship_name(games_year: int) -> str:
    return f"{games_year} Asian Games"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file_obj:
        return [json.loads(line) for line in file_obj if line.strip()]


def build_dob_index(athlete_records: list[dict[str, Any]]) -> dict[tuple[Any, ...], str]:
    index: dict[tuple[Any, ...], str] = {}
    for record in athlete_records:
        dob = record.get("date_of_birth")
        if not dob:
            continue

        year = record.get("games_year")
        bib_no = record.get("bib_no")
        name = normalize_name(record.get("athlete_name"))
        noc_code = record.get("noc_code")

        if bib_no:
            index[("bib", year, bib_no)] = dob
        if name and noc_code:
            index[("name_noc", year, name, noc_code)] = dob
        if name:
            index.setdefault(("name", year, name), dob)
    return index


def lookup_dob(record: dict[str, Any], dob_index: dict[tuple[Any, ...], str]) -> str | None:
    year = record.get("games_year")
    bib_no = record.get("bib_no")
    name = normalize_name(record.get("athlete_name"))
    noc_code = record.get("noc_code")

    if bib_no and ("bib", year, bib_no) in dob_index:
        return dob_index[("bib", year, bib_no)]
    if name and noc_code and ("name_noc", year, name, noc_code) in dob_index:
        return dob_index[("name_noc", year, name, noc_code)]
    if name and ("name", year, name) in dob_index:
        return dob_index[("name", year, name)]
    return None


def compact_score(record: dict[str, Any]) -> str | None:
    if record.get("individual_total"):
        return record["individual_total"]

    score_detail = record.get("score_detail") or {}
    scores = score_detail.get("scores")
    if isinstance(scores, list) and scores:
        return str(scores[-1])

    individual_scores = score_detail.get("individual_scores")
    if isinstance(individual_scores, list) and individual_scores:
        return str(individual_scores[-1])

    return record.get("total")


def convert_record(
    record: dict[str, Any], dob_index: dict[tuple[Any, ...], str]
) -> dict[str, Any]:
    return {
        "championship_name": championship_name(record["games_year"]),
        "event__name": record.get("event"),
        "round_name": record.get("round"),
        "rank": record.get("rank"),
        "name": record.get("athlete_name") or record.get("team_name"),
        "dob": lookup_dob(record, dob_index),
        "score": compact_score(record),
    }


def main() -> None:
    args = parse_args()
    athletes = load_jsonl(args.parsed_dir / "asian_games_athletes.jsonl")
    results = load_jsonl(args.parsed_dir / "asian_games_results.jsonl")
    dob_index = build_dob_index(athletes)

    converted = [convert_record(result, dob_index) for result in results]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        for record in converted:
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")

    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_output.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(converted)

    print(f"Wrote {len(converted)} compact result records: {args.output}")
    print(f"Wrote {len(converted)} compact CSV rows: {args.csv_output}")


if __name__ == "__main__":
    main()
