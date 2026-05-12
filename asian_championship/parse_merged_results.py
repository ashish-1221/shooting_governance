#!/usr/bin/env python3
"""Parse merged Asian Championship result PDFs into compact CSV/JSONL rows.

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
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pdfplumber


DEFAULT_INPUT_DIR = Path("asian_championship/merged")
DEFAULT_OUTPUT_CSV = Path("asian_championship/parsed/asian_championship_results.csv")
DEFAULT_OUTPUT_JSONL = Path("asian_championship/parsed/asian_championship_results.jsonl")
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
LEGEND_TERMS = (
    "Asian Championships",
    "Athlete eliminated",
    "Bib No Bib Number",
    "European Championships",
    "Olympic Games",
    "Qualification Shoot-off",
    "Qualification World Record",
    "Rk Rank",
    "Seconds Sub",
    "Records list",
    "World Championships",
    "World Cup",
    "World Record",
)
LEGEND_SUFFIX_MARKERS = (
    " ASC ",
    " Bib No ",
    " Note Please",
    " OG ",
    " Q ",
    " QS-off ",
    " QWR ",
    " Rk Rank",
    " SO Athlete",
    " Sub ",
    " WC ",
    " WCH ",
    " WR ",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse all PDFs in asian_championship/merged into compact result rows."
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
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Do not OCR pages with missing or broken embedded text.",
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
        return f"{match.group(1)} Asian Championship"
    return "Asian Championship"


def visible_lines(page: Any) -> list[str]:
    text = page.extract_text(layout=True) or ""
    return [compact(line) for line in text.splitlines() if compact(line)]


def has_broken_cid_text(lines: list[str]) -> bool:
    if not lines:
        return True
    joined = " ".join(lines[:12])
    return joined.count("(cid:") >= 3


def ocr_page_lines(pdf_path: Path, page_number: int) -> list[str]:
    gs = shutil.which("gs")
    tesseract = shutil.which("tesseract")
    if not gs or not tesseract:
        return []

    with tempfile.TemporaryDirectory(prefix="asian_championship_ocr_") as temp_dir:
        image_path = Path(temp_dir) / f"page_{page_number}.png"
        render = subprocess.run(
            [
                gs,
                "-q",
                "-dBATCH",
                "-dNOPAUSE",
                "-sDEVICE=pnggray",
                "-r300",
                f"-dFirstPage={page_number}",
                f"-dLastPage={page_number}",
                f"-sOutputFile={image_path}",
                str(pdf_path),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if render.returncode != 0 or not image_path.exists():
            return []

        ocr = subprocess.run(
            [tesseract, str(image_path), "stdout", "--psm", "6"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if ocr.returncode != 0:
            return []
        return [compact(line) for line in ocr.stdout.splitlines() if compact(line)]


def normalize_title(line: str) -> str:
    return compact(line).title()


def normalize_round_name(line: str) -> str | None:
    upper = compact(line).upper()
    if not upper:
        return None
    if "GOLD" in upper and "MEDAL" in upper:
        return "Gold Medal Match"
    if "BRONZE" in upper and "MEDAL" in upper:
        match = re.search(r"\b([12])\b", upper)
        return f"Bronze Medal Match {match.group(1)}" if match else "Bronze Medal Match"
    if "RANKING" in upper and "MATCH" in upper:
        return "Ranking Match"
    if "FINAL" in upper:
        return "Final"
    if "DAY 1" in upper and ("QUAL" in upper or "UALIFICATION" in upper):
        return "Qualification - Day 1"
    if "DAY 2" in upper and ("QUAL" in upper or "UALIFICATION" in upper):
        return "Qualification - Day 2"
    if "QUAL" in upper or "UALIFICATION" in upper or "QALIFICATION" in upper:
        return "Qualification"
    if "ELIMINATION" in upper:
        return "Elimination"
    if "INDIVIDUAL" in upper:
        return "Individual"
    return None


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
        inferred_round = normalize_round_name(upper)
        if inferred_round:
            round_name = inferred_round
            break
        if event is None:
            event = normalize_title(normalized)
        elif round_name is None:
            break

    if event and not round_name:
        joined = " ".join(lines[:14]).upper()
        if "COMPETITION STAGE - ELIMINATION" in joined:
            round_name = "Final"
        elif "RK NAME" in joined or "1ST COMP" in joined or "ELIMINATION" in joined:
            round_name = "Final"
    if event:
        return event, round_name

    for index, line in enumerate(lines[:12]):
        upper = line.upper()
        if not re.search(r"\b(?:AIR|RIFLE|PISTOL|SKEET|TRAP)\b", upper):
            continue
        if re.search(r"\b(?:WR|ASR|QWR|RECORDS?|CHAMPIONSHIP|CHANGWON)\b", upper):
            continue
        candidate = normalize_title(line)
        round_candidate = None
        for following in lines[index + 1 : index + 5]:
            following_upper = following.upper()
            inferred_round = normalize_round_name(following_upper)
            if inferred_round:
                round_candidate = inferred_round
                break
            if re.match(r"^[A-Z]{3}\s+\d{1,2}\s+[A-Z]{3}\s+\d{4}", following_upper):
                break
        if not round_candidate:
            joined = " ".join(lines[index : index + 10]).upper()
            if "COMPETITION STAGE - ELIMINATION" in joined:
                round_candidate = "Final"
            elif "RANK BIB" in joined or "SERIES" in joined:
                round_candidate = "Qualification"
        return candidate, round_candidate

    return None, None


def is_section_end(line: str) -> bool:
    return line.startswith(("Legend", "History", "Release:", "Version of"))


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
    if is_legend_detail(line):
        return True
    return False


def is_legend_detail(line: str) -> bool:
    if line == "Note" or line.startswith(("Note ", "Please note", "C2 ", "D3 ")):
        return True
    return "ISSF website" in line or any(term in line for term in LEGEND_TERMS)


def strip_legend_suffix(line: str) -> str:
    indexes = [line.find(marker) for marker in LEGEND_SUFFIX_MARKERS if line.find(marker) > 0]
    if not indexes:
        return line
    return compact(line[: min(indexes)])


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
    if not round_name and rank.isdigit() and int(rank) <= 8:
        round_name = "Final"
    return {
        "championship_name": championship,
        "event__name": event,
        "round_name": round_name,
        "rank": rank,
        "bib": bib,
        "nme": strip_legend_suffix(nme) if nme else nme,
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
    line = strip_legend_suffix(line)
    if not line or score_tokens(line):
        return False
    if line.startswith(NOISE_PREFIXES):
        return False
    if is_legend_detail(line):
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
    line = strip_legend_suffix(line)
    if not line or is_legend_detail(line):
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


def parse_pdf(pdf_path: Path, use_ocr: bool = True) -> list[dict[str, Any]]:
    championship = championship_name(pdf_path)
    records: list[dict[str, Any]] = []
    current_team: dict[str, Any] | None = None
    pending_individual: dict[str, Any] | None = None
    active_event: str | None = None
    active_round: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            lines = visible_lines(page)
            if use_ocr and has_broken_cid_text(lines):
                ocr_lines = ocr_page_lines(pdf_path, page_number)
                if ocr_lines:
                    lines = ocr_lines
            event, round_name = page_event_round(lines)
            if event and not round_name:
                joined = " ".join(lines[:16]).upper()
                if active_event == event and active_round:
                    round_name = active_round
                elif "RANK BIB" in joined or "SERIES" in joined:
                    round_name = "Qualification"
                elif "RK NAME" in joined or "1ST COMP" in joined or "ELIMINATION" in joined:
                    round_name = "Final"
            if event:
                active_event = event
                active_round = round_name
                current_team = None
                pending_individual = None
            else:
                event = active_event
                round_name = active_round

            for line in lines:
                if is_section_end(line):
                    current_team = None
                    pending_individual = None
                    continue
                if is_legend_detail(line):
                    current_team = None
                    pending_individual = None
                    continue
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
                    total = last_score(scores)
                    if not noc and not total:
                        pending_individual = None
                        continue
                    parsed = row(
                        championship,
                        event,
                        round_name,
                        individual.group("rank"),
                        individual.group("bib"),
                        name,
                        noc,
                        total,
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
        pdf_paths = sorted(args.input_dir.rglob("*.pdf"))
    if not pdf_paths:
        raise SystemExit(f"No PDFs found in {args.input_dir}")

    records: list[dict[str, Any]] = []
    for pdf_path in pdf_paths:
        parsed = parse_pdf(pdf_path, use_ocr=not args.no_ocr)
        records.extend(parsed)
        print(f"Parsed {len(parsed)} rows from {pdf_path}")

    write_jsonl(args.output_jsonl, records)
    write_csv(args.output_csv, records)
    print(f"Wrote {len(records)} rows: {args.output_jsonl}")
    print(f"Wrote {len(records)} rows: {args.output_csv}")


if __name__ == "__main__":
    main()
