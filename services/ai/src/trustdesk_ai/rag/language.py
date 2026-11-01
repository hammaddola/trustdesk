"""Language detection for English, Urdu (Arabic script) and Roman Urdu.

Codes: "en", "ur" (Urdu script), "ur-Latn" (Roman Urdu). Other languages pass through as ISO codes.
Short texts are unreliable for statistical detectors, so script and keyword rules run first.
"""

from __future__ import annotations

import re

from langdetect import DetectorFactory, LangDetectException, detect

DetectorFactory.seed = 0  # langdetect is otherwise nondeterministic

_ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_URDU_ONLY = re.compile(r"[ٹڈڑںےۓہھ۔]")  # letters/punctuation used in Urdu but not standard Arabic
_LATIN = re.compile(r"[A-Za-z]")
_ROMAN_URDU = frozenset(
    """hai hain ka ki ke ko se mein main aap kya kia kyun kaise kitna kitne kitni nahi nahin hum tum
    yeh ye woh wo kab kahan kaun apna apni apke aapka aapki batao bataen bataiye chahiye karte karta
    karti kar sakte sakta hota hoti tha thi raha rahi wala wali liye lekin magar acha accha shukriya""".split()
)

RTL_LANGUAGES = frozenset({"ur", "ar", "fa", "he"})


def detect_language(text: str, default: str = "en") -> str:
    sample = text.strip()
    if not sample:
        return default
    arabic = len(_ARABIC_SCRIPT.findall(sample))
    latin = len(_LATIN.findall(sample))
    if arabic and arabic >= latin:
        return "ur" if _URDU_ONLY.search(sample) else _detect(sample, default_if_unsure="ur")
    tokens = re.findall(r"[a-z]+", sample.lower())
    roman_hits = sum(1 for t in tokens if t in _ROMAN_URDU)
    if tokens and (roman_hits >= 2 or (roman_hits == 1 and len(tokens) <= 3)):
        return "ur-Latn"
    if len(tokens) < 3:
        return default
    return _detect(sample, default_if_unsure=default)


def _detect(text: str, default_if_unsure: str) -> str:
    try:
        return str(detect(text))
    except LangDetectException:
        return default_if_unsure


def text_direction(language: str) -> str:
    return "rtl" if language.split("-")[0] in RTL_LANGUAGES and not language.endswith("-Latn") else "ltr"


def tsv_config_for(language: str | None) -> str:
    """Postgres text-search config: English stemming for en; 'simple' for everything else (no Urdu stemmer)."""
    return "english" if language == "en" else "simple"
