"""Text normalisation and measurement helpers used by the rule-based checks."""

import re

_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+")
_MARKUP = re.compile(r"[*_`#>|]")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
_RAW_SENTENCE_END = re.compile(r"[.!?][\"')\]*_]*\s+")
_INLINE_QUOTE = re.compile(r"(?<=[.!?:])[ \t]+>[ \t]+")
_QUOTE_OPEN = re.compile(r"(?:^|(?<=\s))['\"]")
_QUOTE_CLOSE = re.compile(r"['\"](?=$|\s)")
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def strip_markup(line: str) -> str:
    return _MARKUP.sub("", _LIST_MARKER.sub("", line)).strip()


def sentences(text: str) -> list[str]:
    """Split on sentence punctuation, treating every line as its own boundary."""
    result: list[str] = []
    for line in text.splitlines():
        clean = strip_markup(line)
        if clean:
            result += [part.strip() for part in _SENTENCE_END.split(clean) if part.strip()]
    return result


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def prose(text: str) -> str:
    """Markdown-free text in which every sentence ends with punctuation."""
    terminated = (s if s[-1] in ".!?" else f"{s}." for s in sentences(text))
    return " ".join(terminated)


def paragraphs(text: str) -> list[str]:
    """Prose blocks only. Lists are excluded because each item stands alone."""
    blocks = (block.strip() for block in re.split(r"\n\s*\n", text))
    return [b for b in blocks if b and not _LIST_MARKER.match(b) and not b.startswith(">")]


def split_long_paragraphs(body: str, max_sentences: int) -> tuple[str, int]:
    """Adds paragraph breaks without changing any words. Returns the text and the split count."""
    result: list[str] = []
    splits = 0
    body = _INLINE_QUOTE.sub("\n\n> ", body)
    for block in re.split(r"\n\s*\n", body):
        lines = block.strip().splitlines()
        is_special = any(_LIST_MARKER.match(ln) or ln.lstrip().startswith(">") for ln in lines)
        if is_special or len(sentences(block)) <= max_sentences:
            result.append(block.strip())
            continue
        current: list[str] = []
        in_quote = False
        for part in _raw_sentences(" ".join(ln.strip() for ln in lines)):
            current.append(part)
            in_quote ^= _toggles_quote(part)
            if len(current) >= max_sentences and not in_quote:
                result.append(" ".join(current))
                current = []
        if current:
            result.append(" ".join(current))
        splits += 1
    return "\n\n".join(result), splits


def _toggles_quote(sentence: str) -> bool:
    opens = len(_QUOTE_OPEN.findall(sentence))
    closes = len(_QUOTE_CLOSE.findall(sentence))
    return (opens + closes) % 2 == 1


def _raw_sentences(line: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for match in _RAW_SENTENCE_END.finditer(line):
        parts.append(line[start : match.end()].strip())
        start = match.end()
    if line[start:].strip():
        parts.append(line[start:].strip())
    return parts


def contains_term(text: str, term: str) -> bool:
    pattern = rf"\b{re.escape(term)}(?:s|es)?\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


def normalise_for_match(text: str) -> str:
    """Canonical form for checking that a quote really appears in a lesson."""
    cleaned = strip_markup(text.replace("\n", " "))
    cleaned = cleaned.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", _MARKUP.sub("", cleaned)).strip().lower()
