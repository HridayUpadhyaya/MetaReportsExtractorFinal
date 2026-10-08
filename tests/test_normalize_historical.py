import unittest

from src.normalize import normalize_category, parse_number


class HistoricalNormalizationTests(unittest.TestCase):
    def test_compact_pdf_category_labels(self):
        examples = {
            "1.AdultNudityandSexualActivity": "Adult Nudity and Sexual Activity",
            "3.ChildEndangerment-NudityandPhysicalAbuse": "Child Endangerment - Nudity and Physical Abuse",
            "4.ChildEndangerment-SexualExploitation": "Child Endangerment - Sexual Exploitation",
            "5.DangerousOrganizationsandIndividuals:OrganizedHate": "Dangerous Organizations and Individuals: Organized Hate",
            "7.HateSpeech": "Hate Speech",
            "4. Dangerous Organizations and Individuals: TerroristPropaganda": 'Dangerous Organizations and Individuals: Terrorism (formerly "Terrorist Propaganda")',
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_category(raw), expected)

    def test_unknown_compact_category_is_not_guessed(self):
        self.assertEqual(normalize_category("1.UnrelatedCategory"), "UnrelatedCategory")

    def test_bounded_compact_counts_keep_the_threshold(self):
        self.assertEqual(parse_number(">1 K"), 1000)
        self.assertEqual(parse_number("<1K"), 1000)
        with self.assertRaises(ValueError):
            parse_number("about 1K")
