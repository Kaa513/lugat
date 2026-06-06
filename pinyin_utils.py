"""Convert numbered pinyin (shou3 ji1) to tone-marked pinyin (shǒu jī)."""

from __future__ import annotations

import re

# Tone marks for vowels; index 0–3 = tones 1–4, index 4 = neutral (5)
_TONE_MARKS: dict[str, tuple[str, str, str, str, str]] = {
    "a": ("ā", "á", "ǎ", "à", "a"),
    "e": ("ē", "é", "ě", "è", "e"),
    "i": ("ī", "í", "ǐ", "ì", "i"),
    "o": ("ō", "ó", "ǒ", "ò", "o"),
    "u": ("ū", "ú", "ǔ", "ù", "u"),
    "ü": ("ǖ", "ǖ", "ǚ", "ǜ", "ü"),
}

# Syllable + tone digit (CC-CEDICT style)
_SYLLABLE_RE = re.compile(
    r"([bpmfdtnlgkhjqxzrcsyw]*[aeiouüv]+[a-z]*)([1-5])",
    re.IGNORECASE,
)


def _tone_vowel_index(syllable: str) -> int:
    """Return index of the vowel that receives the tone mark."""
    s = syllable.lower().replace("v", "ü")
    if "a" in s:
        return s.index("a")
    if "e" in s:
        return s.index("e")
    if "ou" in s:
        return s.index("o")
    for i in range(len(s) - 1, -1, -1):
        if s[i] in "iouü":
            return i
    return -1


def _convert_syllable(syllable: str, tone: int) -> str:
    """Convert one syllable such as shou3 -> shǒu."""
    if tone == 5:
        return syllable.lower().replace("v", "ü")

    idx = _tone_vowel_index(syllable)
    if idx < 0:
        return syllable

    chars = list(syllable.lower().replace("v", "ü"))
    vowel = chars[idx]
    if vowel not in _TONE_MARKS:
        return "".join(chars)

    chars[idx] = _TONE_MARKS[vowel][tone - 1]
    return "".join(chars)


def convert_pinyin(text: str) -> str:
    """
    Convert numbered pinyin to tone-marked pinyin.

    Example: "shou3 ji1" -> "shǒu jī"
    Syllables that already lack tone digits are left unchanged.
    """
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        return _convert_syllable(match.group(1), int(match.group(2)))

    return _SYLLABLE_RE.sub(_replace, text)
