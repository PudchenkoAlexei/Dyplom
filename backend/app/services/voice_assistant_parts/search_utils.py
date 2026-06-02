# ruff: noqa: F403,F405
from .shared import *
from .models import KnowledgeBaseEntry
from .normalization import normalize_for_search, normalize_text, stem_token
from .direct_facts import _protect_sentence_abbreviations, _restore_sentence_abbreviations

def char_ngrams(value: str, *, size: int = 4) -> set[str]:
    compact = f" {NON_TOKEN_RE.sub(' ', normalize_for_search(value))} "
    return {compact[index : index + size] for index in range(max(0, len(compact) - size + 1))}


def field_tokens(entry: KnowledgeBaseEntry) -> dict[str, str]:
    return {
        "title": entry.title,
        "question": entry.question,
        "tags": " ".join(entry.tags),
        "answer": entry.answer,
    }


def search_stem_matches(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if right in SEARCH_SYNONYM_STEMS.get(left, ()) or left in SEARCH_SYNONYM_STEMS.get(right, ()):
        return 0.82
    if len(left) >= 5 and len(right) >= 5:
        shorter, longer = sorted((left, right), key=len)
        ratio = len(shorter) / len(longer)
        if shorter in longer and ratio >= 0.64:
            return 0.82
        common_prefix = 0
        for left_char, right_char in zip(left, right):
            if left_char != right_char:
                break
            common_prefix += 1
        if common_prefix >= 5 and common_prefix / min(len(left), len(right)) >= 0.78:
            return 0.72
    return 0.0


def token_match_quality(query_token: str, query_stem: str, field_tokens: set[str], field_stems: set[str]) -> float:
    if query_token in field_tokens or query_stem in field_stems:
        return 1.0
    for field_stem in field_stems:
        quality = search_stem_matches(query_stem, field_stem)
        if quality:
            return quality
    return 0.0


def ngram_similarity(query_ngrams: set[str], document_ngrams: set[str]) -> float:
    if not query_ngrams or not document_ngrams:
        return 0.0
    return len(query_ngrams & document_ngrams) / len(query_ngrams)


def phrase_match_score(query_stems: tuple[str, ...], document_tokens: tuple[str, ...]) -> float:
    if len(query_stems) < 2:
        return 0.0
    document_stems = tuple(stem_token(token) for token in document_tokens)
    query_pairs = list(zip(query_stems, query_stems[1:]))
    if not query_pairs:
        return 0.0

    matched_pairs = 0
    for left, right in query_pairs:
        for index in range(len(document_stems) - 1):
            if document_stems[index] == left and document_stems[index + 1] == right:
                matched_pairs += 1
                break
    return matched_pairs / len(query_pairs)


def compound_form_matches(left: str, right: str) -> bool:
    if len(left) < 8 or len(right) < 8:
        return False
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    if longer.startswith(shorter) and len(shorter) / len(longer) >= 0.82:
        return True
    return shorter in longer and len(shorter) / len(longer) >= 0.88


def compound_phrase_score(query_stems: tuple[str, ...], document_tokens: tuple[str, ...]) -> float:
    if len(query_stems) < 2:
        return 0.0

    document_forms = set(document_tokens) | {stem_token(token) for token in document_tokens}
    matched_query_indexes: set[int] = set()

    for window_size in (3, 2):
        if len(query_stems) < window_size:
            continue
        for start in range(len(query_stems) - window_size + 1):
            indexes = set(range(start, start + window_size))
            if indexes & matched_query_indexes:
                continue
            compound = "".join(query_stems[start : start + window_size])
            if any(compound_form_matches(compound, document_form) for document_form in document_forms):
                matched_query_indexes.update(indexes)

    return len(matched_query_indexes) / len(query_stems)


def build_compound_aliases(
    tokens: tuple[str, ...],
    *,
    min_window_size: int = 1,
    max_window_size: int = 4,
) -> set[str]:
    aliases: set[str] = set()
    if not tokens:
        return aliases

    stems = tuple(stem_token(token) for token in tokens)
    for window_size in range(min_window_size, min(max_window_size, len(tokens)) + 1):
        for start in range(len(tokens) - window_size + 1):
            raw_alias = "".join(tokens[start : start + window_size])
            stem_alias = "".join(stems[start : start + window_size])
            for alias in (raw_alias, stem_alias):
                if len(alias) >= 8:
                    aliases.add(alias)
    return aliases


def alias_form_match_score(left: str, right: str) -> float:
    if left == right:
        return 1.0
    if len(left) < 8 or len(right) < 8:
        return 0.0

    shorter, longer = sorted((left, right), key=len)
    ratio = len(shorter) / len(longer)
    if ratio < 0.82:
        return 0.0
    if longer.startswith(shorter):
        return 0.92
    if shorter in longer and ratio >= 0.9:
        return 0.86
    return 0.0


def alias_match_score(query_aliases: set[str], document_aliases: set[str]) -> float:
    if not query_aliases or not document_aliases:
        return 0.0

    best_score = 0.0
    for query_alias in query_aliases:
        for document_alias in document_aliases:
            best_score = max(
                best_score,
                alias_form_match_score(query_alias, document_alias),
            )
            if best_score >= 1.0:
                return 1.0
    return best_score


def dedupe_repeated_sentences(text: str) -> str:
    protected_text = _protect_sentence_abbreviations(text)
    parts = re.split(r"(?<=[.!?…])\s+", protected_text)
    deduped: list[str] = []
    seen: set[str] = set()

    for part in parts:
        sentence = _restore_sentence_abbreviations(part.strip())
        if not sentence:
            continue
        key = normalize_for_search(sentence)
        if key in seen:
            continue
        deduped.append(sentence)
        seen.add(key)

    return normalize_text(" ".join(deduped))
