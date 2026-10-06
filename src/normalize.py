from __future__ import annotations
import re


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\n", " ")).strip()


def parse_number(raw: str) -> float:
    s = clean_text(raw).upper().replace(",", "").strip()
    less_than = s.startswith("<")
    s = s.lstrip("<").strip()
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*([KMB])?", s)
    if not m:
        raise ValueError(f"Cannot parse number: {raw!r}")
    n = float(m.group(1))
    mult = {None: 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[m.group(2)]
    value = n * mult
    # For '<1 K', preserve the template's conservative convention of 1000.
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
