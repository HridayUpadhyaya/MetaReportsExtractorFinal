from __future__ import annotations
import re


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\n", " ")).strip()


def parse_number(raw: str) -> float:
    """Parse Meta's compact counts.

    Supports the formats seen in India reports, including K/M/B and the
    India-specific L (lakh) column.  Examples: 620.3K, 1.2M, 6.2L, 398.
    The parser requires the whole useful token rather than silently ignoring
    an unknown suffix (the old code incorrectly interpreted 6.2L as 6.2).
    """
    s = clean_text(raw).upper().replace(",", "").strip()
    less_than = s.startswith("<")
    s = s.lstrip("<").strip()

    # Allow a trailing unit word as well as a one-letter suffix.
    m = re.fullmatch(
        r"(-?\d+(?:\.\d+)?)\s*(K|M|B|L|THOUSAND|MILLION|BILLION|LAKH|LAKHS)?\s*",
        s,
        re.I,
    )
    if not m:
        raise ValueError(f"Cannot parse number: {raw!r}")

    n = float(m.group(1))
    unit = (m.group(2) or "").upper()
    mult = {
        "": 1,
        "K": 1_000,
        "THOUSAND": 1_000,
        "L": 100_000,
        "LAKH": 100_000,
        "LAKHS": 100_000,
        "M": 1_000_000,
        "MILLION": 1_000_000,
        "B": 1_000_000_000,
        "BILLION": 1_000_000_000,
    }[unit]
    value = n * mult

    # '<1K' is not exact. Keep the project's existing conservative convention.
    if less_than and value == 0:
        value = mult
    return value


def parse_rate(raw: str) -> float:
    s = clean_text(raw).replace("%", "")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        raise ValueError(f"Cannot parse rate: {raw!r}")
    n = float(m.group(0))
    return n / 100 if n > 1 else n


CATEGORY_RULES = [
    (r"adult nudity|sexual activity", "Adult Nudity and Sexual Activity"),
    (r"bullying|harassment", "Bullying and Harassment"),
    (r"child endangerment.*nudity.*physical abuse|child.*nudity.*physical abuse", "Child Endangerment - Nudity and Physical Abuse"),
    (r"child endangerment.*sexual exploitation|child.*sexual exploitation", "Child Endangerment - Sexual Exploitation"),
    (r"organized hate|organised hate", "Dangerous Organizations and Individuals: Organized Hate"),
    (r"terrorist propaganda|terrorism", 'Dangerous Organizations and Individuals: Terrorism (formerly "Terrorist Propaganda")'),
    (r"hate speech", "Hate Speech"),
    (r"regulated goods.*drug|drugs", "Regulated Goods: Drugs"),
    (r"regulated goods.*firearm|firearms", "Regulated Goods: Firearms"),
    (r"suicide|self[- ]injury", "Suicide and Self-Injury"),
    (r"violent.*graphic", "Violent and Graphic Content"),
    (r"spam", "Spam"),
    (r"child nudity|sexual exploitation.*children|child sexual", "Child Nudity and Sexual Exploitation"),
    (r"violence.*incitement", "Violence and Incitement"),
]


def normalize_category(raw: str) -> str:
    s = clean_text(raw)
    s = re.sub(r"^\s*\d+[\.)]\s*", "", s)
    low = s.lower()
    for pattern, canonical in CATEGORY_RULES:
        if re.search(pattern, low):
            return canonical
    return s
