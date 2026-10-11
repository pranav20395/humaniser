"""Split a draft into pieces the model can rewrite, and put the rewrites back.

The model has an 8192-token context and was trained on single emails, posts and
report sections of a few hundred words, so long drafts are rewritten in pieces
of at most about 350 English words or 600 Chinese characters, split at
paragraph breaks. Headings, fenced code, tables, rules, image/link-only lines
and HTML are kept exactly as written and never sent to the model: it tends to
drop or rephrase them.

A short plain draft stays one piece, which is how the model was meant to be used.
"""

import math
import re
from dataclasses import dataclass

from .checks import CJK, LATIN_WORD

MAX_WORDS = 350
MAX_CJK = 600

FENCE = re.compile(r"^\s{0,3}(```|~~~)")
HEADING = re.compile(r"^\s{0,3}(#{1,6}\s+\S|\*\*[^*]+\*\*:?\s*$|__[^_]+__:?\s*$)")
STRUCTURAL = re.compile(
    r"^\s*("
    r"#{1,6}\s+\S"                      # heading
    r"|(\*\*[^*]+\*\*|__[^_]+__):?$"     # a line that is only bold: a heading too
    r"|\|.*\|\s*$"                      # table row
    r"|([-*_]\s*){3,}$"                 # horizontal rule
    r"|!?\[[^\]]*\]\([^)]*\)\s*$"       # image or link alone on a line
    r"|<[^>]+>.*"                       # HTML
    r"|\[[^\]]+\]:\s*\S+"               # link definition
    r"|\$\$.*"                          # display math
    r")"
)
# Split after a sentence end, keeping any closing quote or bracket with its sentence.
SENTENCE_END = re.compile(
    r"(?<=[.!?])\s+|(?<=[.!?][\"'”’)])\s+"
    r"|(?<=[。！？])(?![”’」』）])|(?<=[。！？][”’」』）])"
)


@dataclass
class Segment:
    kind: str          # "prose": rewritten by the model; "keep": copied as is
    text: str
    joiner: str = ""   # placed before this segment when the document is put back together


def weight(text: str) -> float:
    """1.0 is a full piece: MAX_WORDS English words or MAX_CJK Chinese characters."""
    return len(LATIN_WORD.findall(text)) / MAX_WORDS + len(CJK.findall(text)) / MAX_CJK


def _blocks(text: str) -> list[tuple[str, str, str]]:
    """(kind, text, joiner) blocks, split at blank lines; fenced code stays whole."""
    blocks, current, fence = [], [], None
    gap = "\n\n"

    def flush():
        nonlocal current, gap
        if current:
            body = "\n".join(current)
            if all(STRUCTURAL.match(line) for line in current):
                blocks.append(("keep", body, gap))
            elif HEADING.match(current[0]) and len(current) > 1:
                # A heading directly followed by its paragraph.
                blocks.append(("keep", current[0], gap))
                blocks.append(("prose", "\n".join(current[1:]), "\n"))
            else:
                blocks.append(("prose", body, gap))
            current, gap = [], "\n\n"

    for line in text.split("\n"):
        if fence:
            current.append(line)
            if line.strip().startswith(fence):
                blocks.append(("keep", "\n".join(current), gap))
                current, gap, fence = [], "\n\n", None
            continue
        match = FENCE.match(line)
        if match:
            flush()
            fence, current = match.group(1), [line]
            continue
        if line.strip():
            current.append(line.rstrip())
        else:
            flush()
    if fence:  # unclosed fence: keep the rest as is
        blocks.append(("keep", "\n".join(current), gap))
    else:
        flush()
    return blocks


def _group(items: list[str], joiner: str) -> list[str]:
    """Join items in order into pieces of weight <= 1, about the same size."""
    total = sum(weight(i) for i in items)
    target = total / max(1, math.ceil(total))
    limit = min(1.0, target * 1.2)
    pieces, current, current_w = [], [], 0.0
    for item in items:
        w = weight(item)
        if current and current_w + w > limit:
            pieces.append(joiner.join(current))
            current, current_w = [], 0.0
        current.append(item)
        current_w += w
    if current:
        pieces.append(joiner.join(current))
    return pieces


def _is_cjk(text: str) -> bool:
    return len(CJK.findall(text)) > len(LATIN_WORD.findall(text))


def _sentence_joiner(text: str) -> str:
    return "" if _is_cjk(text) else " "


def _split_paragraph(paragraph: str) -> list[str]:
    sentences = [s.strip() for s in SENTENCE_END.split(paragraph) if s and s.strip()]
    return _group(sentences, _sentence_joiner(paragraph))


def split(text: str) -> list[Segment]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    segments: list[Segment] = []
    stretch: list[tuple[str, str]] = []   # consecutive prose blocks: (text, joiner)

    def flush_stretch():
        if not stretch:
            return
        first_joiner = stretch[0][1]
        paragraphs = [t for t, _ in stretch]
        groups: list[list[str]] = []
        current: list[str] = []
        # Paragraphs longer than one piece are cut at sentence ends and rejoined as one paragraph.
        for p in paragraphs:
            if weight(p) > 1.0:
                if current:
                    groups.append(current)
                    current = []
                groups.append([p])
            else:
                current.append(p)
        if current:
            groups.append(current)
        joiner = first_joiner
        for group in groups:
            if len(group) == 1 and weight(group[0]) > 1.0:
                inner = _sentence_joiner(group[0])
                for k, part in enumerate(_split_paragraph(group[0])):
                    segments.append(Segment("prose", part, joiner if k == 0 else inner))
            else:
                for k, piece in enumerate(_group(group, "\n\n")):
                    segments.append(Segment("prose", piece, joiner if k == 0 else "\n\n"))
            joiner = "\n\n"
        stretch.clear()

    for kind, body, joiner in _blocks(text):
        if kind == "prose":
            stretch.append((body, joiner))
        else:
            flush_stretch()
            segments.append(Segment("keep", body, joiner))
    flush_stretch()
    if segments:
        segments[0].joiner = ""
    return segments


def join(segments: list[Segment], outputs: list[str]) -> str:
    return "".join(seg.joiner + out for seg, out in zip(segments, outputs))
