from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import logging
import re

try:
    import jieba  # type: ignore
    _HAS_JIEBA = True
except Exception:  # pragma: no cover - optional dep
    jieba = None
    _HAS_JIEBA = False


SENT_END = set("。！？!?；;‽")
PUNCT_CHARS = set("，。！？；：、（）《》“”‘’—…·,.;:!?()[]\"'—…")


def split_sentences(text: str) -> List[str]:
    parts: List[str] = []
    buf: List[str] = []
    for ch in text.strip():
        buf.append(ch)
        if ch in SENT_END:
            parts.append("".join(buf).strip())
            buf = []
    if buf:
        tail = "".join(buf).strip()
        if tail:
            parts.append(tail)
    return parts


def _is_ascii_letter_or_digit(ch: str) -> bool:
    return ("0" <= ch <= "9") or ("A" <= ch <= "Z") or ("a" <= ch <= "z")


def tokenize(text: str) -> List[Tuple[str, str]]:
    """Tokenize text into (token, kind) using jieba when available.
    kind in {word, punct, latin, space, number}
    """
    if _HAS_JIEBA:
        raw_tokens = list(jieba.lcut(text))  # includes punctuation like '。'
    else:
        # Very naive fallback: character-based with ASCII grouping
        raw_tokens = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch.isspace():
                j = i + 1
                while j < n and text[j].isspace():
                    j += 1
                raw_tokens.append(text[i:j])
                i = j
                continue
            if _is_ascii_letter_or_digit(ch):
                j = i + 1
                while j < n and _is_ascii_letter_or_digit(text[j]):
                    j += 1
                raw_tokens.append(text[i:j])
                i = j
                continue
            raw_tokens.append(ch)
            i += 1

    tokens: List[Tuple[str, str]] = []
    for t in raw_tokens:
        if not t:
            continue
        if t.isspace():
            kind = "space"
        elif t in PUNCT_CHARS:
            kind = "punct"
        elif t.isdigit():
            kind = "number"
        elif all(_is_ascii_letter_or_digit(c) for c in t):
            kind = "latin"
        else:
            kind = "word"
        tokens.append((t, kind))
    return tokens


def translate_text(text: str, source_lang: str = "zh", target_lang: str = "en") -> Optional[str]:
    """Translate text using deep_translator.GoogleTranslator when available.

    Returns translated text on success, or None if translation isn't available
    (missing dependency, network error, unsupported language, etc.).
    """
    try:  # Lazy import so project can run without the optional dep
        from deep_translator import GoogleTranslator  # type: ignore
    except Exception:
        return None

    # Normalize common language tags for GoogleTranslator
    def _norm(lang: str) -> str:
        l = (lang or "").strip().lower()
        if l in {"zh", "zh-cn", "zh_hans", "chinese", "chinese (simplified)"}:
            return "zh-CN"
        if l in {"zh-tw", "zh_hant", "chinese (traditional)"}:
            return "zh-TW"
        return lang

    src = _norm(source_lang)
    tgt = _norm(target_lang)

    try:
        return GoogleTranslator(source=src or "auto", target=tgt or "en").translate(text)
    except Exception as exc:  # Network errors, rate limits, etc.
        logging.getLogger(__name__).warning("Translation failed: %s", exc)
        return None


def _parse_srt_timestamp(ts: str) -> int:
    """Convert an SRT timestamp (HH:MM:SS,mmm) to milliseconds."""
    ts = ts.strip()
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2}),(\d{3})$", ts)
    if not m:
        raise ValueError(f"Invalid SRT timestamp: {ts}")
    hh, mm, ss, ms = map(int, m.groups())
    return ((hh * 60 + mm) * 60 + ss) * 1000 + ms


def parse_srt(text: str) -> List[Tuple[int, int, str]]:
    """Parse SRT content into a list of (start_ms, end_ms, text).

    - Supports standard SRT blocks separated by blank lines.
    - Joins multi-line cue text with a single space.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues: List[Tuple[int, int, str]] = []
    i = 0
    n = len(lines)
    while i < n:
        # Skip leading blanks
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break
        # Optional index line
        if re.match(r"^\d+$", lines[i].strip()):
            i += 1
            if i >= n:
                break
        # Timestamp line
        if i < n and "-->" in lines[i]:
            ts_line = lines[i].strip()
            i += 1
        else:
            # Malformed block; skip to next blank
            while i < n and lines[i].strip():
                i += 1
            continue
        try:
            start_str, end_str = [p.strip() for p in ts_line.split("-->")]
            start_ms = _parse_srt_timestamp(start_str)
            end_ms = _parse_srt_timestamp(end_str)
        except Exception:
            # Skip malformed timestamps
            while i < n and lines[i].strip():
                i += 1
            continue
        # Collect text lines until blank
        text_lines: List[str] = []
        while i < n and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        cue_text = " ".join(text_lines).strip()
        if cue_text:
            cues.append((start_ms, end_ms, cue_text))
        # Skip the blank separator
        while i < n and not lines[i].strip():
            i += 1
    return cues
