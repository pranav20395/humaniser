from humaniser.checks import (added_numbers, check, copy_rate, language, missing_numbers, missing_urls, numbers,
                              retry_score, wrong_language)
from humaniser.prompt import FINGERPRINT, SEP, build_prompt, fingerprint


def test_prompt_matches_published_fingerprint():
    assert fingerprint() == FINGERPRINT
    assert build_prompt("  draft \n\n").endswith("\n\ndraft" + SEP)


def test_numbers_are_normalized():
    assert numbers("1,250 apples, 3.50 dollars, 07:30, 480k users, 31.7万人") == {
        "1250", "3.5", "7", "30", "480000", "317000"}
    assert numbers("本月20日前后") == {"20"}
    assert numbers("MB-2047 and B2B") == {"2047"}
    assert numbers("1.1k") == {"1100"}


def test_missing_and_added_numbers():
    draft = "We reviewed 88 files; 12 remain. Deadline: March 14."
    assert missing_numbers(draft, "Twelve files left of 88, due March 14.") == []
    assert missing_numbers(draft, "Most files are done, due March 14.") == ["12", "88"]
    assert added_numbers(draft, "88 done, 12 left, 100 total, due March 14.") == ["100"]
    assert added_numbers("three teams met", "3 teams met") == []


def test_copy_rate():
    draft = "the quick brown fox jumps over the lazy dog every single day"
    assert copy_rate(draft, draft) == 1.0
    assert copy_rate(draft, "a fast fox leaps across a sleepy hound daily") == 0.0


def test_language():
    assert language("Hello there, how are you") == "en"
    assert language("大家好，今天开会") == "zh"
    assert wrong_language("Please deploy the API fix today", "请今天部署这个API修复")
    assert not wrong_language("Please deploy the API fix today", "Ship the API fix today, please.")
    assert wrong_language("请今天部署修复", "Please deploy the fix today")


def test_missing_urls():
    draft = "Docs at https://example.com/a. Also https://example.com/b"
    assert missing_urls(draft, "See https://example.com/a for docs.") == ["https://example.com/b"]


def test_check_flags_issues():
    draft = " ".join(["The team shipped 42 features this quarter and fixed many bugs."] * 3)
    result = check(draft, "Shipped stuff.", truncated=True)
    assert {"truncated", "missing_numbers", "too_short"} <= set(result["issues"])
    ok = check(draft, "This quarter the team shipped 42 features. Lots of bugs got fixed too, again and again.")
    assert "missing_numbers" not in ok["issues"]
    assert retry_score(ok) < retry_score(result)
    assert check(draft, "")["issues"][0] == "empty"
