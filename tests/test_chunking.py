from humaniser.chunking import join, split, weight


def roundtrip(text):
    segments = split(text)
    return segments, join(segments, [s.text for s in segments])


def test_short_draft_is_one_piece():
    text = "Hi Nadia,\n\nThe audit is 88% done.\n\n- MB-2047\n- MB-2091\n\nThanks,\nSam"
    segments, back = roundtrip(text)
    assert [s.kind for s in segments] == ["prose"]
    assert back == text


def test_structure_is_kept_out_of_the_model():
    text = ("# Report\n\nFirst paragraph here.\n\n```python\nx = 1\n\ny = 2\n```\n\n"
            "| a | b |\n|---|---|\n| 1 | 2 |\n\n## Next\nA paragraph right under a heading.\n\n---\n\nLast one.")
    segments, back = roundtrip(text)
    assert [(s.kind, s.text.split("\n")[0]) for s in segments] == [
        ("keep", "# Report"), ("prose", "First paragraph here."), ("keep", "```python"), ("keep", "| a | b |"),
        ("keep", "## Next"), ("prose", "A paragraph right under a heading."), ("keep", "---"),
        ("prose", "Last one.")]
    assert back == text


def test_long_draft_is_split_at_paragraphs():
    para = " ".join(["This sentence has exactly eight words in it."] * 10)  # 90 words
    text = "\n\n".join([para] * 9)
    segments, back = roundtrip(text)
    assert len(segments) == 3
    assert all(s.kind == "prose" and weight(s.text) <= 1.0 for s in segments)
    assert back == text


def test_long_paragraph_is_split_at_sentences():
    text = " ".join(f"Sentence number {i} is right here." for i in range(150))
    segments, back = roundtrip(text)
    assert len(segments) > 1
    assert all(weight(s.text) <= 1.0 for s in segments)
    assert [s.joiner for s in segments[1:]] == [" "] * (len(segments) - 1)
    assert back == text


def test_sentence_split_keeps_closing_quotes():
    text = " ".join(f'Then she said "point {i} is done." And left.' for i in range(60))
    _, back = roundtrip(text)
    assert back == text
    zh = "他说：“第一项已经完成。”然后离开了会议室。" * 40
    _, back = roundtrip(zh)
    assert back == zh


def test_long_chinese_paragraph_joins_without_spaces():
    text = "这是一个用于测试的句子，内容没有实际意义。" * 60
    segments, back = roundtrip(text)
    assert len(segments) > 1
    assert all(s.joiner == "" for s in segments)
    assert back == text


def test_empty():
    assert split("  \n\n ") == []
