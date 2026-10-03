"""Sentence splitting and English TTS normalisation (numbers, symbols, abbreviations)."""

from __future__ import annotations

import re

_ABBREV = ["Mr", "Mrs", "Ms", "Dr", "St", "Prof", "No", "Sr", "Jr", "vs", "etc", "e.g", "i.e", "approx", "Mt"]
_ABBR_RE = re.compile(r"\b(" + "|".join(re.escape(a) for a in _ABBREV) + r")\.", re.IGNORECASE)
_SPLIT_RE = re.compile(r"(?<=[.!?…])[\"'”’)]?\s+(?=[\"'“‘(]?[A-Z0-9])")


def split_sentences(text: str, max_chars: int = 240) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    protected = _ABBR_RE.sub(lambda m: m.group(1) + "<DOT>", text)
    parts = [p.replace("<DOT>", ".").strip() for p in _SPLIT_RE.split(protected) if p.strip()]
    out: list[str] = []
    for p in parts:   # keep TTS chunks short: long sentences drift
        while len(p) > max_chars:
            cut = max(p.rfind("; ", 0, max_chars), p.rfind(", ", 0, max_chars), p.rfind(" - ", 0, max_chars))
            if cut < max_chars // 3:
                cut = p.rfind(" ", 0, max_chars)
            if cut <= 0:
                break
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            out.append(p)
    return out


def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’-]+", text or ""))

# ----------------------------------------------------------------------- numbers -> words
_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen " \
        "fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _under_1000(n: int) -> str:
    words = []
    if n >= 100:
        words.append(_ONES[n // 100] + " hundred")
        n %= 100
        if n:
            words.append("and")
    if n >= 20:
        words.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n or not words:
        words.append(_ONES[n])
    return " ".join(words)


def number_to_words(n: int) -> str:
    if n < 0:
        return "minus " + number_to_words(-n)
    if n < 1000:
        return _under_1000(n)
    parts = []
    for value, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= value:
            parts.append(number_to_words(n // value) + " " + name)
            n %= value
    if n:
        parts.append(("and " if n < 100 else "") + _under_1000(n))
    return " ".join(parts)


def year_to_words(y: int) -> str:
    if 2000 <= y <= 2009:
        return number_to_words(y)
    hi, lo = divmod(y, 100)
    if lo == 0:
        return number_to_words(hi) + " hundred"
    return number_to_words(hi) + " " + ("oh-" + _ONES[lo] if lo < 10 else number_to_words(lo))


_ORD = {"1": "first", "2": "second", "3": "third", "5": "fifth", "8": "eighth", "9": "ninth", "12": "twelfth"}


def _ordinal(n: int) -> str:
    w = number_to_words(n)
    if str(n) in _ORD:
        return _ORD[str(n)]
    last = w.split(" ")[-1].split("-")[-1]
    repl = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth",
            "nine": "ninth", "twelve": "twelfth"}.get(last)
    if repl:
        return w[: len(w) - len(last)] + repl
    if w.endswith("y"):
        return w[:-1] + "ieth"
    return w + "th"


def _plural(words: str) -> str:
    return words[:-1] + "ies" if words.endswith("y") else words + "s"


def normalize_for_tts(text: str) -> str:
    t = text
    t = re.sub(r"\be\.g\.", "for example", t, flags=re.I)
    t = re.sub(r"\bi\.e\.", "that is", t, flags=re.I)
    t = re.sub(r"\betc\.", "et cetera", t, flags=re.I)
    t = re.sub(r"\bMr\.", "Mister", t)
    t = re.sub(r"\bMrs\.", "Missus", t)
    t = re.sub(r"\bDr\.", "Doctor", t)
    t = re.sub(r"\bNo\.\s?(\d)", r"number \1", t)
    t = t.replace("&", " and ").replace("%", " per cent").replace("+", " plus ")
    t = re.sub(r"£\s?(\d[\d,]*)", lambda m: m.group(1) + " pounds", t)
    t = re.sub(r"\$\s?(\d[\d,]*)", lambda m: m.group(1) + " dollars", t)
    t = re.sub(r"€\s?(\d[\d,]*)", lambda m: m.group(1) + " euros", t)
    t = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: _ordinal(int(m.group(1))), t)
    t = re.sub(r"\b(1[1-9]\d\d|20\d\d)s\b", lambda m: _plural(year_to_words(int(m.group(1)))), t)
    t = re.sub(r"\b(1[1-9]\d\d|20\d\d)\b", lambda m: year_to_words(int(m.group(1))), t)
    t = re.sub(r"\b(\d+)\.(\d+)\b", lambda m: number_to_words(int(m.group(1))) + " point " +
               " ".join(_ONES[int(d)] for d in m.group(2)), t)
    t = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", lambda m: number_to_words(int(m.group(0).replace(",", ""))), t)
    t = re.sub(r"\b\d+\b", lambda m: number_to_words(int(m.group(0))), t)
    t = t.replace("—", ", ").replace("–", ", ").replace("…", "...")
    t = re.sub(r"\s+", " ", t).strip()
    return t
