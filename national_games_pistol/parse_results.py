#!/usr/bin/env python3
"""Parse National Games pistol PDFs into championship/event result rows."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pypdfium2 as pdfium


DEFAULT_INPUT_DIR = Path("raws/national_games_pistol")
DEFAULT_OUTPUT_CSV = Path("national_games_pistol/national_games_pistol_results.csv")
FIELDS = ["championship_name", "event_name", "round_name", "state", "rank", "name", "total"]

ROUND_LABELS = (
    "MIXED-MEDAL-MATCH",
    "MEDAL MATCH",
    "SEMIFINAL-1",
    "SEMIFINAL-2",
    "SEMIFINAL",
    "TOP EIGHT",
    "RESULT OF FINALISTS",
    "QUALIFICATION RESULT",
)
STOP_PREFIXES = (
    "Total Competitors",
    "Summary:",
    "Legend:",
    "Page ",
    "DNS ",
    "Finish)",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse National Games pistol PDFs.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    return parser.parse_args()


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def visible_lines(page: object) -> list[str]:
    text = page.get_textpage().get_text_range() or ""
    return [compact(line) for line in text.splitlines() if compact(line)]


def clean_name(value: str) -> str:
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\bP?SH[MF][A-Z0-9]*\b", " ", value)
    return compact(value)


def is_id_line(line: str) -> bool:
    return bool(re.fullmatch(r"\(?P?SH[MF][A-Z0-9]*\)?", line.replace(" ", "")))


def is_noise(line: str) -> bool:
    if not line:
        return True
    if line.startswith(STOP_PREFIXES):
        return True
    if line in {"SrNo", "Comp", "No.", "Comp_No", "Shooter Name", "Name State", "State"}:
        return True
    if line in {"Score", "Series", "Stage", "Sub", "Total", "Penalty", "Tie", "Shot", "Rank Rem", "Rem"}:
        return True
    if "Shooter Name" in line or "Comp No" in line or "Comp_No" in line:
        return True
    if re.fullmatch(r"(?:1st|2nd)?\s*Comp\.?", line):
        return True
    if re.fullmatch(r"(?:1\s+2\s+3(?:\s+4\s+5\s+6)?|FINAL SERIES)", line):
        return True
    return False


def valid_state(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z.]*", value))


def score_like(value: str) -> bool:
    return bool(re.fullmatch(r"(?:DNS|DNF|DSQ|-?\d+(?:\.\d+)?(?:-\d+x|-)?|\d+x|-)", value))


def rank_like(value: str) -> bool:
    return bool(re.fullmatch(r"(?:-|[IVXLCDM]+|\d+)", value))


def championship_from_path(pdf_path: Path) -> str:
    match = re.search(r"(20\d{2})", str(pdf_path))
    if match:
        return f"{match.group(1)} National Games Pistol"
    return "National Games Pistol"


def extract_championship(lines: list[str], pdf_path: Path) -> str:
    for index, line in enumerate(lines):
        if "NATIONAL SHOOTING CHAMPIONSHIP" in line.upper():
            parts = [line]
            if index + 1 < len(lines) and "EVENT" in lines[index + 1].upper():
                parts.append(lines[index + 1])
            return compact(" ".join(parts))
    return championship_from_path(pdf_path)


def normalize_round(line: str) -> str:
    upper = line.upper()
    if "MIXED-MEDAL" in upper:
        return "Mixed Medal Match"
    if "MEDAL MATCH" in upper:
        return "Medal Match"
    if "SEMIFINAL-1" in upper:
        return "Semifinal 1"
    if "SEMIFINAL-2" in upper:
        return "Semifinal 2"
    if "SEMIFINAL" in upper:
        return "Semifinal"
    if "TOP EIGHT" in upper:
        return "Top Eight"
    if "RESULT OF FINALISTS" in upper:
        return "Final"
    if "QUALIFICATION" in upper:
        return "Qualification"
    return compact(line).title()


def extract_event_round(lines: list[str], pdf_path: Path) -> tuple[str, str]:
    event = ""
    round_name = ""
    for index, line in enumerate(lines):
        upper = line.upper()
        if any(label == upper for label in ROUND_LABELS):
            round_name = normalize_round(line)
            for candidate in lines[index + 1 : index + 8]:
                if candidate.startswith("(") and "CHAMPIONSHIP" in candidate.upper():
                    event = candidate
                    break
        if line.startswith("(") and "CHAMPIONSHIP" in upper and not event:
            event = line
    if not round_name:
        for line in lines:
            upper = line.upper()
            if any(label == upper for label in ROUND_LABELS):
                round_name = normalize_round(line)
                break
    if not event:
        event = pdf_path.stem
    return event, round_name


def row_start(line: str) -> tuple[str, str, list[str]] | None:
    match = re.match(r"^(?P<rank>\d+)\s+(?P<comp>\d+)\s+(?P<rest>.+)$", line)
    if not match:
        return None
    return match.group("rank"), match.group("comp"), match.group("rest").split()


def parse_tail(tokens: list[str], default_rank: str = "") -> tuple[str, str, str, int] | None:
    state_index = None
    for index, token in enumerate(tokens):
        if valid_state(token) and index + 1 < len(tokens) and score_like(tokens[index + 1]):
            state_index = index
            break
    if state_index is None:
        return None
    state = tokens[state_index]
    tail = tokens[state_index + 1 :]
    if "DNS" in tail:
        return state, "DNS", "-", state_index
    if "DNF" in tail:
        return state, "DNF", "-", state_index
    if "DSQ" in tail:
        return state, "DSQ", "-", state_index
    if tail and tail[-1] == "C":
        rank = tail[-2] if len(tail) >= 2 and rank_like(tail[-2]) else default_rank
        candidates = tail[: -2 if len(tail) >= 2 and rank_like(tail[-2]) else -1]
        total = ""
        for token in reversed(candidates):
            if re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+x|-)?", token):
                total = token
                break
        return state, total, rank, state_index
    total = ""
    rank = default_rank
    for token in reversed(tail):
        if re.fullmatch(r"\d+(?:\.\d+)?(?:-\d+x|-)?", token):
            total = token
            break
    return state, total, rank or default_rank, state_index


def parse_inline_individual(line: str, championship: str, event: str, round_name: str) -> dict[str, str] | None:
    start = row_start(line)
    if not start:
        return None
    row_rank, _comp, tokens = start
    parsed = parse_tail(tokens, default_rank=row_rank)
    if not parsed:
        return None
    state, total, rank, state_index = parsed
    name = clean_name(" ".join(tokens[:state_index]))
    if not name or not total:
        return None
    return {
        "championship_name": championship,
        "event_name": event,
        "round_name": round_name,
        "state": state,
        "rank": rank,
        "name": name,
        "total": total,
    }


def pending_individual(line: str, championship: str, event: str, round_name: str) -> dict[str, str] | None:
    start = row_start(line)
    if not start:
        return None
    row_rank, comp, tokens = start
    if any(score_like(token) for token in tokens):
        return None
    name = clean_name(" ".join(tokens))
    if not name:
        return None
    return {
        "championship_name": championship,
        "event_name": event,
        "round_name": round_name,
        "state": "",
        "rank": row_rank,
        "name": name,
        "total": "",
        "_comp": comp,
    }


def append_individual(record: dict[str, str], line: str) -> None:
    if is_id_line(line) or is_noise(line):
        return
    tokens = line.split()
    parsed = parse_tail(tokens, default_rank=record.get("rank", ""))
    if parsed:
        state, total, rank, state_index = parsed
        prefix = clean_name(" ".join(tokens[:state_index]))
        if prefix:
            record["name"] = clean_name(f"{record['name']} {prefix}")
        record["state"] = state
        record["total"] = total
        record["rank"] = rank
        return
    if record.get("total", "").endswith("-") and re.fullmatch(r"\d+x", line):
        record["total"] += line
        return
    if re.fullmatch(r"(?:[IVXLCDM]+|\d+)\s+C", line):
        if not record.get("rank"):
            record["rank"] = line.split()[0]
        return
    if not re.search(r"\d", line):
        record["name"] = clean_name(f"{record['name']} {line}")


def parse_final_block(lines: list[str], championship: str, event: str, round_name: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        start = row_start(lines[i])
        if not start:
            i += 1
            continue
        row_rank, comp, tokens = start
        name_parts = [clean_name(" ".join(tokens))]
        i += 1
        while i < len(lines) and not is_id_line(lines[i]) and not row_start(lines[i]):
            if valid_state(lines[i].split()[0]) if lines[i].split() else False:
                break
            if not is_noise(lines[i]) and not re.search(r"\d", lines[i]):
                name_parts.append(clean_name(lines[i]))
            i += 1
        if i < len(lines) and is_id_line(lines[i]):
            i += 1
        state = ""
        total = ""
        rank = row_rank
        if i < len(lines):
            tokens2 = lines[i].split()
            if tokens2 and valid_state(tokens2[0]):
                state = tokens2[0]
                numbers = [token for token in tokens2[1:] if score_like(token)]
                if numbers:
                    total = numbers[-2] if len(numbers) >= 2 and numbers[-1] == "0" else numbers[-1]
                for token in reversed(tokens2):
                    if rank_like(token) and token != "0":
                        rank = token
                        break
                i += 1
        if state and total:
            records.append({
                "championship_name": championship,
                "event_name": event,
                "round_name": round_name,
                "state": state,
                "rank": rank,
                "name": clean_name(" ".join(name_parts)),
                "total": total,
            })
    return records


def parse_mixed(lines: list[str], championship: str, event: str, round_name: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        if not re.fullmatch(r"\d+", lines[i]):
            i += 1
            continue
        rank = lines[i]
        if i + 4 >= len(lines) or not re.fullmatch(r"\d+", lines[i + 1]) or not re.fullmatch(r"\d+", lines[i + 2]):
            i += 1
            continue
        state = lines[i + 3]
        if not valid_state(state):
            i += 1
            continue
        name1 = clean_name(lines[i + 4])
        name2 = clean_name(lines[i + 5]) if i + 5 < len(lines) else ""
        j = i + 6
        total = ""
        individual_scores: list[str] = []
        while j < len(lines) and not re.fullmatch(r"\d+", lines[j]):
            if re.fullmatch(r"\d+(?:-\d+x|-)?", lines[j]):
                if not total:
                    total = lines[j]
                else:
                    individual_scores.append(lines[j])
            elif lines[j] == "C":
                break
            j += 1
        if total:
            score1 = f"{total}({individual_scores[0] if len(individual_scores) > 0 else ''})"
            score2 = f"{total}({individual_scores[1] if len(individual_scores) > 1 else ''})"
            for name, score in ((name1, score1), (name2, score2)):
                if name:
                    records.append({
                        "championship_name": championship,
                        "event_name": event,
                        "round_name": round_name,
                        "state": state,
                        "rank": rank,
                        "name": name,
                        "total": score,
                    })
        i = max(j, i + 1)
    return records


def parse_stage_blocks(lines: list[str], championship: str, event: str, round_name: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        start = row_start(lines[i])
        if not start:
            i += 1
            continue
        row_rank, _comp, tokens = start
        block = [lines[i]]
        i += 1
        while i < len(lines) and not row_start(lines[i]) and not lines[i].startswith(STOP_PREFIXES):
            block.append(lines[i])
            i += 1
        flat_tokens: list[str] = []
        for line in block:
            if is_id_line(line) or is_noise(line):
                continue
            flat_tokens.extend(line.split())
        if len(flat_tokens) < 8:
            continue

        state_index = None
        for index, token in enumerate(flat_tokens):
            if index > 2 and valid_state(token) and index + 1 < len(flat_tokens) and flat_tokens[index + 1] == "Stage1":
                state_index = index
                break
        if state_index is None:
            continue
        name = clean_name(" ".join(flat_tokens[2:state_index]))
        state = flat_tokens[state_index]
        total = ""
        rank = row_rank
        for index, token in enumerate(flat_tokens):
            if token == "-0" and index + 1 < len(flat_tokens):
                total = flat_tokens[index + 1]
                if index + 2 < len(flat_tokens) and rank_like(flat_tokens[index + 2]):
                    rank = flat_tokens[index + 2]
                break
        if not total:
            for token in reversed(flat_tokens):
                if re.fullmatch(r"\d+(?:-\d+x|-)?", token):
                    total = token
                    break
        if name and state and total:
            records.append({
                "championship_name": championship,
                "event_name": event,
                "round_name": round_name,
                "state": state,
                "rank": rank,
                "name": name,
                "total": total,
            })
    return records


def parse_page(lines: list[str], pdf_path: Path, state_by_comp: dict[str, str]) -> list[dict[str, str]]:
    championship = extract_championship(lines, pdf_path)
    event, round_name = extract_event_round(lines, pdf_path)
    if "MIXED TEAM" in event.upper():
        return parse_mixed(lines, championship, event, round_name)
    if any("Stage1" in line for line in lines) and any("Stage2" in line for line in lines):
        return parse_stage_blocks(lines, championship, event, round_name)
    if any("1st Comp" in line for line in lines) or any("FINAL SERIES" in line for line in lines):
        final_records = parse_final_block(lines, championship, event, round_name)
        for record in final_records:
            if not record["state"]:
                comp = record.get("_comp", "")
                record["state"] = state_by_comp.get(comp, "")
        return final_records

    records: list[dict[str, str]] = []
    pending: dict[str, str] | None = None
    for line in lines:
        if is_noise(line) or line.startswith("(") and "CHAMPIONSHIP" in line.upper():
            continue
        parsed = parse_inline_individual(line, championship, event, round_name)
        if parsed:
            records.append(parsed)
            pending = None
            continue
        start = pending_individual(line, championship, event, round_name)
        if start:
            records.append(start)
            pending = start
            continue
        if pending:
            append_individual(pending, line)
            if pending["state"] and pending["total"]:
                state_by_comp[pending.get("_comp", "")] = pending["state"]
                pending = None
    return [{k: record.get(k, "") for k in FIELDS} for record in records if record.get("state") and record.get("total")]


def parse_pdf(pdf_path: Path) -> list[dict[str, str]]:
    pdf = pdfium.PdfDocument(pdf_path)
    records: list[dict[str, str]] = []
    state_by_comp: dict[str, str] = {}
    try:
        pages = [visible_lines(page) for page in pdf]
        # First pass harvests states from qualification-style rows.
        for lines in pages:
            for line in lines:
                parsed = parse_inline_individual(line, championship_from_path(pdf_path), pdf_path.stem, "")
                if parsed:
                    start = row_start(line)
                    if start:
                        state_by_comp[start[1]] = parsed["state"]
        for lines in pages:
            records.extend(parse_page(lines, pdf_path, state_by_comp))
    finally:
        pdf.close()
    bad_name_markers = ("Previous Records", "SrNo", "Comp", "Shooter", "Total Competitors", "CHAMPIONSHIP", "Penalty Total", "Rank Rem")
    return [
        record
        for record in records
        if not any(marker in record["name"] for marker in bad_name_markers)
        and not (record["total"].isdigit() and record["total"] == record["rank"])
    ]


def write_csv(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)


def main() -> None:
    args = parse_args()
    pdf_paths = sorted(args.input_dir.rglob("*.pdf"))
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
