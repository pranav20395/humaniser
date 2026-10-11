"""Cheap, model-free checks on a rewrite, against its draft.

They mirror the checks the model's authors recommend (and that their `hz` tool
runs): numbers that went missing or appeared, links that went missing, how much
of the rewrite copies the draft, length, and answering in the wrong language.
They catch slips; they do not prove a rewrite is faithful. Names, dates written
as words and the direction of each claim still need a human read.
"""

import re

CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
LATIN_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")

# Copy-rate units: single CJK characters, runs of other word characters, punctuation.
UNIT = re.compile(r"[㐀-䶿一-鿿豈-﫿]|[^\W_㐀-䶿一-鿿豈-﫿]+|[^\w\s]")

# 1,250  3.5  480k  31.7万  — thousands separators only when followed by exactly 3 digits.
# Only Latin letters and digits block the lookbehind: in "本月20日" the 20 counts.
NUMBER = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?([kK](?![A-Za-z])|万)?")
URL = re.compile(r"https?://[^\s<>\"'）)\]]+")

NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000, "dozen": 12, "half": 0.5,
}
CHINESE_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
                  "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

COPY_LIMIT = 0.5          # share of the rewrite's n-grams found in the draft
MIN_LENGTH_RATIO = 0.35   # rewrite length / draft length
MAX_LENGTH_RATIO = 1.75
WRONG_LANGUAGE_CJK = 5    # an English draft whose rewrite has more CJK chars than this

# Problems worth sampling again for. added_numbers is reported only: the model
# sometimes does correct arithmetic ("from $480k to $305k" -> "saved $175k").
RETRY_ISSUES = ("empty", "truncated", "missing_numbers", "missing_urls", "copy", "too_short", "too_long")


def language(text: str) -> str:
    """'zh' when CJK characters outnumber Latin words, else 'en'."""
    return "zh" if len(CJK.findall(text)) > len(LATIN_WORD.findall(text)) else "en"


def wrong_language(draft: str, rewrite: str) -> bool:
    if language(draft) == "en":
        return len(CJK.findall(rewrite)) > WRONG_LANGUAGE_CJK
    return language(rewrite) == "en" and bool(LATIN_WORD.search(rewrite))


def _normalize(whole: str, frac: str | None, suffix: str | None) -> str:
    value = whole.replace(",", "") + (frac or "")
    if suffix:
        mult = 10_000 if suffix == "万" else 1_000
        n = round(float(value) * mult, 6)
        return str(int(n)) if n == int(n) else str(n)
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value.lstrip("0") or "0"


def numbers(text: str) -> set[str]:
    """Numbers written with digits, normalized: 1,250 -> 1250, 3.50 -> 3.5, 07 -> 7, 480k -> 480000."""
    return {_normalize(*m.groups()) for m in NUMBER.finditer(text)}


def spelled_numbers(text: str) -> set[str]:
    found = set()
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in NUMBER_WORDS:
            n = NUMBER_WORDS[word]
            found.add(str(int(n)) if n == int(n) else str(n))
    for ch in CJK.findall(text):
        if ch in CHINESE_DIGITS:
            found.add(str(CHINESE_DIGITS[ch]))
    return found


def _sort_numbers(values: set[str]) -> list[str]:
    return sorted(values, key=lambda v: (float(v), v))


def missing_numbers(draft: str, rewrite: str) -> list[str]:
    return _sort_numbers(numbers(draft) - numbers(rewrite) - spelled_numbers(rewrite))


def added_numbers(draft: str, rewrite: str) -> list[str]:
    return _sort_numbers(numbers(rewrite) - numbers(draft) - spelled_numbers(draft))


def urls(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in URL.findall(text)]


def missing_urls(draft: str, rewrite: str) -> list[str]:
    return [u for u in dict.fromkeys(urls(draft)) if u not in rewrite]


def _units(text: str) -> list[str]:
    return [u.lower() for u in UNIT.findall(text)]


def copy_rate(draft: str, rewrite: str) -> float:
    """Share of the rewrite's 5-grams (6-grams for Chinese) that also occur in the draft."""
    n = 6 if language(draft) == "zh" else 5
    a, b = _units(draft), _units(rewrite)
    seen = {tuple(a[i:i + n]) for i in range(len(a) - n + 1)}
    grams = [tuple(b[i:i + n]) for i in range(len(b) - n + 1)]
    return sum(g in seen for g in grams) / len(grams) if grams else 0.0


def length(text: str) -> int:
    """Words, counting each CJK character as one."""
    return len(CJK.findall(text)) + len(re.findall(r"[^\W_㐀-䶿一-鿿豈-﫿]+", text))


def check(draft: str, rewrite: str, truncated: bool = False) -> dict:
    """Run every check. `issues` lists problem names; RETRY_ISSUES says which deserve another sample."""
    draft_len = length(draft)
    ratio = length(rewrite) / draft_len if draft_len else 1.0
    result = {
        "missing_numbers": missing_numbers(draft, rewrite),
        "added_numbers": added_numbers(draft, rewrite),
        "missing_urls": missing_urls(draft, rewrite),
        "copy_rate": round(copy_rate(draft, rewrite), 3),
        "length_ratio": round(ratio, 2),
        "wrong_language": bool(rewrite.strip()) and wrong_language(draft, rewrite),
        "truncated": truncated,
    }
    issues = []
    if not rewrite.strip():
        issues.append("empty")
    if truncated:
        issues.append("truncated")
    if result["wrong_language"]:
        issues.append("language")
    for key in ("missing_numbers", "added_numbers", "missing_urls"):
        if result[key]:
            issues.append(key)
    if result["copy_rate"] > COPY_LIMIT:
        issues.append("copy")
    # Length checks mean little on very short drafts.
    if rewrite.strip() and draft_len >= 20:
        if ratio < MIN_LENGTH_RATIO:
            issues.append("too_short")
        elif ratio > MAX_LENGTH_RATIO:
            issues.append("too_long")
    result["issues"] = issues
    return result


def retry_score(result: dict) -> tuple:
    """Lower is better: fewer retry-worthy problems, then fewer missing numbers, then less copying."""
    return (
        sum(i in RETRY_ISSUES or i == "language" for i in result["issues"]),
        len(result["missing_numbers"]),
        result["copy_rate"],
    )
