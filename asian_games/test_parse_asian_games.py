import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

import parse_asian_games as parser


class AsianGamesParserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = parser.load_pages(Path("asian_games/jsonl"))
        cls.by_year_page = {
            (parser.games_year(page), page["page"]["page_number"]): page
            for page in cls.pages
        }

    def test_required_page_classification(self):
        expected = {
            (2018, 15): "Entry List by NOC",
            (2018, 39): "Results",
            (2018, 59): "Results",
            (2018, 89): "Results",
            (2022, 29): "ASC Ranking Points Results",
            (2022, 41): "Results",
            (2022, 90): "Results",
            (2022, 116): "Results",
            (2022, 129): "Results",
        }
        for key, page_type in expected.items():
            page = self.by_year_page[key]
            self.assertEqual(
                parser.required_page_type(
                    parser.games_year(page),
                    page["page"]["page_number"],
                    page["content"]["text"],
                ),
                page_type,
            )

    def test_2018_entry_list_merges_continuation_events(self):
        page = self.by_year_page[(2018, 15)]
        records, warnings = parser.parse_entry_list(page)
        self.assertFalse(warnings)
        ferdous = next(record for record in records if record["athlete_name"] == "FERDOUS Ardina")
        self.assertEqual(ferdous["noc_code"], "BAN")
        self.assertEqual(
            ferdous["events"],
            ["10m Air Pistol Women", "10m Air Pistol Mixed Team"],
        )

    def test_2022_ranking_page(self):
        page = self.by_year_page[(2022, 29)]
        records, warnings = parser.parse_ranking_page(page)
        self.assertFalse(warnings)
        first = records[0]
        self.assertEqual(first["event"], "10m Air Rifle Men")
        self.assertEqual(first["rank"], "1")
        self.assertEqual(first["rating"], "4000")
        self.assertEqual(first["athlete_name"], "SHENG Lihao")
        self.assertEqual(first["noc_code"], "CHN")

    def test_2018_mixed_team_qualification_grouping(self):
        page = self.by_year_page[(2018, 83)]
        records, warnings = parser.parse_results_page(page)
        self.assertFalse(warnings)
        korea = [record for record in records if record["team_name"] == "Republic of Korea"]
        self.assertEqual(len(korea), 2)
        self.assertEqual({record["athlete_name"] for record in korea}, {"JUNG Eunhea", "KIM Hyeonjun"})
        self.assertEqual({record["total"] for record in korea}, {"836.7"})
        self.assertEqual({record["individual_total"] for record in korea}, {"418.8", "417.9"})

    def test_2022_mixed_medal_match_table_fallback(self):
        page = self.by_year_page[(2022, 116)]
        records, warnings = parser.parse_results_page(page)
        self.assertFalse(warnings)
        kazakhstan = [record for record in records if record["team_name"] == "Kazakhstan"]
        self.assertEqual(len(kazakhstan), 2)
        self.assertEqual({record["athlete_name"] for record in kazakhstan}, {"LE Alexandra", "SATPAYEV Islam"})
        self.assertEqual({record["gender"] for record in kazakhstan}, {"F", "M"})
        self.assertEqual({record["total"] for record in kazakhstan}, {"17"})

    def test_end_to_end_audit_coverage(self):
        athletes, results, audit = parser.parse_pages(self.pages)
        self.assertGreater(len(athletes), 0)
        self.assertGreater(len(results), 0)
        audited = {(record["games_year"], record["source_page"]) for record in audit}
        expected_pages = (
            {(2018, page) for page in range(15, 29)}
            | {(2018, page) for page in range(39, 90)}
            | {(2022, page) for page in range(29, 41)}
            | {(2022, page) for page in range(41, 130)}
        )
        self.assertEqual(audited, expected_pages)
        self.assertNotIn("unknown", {record["classification"] for record in audit})

    def test_output_jsonl_files_are_valid_when_present(self):
        parsed_dir = Path("asian_games/parsed")
        for path in parsed_dir.glob("*.jsonl"):
            with path.open(encoding="utf-8") as file_obj:
                for line in file_obj:
                    json.loads(line)


if __name__ == "__main__":
    unittest.main()
