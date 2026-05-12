#!/usr/bin/env python3
"""Parse merged World Championship result PDFs into compact CSV/JSONL rows.

Output schema:
    championship_name, event__name, round_name, rank, bib, nme, noc, total

Mixed/team events are expanded to one row per listed athlete when athlete rows
are present below a ranked team row. The team score is kept as total, matching
the Asian Games mixed-team handling.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import pdfplumber


DEFAULT_INPUT_DIR = Path("world_championship/merged")
DEFAULT_OUTPUT_CSV = Path("world_championship/parsed/world_championship_results.csv")
DEFAULT_OUTPUT_JSONL = Path("world_championship/parsed/world_championship_results.jsonl")
OUTPUT_FIELDS = [
    "championship_name",
    "event__name",
    "round_name",
    "rank",
    "bib",
    "nme",
    "noc",
    "total",
]

ROUND_KEYWORDS = (
    "GOLD MEDAL MATCH",
    "BRONZE MEDAL MATCH 1",
    "BRONZE MEDAL MATCH 2",
    "BRONZE MEDAL MATCH",
    "RANKING MATCH",
    "QUALIFICATION",
    "ELIMINATION",
    "FINAL",
)
NOISE_PREFIXES = (
    "RESULTS",
    "Rank ",
    "Series",
    "Legend",
    "History",
    "Release:",
    "Version of",
    "OFFICIAL ISSF",
    "Summary",
    "Number of athletes",
    "Bib No Bib Number",
    "___",
    "Nat ",
)
STAGE_WORDS = (
    "Part 1",
    "Part 2",
    "Stage",
    "Precision",
    "Rapid",
    "Kneeling",
    "Prone",
    "Standing",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse all PDFs in world_championship/merged into compact result rows."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Directory containing merged PDFs. Default: {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help=f"CSV output path. Default: {DEFAULT_OUTPUT_CSV}",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=DEFAULT_OUTPUT_JSONL,
        help=f"JSONL output path. Default: {DEFAULT_OUTPUT_JSONL}",
    )
    return parser.parse_args()


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_total(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"-\s+", "-", value.strip())


def championship_name(pdf_path: Path) -> str:
    match = re.search(r"(20\d{2})", pdf_path.stem)
    if match:
        return f"{match.group(1)} World Championship"
    return "World Championship"


def visible_lines(page: Any) -> list[str]:
    text = page.extract_text(layout=True) or ""
    return [compact(line) for line in text.splitlines() if compact(line)]


def normalize_title(line: str) -> str:
    return compact(line).title()


def page_event_round(lines: list[str]) -> tuple[str | None, str | None]:
    event: str | None = None
    round_name: str | None = None
    seen_results = False

    for line in lines[:12]:
        if line == "RESULTS":
            seen_results = True
            continue
        if not seen_results:
            continue
        if re.match(r"^[A-Z]{3}\s+\d{1,2}\s+[A-Z]{3}\s+\d{4}", line):
            break
        normalized = compact(line)
        upper = normalized.upper()
        if upper in ROUND_KEYWORDS:
            round_name = normalize_title(upper)
            break
        if event is None:
            event = normalize_title(normalized)
        elif round_name is None:
            round_name = normalize_title(normalized)
            break

    return event, round_name


def score_tokens(text: str) -> list[str]:
    return [
        normalize_total(token)
        for token in re.findall(
            r"\b(?:DNS|DNF|DSQ|[\d]+(?:\.\d+)?(?:-\s*\d+x)?)(?=[A-Za-z]|\b)",
            text,
        )
    ]


def last_score(text: str) -> str | None:
    tokens = score_tokens(text)
    return tokens[-1] if tokens else None


def is_noise(line: str) -> bool:
    if not line:
        return True
    if line.startswith(NOISE_PREFIXES):
        return True
    if re.match(r"^\d+\s+\d+\s+\d+$", line):
        return True
    if re.match(r"^[1-9]\s+[2-9]\s+[3-9]", line):
        return True
    return False


def team_line_match(line: str) -> re.Match[str] | None:
    return re.match(
        r"^(?P<rank>\d{1,3})\s*(?P<team>[A-Za-z][A-Za-z0-9 .'/&()-]+?)\s+"
        r"(?P<total>DNS|DNF|DSQ|[\d]+(?:\.\d+)?(?:-\s*\d+x)?)(?:\s+(?P<remarks>[A-Z].*))?$",
        line,
    )


def team_qualification_match(line: str) -> re.Match[str] | None:
    return re.match(
        r"^(?P<rank>\d{1,3})\s+(?P<noc>[A-Z]{3}(?:\s+\d+)?)\s+-\s+"
        r"(?P<team>.+?)\s+(?P<scores>DNS|DNF|DSQ|[-\d].*)$",
        line,
    )


def athlete_line_match(line: str) -> re.Match[str] | None:
    return re.match(r"^(?P<bib>\d{3,4})\s+(?P<rest>.+)$", line)


def individual_result_match(line: str) -> re.Match[str] | None:
    return re.match(
        r"^(?P<rank>\d{1,3})\s+(?P<bib>\d{3,4})\s+(?P<rest>.+)$",
        line,
    )


def split_name_noc_scores(rest: str) -> tuple[str, str | None, str]:
    match = re.match(
        r"(?P<name>.+?)(?:\s+(?P<noc>[A-Z]{3})|(?<=[a-z])(?P<noc_glued>[A-Z]{3}))\s+(?P<scores>.+)$",
        rest,
    )
    if match:
        return (
            compact(match.group("name")),
            match.group("noc") or match.group("noc_glued"),
            compact(match.group("scores")),
        )
    fallback = re.match(
        r"(?P<name>.+\s.+)(?P<noc>[A-Z]{3})\s+(?P<scores>(?:DNS|DNF|DSQ|[-\d]).*)$",
        rest,
    )
    if fallback:
        return (
            compact(fallback.group("name")),
            fallback.group("noc"),
            compact(fallback.group("scores")),
        )
    return compact(rest), None, ""


def split_team_athlete(rest: str) -> tuple[str, str]:
    score_start = re.search(r"\s(?:DNS|DNF|DSQ|[\d]+(?:\.\d+)?)\b", rest)
    if not score_start:
        return compact(rest), ""
    return compact(rest[: score_start.start()]), compact(rest[score_start.start() :])


def row(
    championship: str,
    event: str | None,
    round_name: str | None,
    rank: str,
    bib: str | None,
    nme: str | None,
    noc: str | None,
    total: str | None,
) -> dict[str, Any]:
    return {
        "championship_name": championship,
        "event__name": event,
        "round_name": round_name,
        "rank": rank,
        "bib": bib,
        "nme": nme,
        "noc": noc,
        "total": normalize_total(total),
    }


def is_mixed_event(event: str | None) -> bool:
    return bool(event and "Mixed Team" in event)


def event_total(
    event: str | None, team_total: str | None, individual_total: str | None
) -> str | None:
    if is_mixed_event(event) and team_total:
        return f"{normalize_total(team_total)}({normalize_total(individual_total) or ''})"
    return team_total


def append_name_continuation(record: dict[str, Any], line: str) -> bool:
    if not record.get("nme"):
        return False
    if score_tokens(line):
        return False
    if line.startswith(NOISE_PREFIXES):
        return False
    if any(word in line for word in STAGE_WORDS):
        return False
    record["nme"] = compact(f"{record['nme']} {line}")
    return True


def append_name_prefix_before_scores(record: dict[str, Any], line: str) -> bool:
    if not record.get("nme"):
        return False
    if any(word in line for word in STAGE_WORDS):
        return False
    score_start = re.search(r"\s(?:DNS|DNF|DSQ|[\d]+(?:\.\d+)?)\b", line)
    if not score_start:
        return False
    prefix = compact(line[: score_start.start()])
    if not prefix or prefix.startswith(NOISE_PREFIXES):
        return False
    if not re.search(r"[A-Za-z]", prefix) or re.search(r"\d", prefix):
        return False
    record["nme"] = compact(f"{record['nme']} {prefix}")
    return True


def parse_pdf(pdf_path: Path) -> list[dict[str, Any]]:
    championship = championship_name(pdf_path)
    records: list[dict[str, Any]] = []
    current_team: dict[str, Any] | None = None
    pending_individual: dict[str, Any] | None = None
    active_event: str | None = None
    active_round: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            lines = visible_lines(page)
            event, round_name = page_event_round(lines)
            if event:
                active_event = event
                active_round = round_name
                current_team = None
                pending_individual = None
            else:
                event = active_event
                round_name = active_round

            for line in lines:
                if is_noise(line):
                    continue
                if line == event or line == round_name:
                    continue
                if re.match(r"^[A-Z]{3}\s+\d{1,2}\s+[A-Z]{3}\s+\d{4}", line):
                    continue

                team_qual = team_qualification_match(line)
                if team_qual:
                    total = last_score(team_qual.group("scores"))
                    current_team = {
                        "rank": team_qual.group("rank"),
                        "noc": compact(team_qual.group("noc")),
                        "team": compact(team_qual.group("team")),
                        "total": total,
                    }
                    pending_individual = None
                    continue

                team_medal = team_line_match(line)
                if team_medal and "MIXED TEAM" in " ".join(lines[:5]).upper():
                    current_team = {
                        "rank": team_medal.group("rank"),
                        "noc": None,
                        "team": compact(team_medal.group("team")),
                        "total": team_medal.group("total"),
                    }
                    pending_individual = None
                    continue

                athlete = athlete_line_match(line)
                if athlete and current_team:
                    name, scores = split_team_athlete(athlete.group("rest"))
                    individual_total = last_score(scores)
                    records.append(
                        row(
                            championship,
                            event,
                            round_name,
                            current_team["rank"],
                            athlete.group("bib"),
                            name,
                            current_team["noc"],
                            event_total(event, current_team["total"], individual_total),
                        )
                    )
                    pending_individual = None
                    continue

                if current_team and not re.match(r"^\d", line):
                    # Medal-match mixed-team pages list athlete names without bibs.
                    records.append(
                        row(
                            championship,
                            event,
                            round_name,
                            current_team["rank"],
                            None,
                            line,
                            current_team["noc"],
                            event_total(event, current_team["total"], None),
                        )
                    )
                    pending_individual = None
                    continue

                individual = individual_result_match(line)
                if individual:
                    current_team = None
                    name, noc, scores = split_name_noc_scores(individual.group("rest"))
                    parsed = row(
                        championship,
                        event,
                        round_name,
                        individual.group("rank"),
                        individual.group("bib"),
                        name,
                        noc,
                        last_score(scores),
                    )
                    records.append(parsed)
                    pending_individual = parsed
                    continue

                if pending_individual:
                    if append_name_continuation(pending_individual, line):
                        continue
                    append_name_prefix_before_scores(pending_individual, line)
                    stage_score = last_score(line)
                    if stage_score and any(word in line for word in STAGE_WORDS):
                        pending_individual["total"] = stage_score

    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            output.write("\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    args = parse_args()
    pdf_paths = sorted(args.input_dir.glob("*.pdf"))
    if not pdf_paths:
        raise SystemExit(f"No PDFs found in {args.input_dir}")

    records: list[dict[str, Any]] = []
    for pdf_path in pdf_paths:
        parsed = parse_pdf(pdf_path)
        records.extend(parsed)
        print(f"Parsed {len(parsed)} rows from {pdf_path}")

    write_jsonl(args.output_jsonl, records)
    write_csv(args.output_csv, records)
    print(f"Wrote {len(records)} rows: {args.output_jsonl}")
    print(f"Wrote {len(records)} rows: {args.output_csv}")


if __name__ == "__main__":
    main()
