import sqlite3
import unittest

import app
from tests.fixtures import CLOSURE_VIOLATIONS, RECORDS, WAREHOUSE_VIOLATIONS


def make_db(records=RECORDS):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(app.SCHEMA)
    app.replace_inspections(conn, records)
    return conn


class ParseViolationsTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(app.parse_violations(None), [])
        self.assertEqual(app.parse_violations(""), [])

    def test_splits_entries_and_codes(self):
        items = app.parse_violations(WAREHOUSE_VIOLATIONS)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["codes"], ["114067(f, g)", "114099", "114099.3"])
        self.assertEqual(
            items[0]["description"],
            "Provide an approved warewashing facility. Obtain chlorine test strips",
        )
        self.assertEqual(items[1]["codes"], ["114254-114254.2"])

    def test_entry_without_codes(self):
        last = app.parse_violations(WAREHOUSE_VIOLATIONS)[-1]
        self.assertEqual(last["codes"], [])
        self.assertEqual(
            last["description"],
            "Submit Standard Operating Procedures for review and approval.",
        )

    def test_decimal_code_does_not_split_entry(self):
        items = app.parse_violations("113953.3, 114130 - Wash hands.")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["codes"], ["113953.3", "114130"])

    def test_closure_notice(self):
        items = app.parse_violations(CLOSURE_VIOLATIONS)
        self.assertEqual([i["closure_notice"] for i in items], [False, True])

    def test_hyphen_in_description_is_not_a_code_separator(self):
        items = app.parse_violations("Keep cold-holding units at 41F - or below.")
        self.assertEqual(items[0]["codes"], [])
        self.assertEqual(
            items[0]["description"], "Keep cold-holding units at 41F - or below."
        )


class SplitCodesTest(unittest.TestCase):
    def test_unbalanced_parenthesis_is_kept_verbatim(self):
        self.assertEqual(
            app.split_codes("114101(a), 114125)"), ["114101(a)", "114125)"]
        )


class RecordToRowTest(unittest.TestCase):
    def test_numeric_fields(self):
        row = app.record_to_row(RECORDS[0])
        self.assertEqual(row[9], 3)
        self.assertEqual(row[13], 37.77)

    def test_missing_numbers_become_null(self):
        row = app.record_to_row({"violation_count": "", "latitude": None})
        self.assertIsNone(row[9])
        self.assertIsNone(row[13])


class RestaurantRollupTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def restaurant(self, permit):
        return app.api_restaurant(self.conn, {"permit": permit})["restaurant"]

    def test_unrated_visit_does_not_erase_status(self):
        r = self.restaurant("P001")
        self.assertEqual(r["status"], "Pass")
        self.assertEqual(r["status_date"], "2025-04-10T00:00:00.000")
        self.assertEqual(r["latest_type"], "Site Visit")
        self.assertEqual(r["inspection_count"], 2)

    def test_status_follows_latest_rated_inspection(self):
        r = self.restaurant("P002")
        self.assertEqual(r["status"], "Pass")
        self.assertEqual(r["status_violations"], 0)

    def test_never_rated(self):
        self.assertIsNone(self.restaurant("P003")["status"])

    def test_history_is_newest_first_with_parsed_violations(self):
        data = app.api_restaurant(self.conn, {"permit": "P001"})
        dates = [i["inspection_date"][:10] for i in data["inspections"]]
        self.assertEqual(dates, ["2025-05-27", "2025-04-10"])
        self.assertEqual(data["inspections"][0]["violations"], [])
        self.assertEqual(len(data["inspections"][1]["violations"]), 3)
        self.assertNotIn("violation_codes", data["inspections"][0])

    def test_unknown_and_missing_permit(self):
        self.assertEqual(app.api_restaurant(self.conn, {"permit": "nope"})[1], 404)
        self.assertEqual(app.api_restaurant(self.conn, {})[1], 400)


class NeighborhoodsTest(unittest.TestCase):
    def test_counts_per_neighborhood(self):
        hoods = {
            h["neighborhood"]: h
            for h in app.api_neighborhoods(make_db(), {})["neighborhoods"]
        }
        self.assertEqual(hoods["Mission"]["restaurants"], 2)
        self.assertEqual(hoods["Mission"]["pass"], 2)
        self.assertEqual(hoods["Sunset/Parkside"]["conditional"], 1)
        self.assertEqual(hoods["(Unknown)"]["unrated"], 1)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def names(self, q):
        return [r["dba"] for r in app.api_search(self.conn, {"q": q})["results"]]

    def test_prefix_match_ranks_first(self):
        self.assertEqual(self.names("noodle"), ["NOODLE TEST BAR", "TEST NOODLE HOUSE"])

    def test_tokens_match_across_fields(self):
        self.assertEqual(self.names("diner sample"), ["JOE'S TEST DINER"])

    def test_like_wildcards_are_literal(self):
        self.assertEqual(self.names("%%"), [])
        self.assertEqual(self.names("_e"), [])

    def test_short_query_returns_nothing(self):
        self.assertEqual(self.names("n"), [])


class BrowseTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def test_filter_by_status(self):
        data = app.api_browse(self.conn, {"status": "none"})
        self.assertEqual([r["permit_number"] for r in data["results"]], ["P003"])

    def test_unknown_neighborhood(self):
        data = app.api_browse(self.conn, {"neighborhood": "(Unknown)"})
        self.assertEqual(data["total"], 1)

    def test_status_sort_puts_worst_status_first(self):
        data = app.api_browse(self.conn, {"sort": "status"})
        self.assertEqual(data["results"][0]["status"], "Conditional Pass")

    def test_bad_paging_params(self):
        self.assertEqual(app.api_browse(self.conn, {"limit": "abc"})[1], 400)
        data = app.api_browse(self.conn, {"limit": "-1"})
        self.assertEqual(len(data["results"]), 1)


if __name__ == "__main__":
    unittest.main()
