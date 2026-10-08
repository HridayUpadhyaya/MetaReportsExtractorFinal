import unittest
from src.site_data import public_dataset


class PublicDatasetTests(unittest.TestCase):
    def test_exports_only_public_fields_in_master_data_order(self):
        rows = [dict(period_end="2025-04-30", platform=platform,
                     policy_order=order, policy_category=category,
                     source_url="private-cache-url", confidence=0.99)
                for platform, order, category in [
                    ("Instagram", 1, "Spam"), ("Facebook", 2, "Hate Speech"),
                    ("Facebook", 1, "Spam"),
                ]]
        data = public_dataset(rows, [], {"rows": 3})
        self.assertEqual([r["policy_category"] for r in data["rows"]], ["Spam", "Hate Speech", "Spam"])
        self.assertEqual([r["workbook_row"] for r in data["rows"]], [2, 3, 4])
        self.assertTrue(all("source_url" not in r and "confidence" not in r for r in data["rows"]))

    def test_audit_note_does_not_publish_local_review_path(self):
        failed = [{"publication_month": "June 2021", "error": "Local PDF failed. Review file: C:/private/file.json",
                   "audit": {"validation": {"report_issues": ["no_policy_rows"]}}}]
        data = public_dataset([], failed, {})
        self.assertEqual(data["excluded_reports"][0]["message"], "June 2021: No content-policy table is present in this report.")

