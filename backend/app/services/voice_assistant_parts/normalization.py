# ruff: noqa: F403,F405
from .shared import *

def normalize_text(value: str) -> str:
    return " ".join(value.split())


def normalize_for_search(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.casefold().replace("’", "'").replace("`", "'")
    return normalize_text(normalized)


def tokenize(value: str) -> tuple[str, ...]:
    return tuple(
        token.casefold()
        for token in TOKEN_RE.findall(normalize_for_search(value))
        if token.casefold() not in STOP_WORDS
    )


def stem_token(token: str) -> str:
    if len(token) < 6:
        return token
    for suffix in UKRAINIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 5:
            return token[: -len(suffix)]
    return token
