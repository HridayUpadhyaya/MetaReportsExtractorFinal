import unittest

from src.parser import _find_grievances, _header_indexes, _policy_title_platform, _text_policy_rows


class HeaderDetectionTests(unittest.TestCase):
    def test_merged_table_title_is_skipped(self):
        rows = [
            ["Table 1: Content Actioned and Proactive Rate on Facebook (April 2025)", None, None],
            ["Policy Area", "Content Actioned", "Proactive Rate"],
            ["Hate Speech", "123,400", "98.2%"],
        ]
        self.assertEqual(_header_indexes(rows), (1, 0, 1, 2))

    def test_title_cannot_supply_both_metric_columns(self):
        rows = [["Table 2: Content Actioned and Proactive Rate", "Instagram", "April 2025"]]
        self.assertIsNone(_header_indexes(rows))

    def test_multiline_headers_and_extra_column(self):
        rows = [["Policy\nArea", "Content\nActioned", None, "Proactive\nRate"]]
        self.assertEqual(_header_indexes(rows), (0, 0, 1, 3))

    def test_standard_headers_still_work(self):
        self.assertEqual(
            _header_indexes([["Category", "Pieces of content actioned", "Proactive %"]]),
            (0, 0, 1, 2),
        )

    def test_missing_policy_header_is_rejected(self):
        self.assertIsNone(_header_indexes([["Facebook", "Content Actioned", "Proactive Rate"]]))

    def test_table_title_identifies_its_platform(self):
        self.assertEqual(_policy_title_platform("Table 1: Content Actioned and Proactive Rate on Facebook"), "Facebook")
        self.assertIsNone(_policy_title_platform("13 policy areas on Facebook and 12 on Instagram"))

    def test_complete_text_row_can_recover_clipped_grid(self):
        text = "Table 2: Content Actioned and Proactive Rate on Instagram\n12. Violence and Incitement 82.1K 94.9\n1. unrelated prose 500 10"
        self.assertEqual(list(_text_policy_rows(text)), [("Instagram", "Violence and Incitement", "82.1K", "94.9")])

    def test_grievance_totals_allow_footnotes_and_missing_spaces(self):
        text = "Facebook\nBetween 2025-11-01 and 2025-11-30, we received 12,247** reports.\nInstagram\nBetween 2026-02-01 and 2026-02-28, we received 34,986reports.\nThreads\nBetween 2025-11-01 and 2025-11-30, we received 9** reports."
        self.assertEqual(_find_grievances(text), {"Facebook": 12247, "Instagram": 34986, "Threads": 9})


if __name__ == "__main__":
    unittest.main()
