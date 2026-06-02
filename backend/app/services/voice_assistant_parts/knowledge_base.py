# ruff: noqa: F403,F405
from .shared import *
from .models import DirectFactIntent, EntrySearchIndex, KnowledgeBaseEntry, KnowledgeMatch
from .normalization import stem_token, tokenize
from .direct_facts import (
    detect_direct_fact_intent,
    direct_fact_object_terms,
    focus_direct_fact_chunks,
    uses_direct_fact_field_reranking,
)
from .search_utils import (
    alias_match_score,
    build_compound_aliases,
    char_ngrams,
    compound_phrase_score,
    field_tokens,
    ngram_similarity,
    phrase_match_score,
    token_match_quality,
)
class KnowledgeBaseService:
    def __init__(self, path: Path = KNOWLEDGE_BASE_PATH) -> None:
        raw_entries = json.loads(path.read_text(encoding="utf-8"))
        self.entries = [KnowledgeBaseEntry.from_dict(item) for item in raw_entries]
        self._index = [self._build_index(entry) for entry in self.entries]
        self._index_by_entry_id = {item.entry.id: item for item in self._index}
        self._idf = self._build_idf(self._index)

    @classmethod
    def from_entries(cls, entries: list[KnowledgeBaseEntry]) -> "KnowledgeBaseService":
        service = cls.__new__(cls)
        service.entries = entries
        service._index = [service._build_index(entry) for entry in entries]
        service._index_by_entry_id = {item.entry.id: item for item in service._index}
        service._idf = service._build_idf(service._index)
        return service

    @staticmethod
    def _build_index(entry: KnowledgeBaseEntry) -> EntrySearchIndex:
        fields = field_tokens(entry)
        tokens = {field: tokenize(value) for field, value in fields.items()}
        primary_aliases: set[str] = set()
        for field in ("title", "question", "tags"):
            primary_aliases.update(build_compound_aliases(tokens[field]))
        return EntrySearchIndex(
            entry=entry,
            tokens=tokens,
            stems={field: {stem_token(token) for token in values} for field, values in tokens.items()},
            ngrams={field: char_ngrams(value) for field, value in fields.items()},
            primary_aliases=primary_aliases,
        )

    @staticmethod
    def _build_idf(index: list[EntrySearchIndex]) -> dict[str, float]:
        document_frequency: Counter[str] = Counter()
        for item in index:
            document_stems = set().union(*(item.stems[field] for field in SEARCH_FIELDS))
            document_frequency.update(document_stems)

        document_count = len(index)
        return {
            stem: math.log((document_count + 1) / (count + 0.5)) + 1
            for stem, count in document_frequency.items()
        }

    def search(self, question: str, *, limit: int | None = None) -> list[KnowledgeMatch]:
        query_tokens = tokenize(question)
        if not query_tokens:
            return []

        matches = []
        query_stems = tuple(stem_token(token) for token in query_tokens)
        query_ngrams = char_ngrams(question)
        query_aliases = build_compound_aliases(query_tokens, min_window_size=2)
        direct_fact_intent = detect_direct_fact_intent(question)
        object_tokens, object_stems = direct_fact_object_terms(
            query_tokens,
            query_stems,
            direct_fact_intent,
        )
        for item in self._index:
            score = self._score_entry(
                query_tokens,
                query_stems,
                query_ngrams,
                query_aliases,
                item,
                direct_fact_intent=direct_fact_intent,
                object_tokens=object_tokens,
                object_stems=object_stems,
            )
            if score > 0:
                matches.append(KnowledgeMatch(entry=item.entry, score=round(score, 4)))

        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[: limit or settings.voice_assistant_max_context_items]

    def score_entry_for_question(self, question: str, entry: KnowledgeBaseEntry) -> float:
        query_tokens = tokenize(question)
        if not query_tokens:
            return 0.0
        item = self._index_by_entry_id.get(entry.id)
        if item is None:
            return 0.0
        query_stems = tuple(stem_token(token) for token in query_tokens)
        query_ngrams = char_ngrams(question)
        query_aliases = build_compound_aliases(query_tokens, min_window_size=2)
        direct_fact_intent = detect_direct_fact_intent(question)
        object_tokens, object_stems = direct_fact_object_terms(
            query_tokens,
            query_stems,
            direct_fact_intent,
        )
        return round(
            self._score_entry(
                query_tokens,
                query_stems,
                query_ngrams,
                query_aliases,
                item,
                direct_fact_intent=direct_fact_intent,
                object_tokens=object_tokens,
                object_stems=object_stems,
            ),
            4,
        )

    def _coverage(
        self,
        query_tokens: tuple[str, ...],
        query_stems: tuple[str, ...],
        document_tokens: set[str],
        document_stems: set[str],
    ) -> float:
        denominator = sum(self._idf.get(stem, 2.0) for stem in query_stems)
        if denominator <= 0:
            return 0.0

        score = 0.0
        for token, stem in zip(query_tokens, query_stems):
            score += self._idf.get(stem, 2.0) * token_match_quality(
                token,
                stem,
                document_tokens,
                document_stems,
            )
        return score / denominator

    def _significant_coverage(
        self,
        query_tokens: tuple[str, ...],
        query_stems: tuple[str, ...],
        document_tokens: set[str],
        document_stems: set[str],
    ) -> tuple[float, int]:
        significant_pairs = [
            (token, stem)
            for token, stem in zip(query_tokens, query_stems)
            if len(stem) >= 5 and stem not in LOW_VALUE_SEARCH_STEMS
        ]
        if not significant_pairs:
            return 1.0, 0

        filtered_tokens = tuple(token for token, _ in significant_pairs)
        filtered_stems = tuple(stem for _, stem in significant_pairs)
        return (
            self._coverage(filtered_tokens, filtered_stems, document_tokens, document_stems),
            len(significant_pairs),
        )

    def _score_entry(
        self,
        query_tokens: tuple[str, ...],
        query_stems: tuple[str, ...],
        query_ngrams: set[str],
        query_aliases: set[str],
        item: EntrySearchIndex,
        *,
        direct_fact_intent: DirectFactIntent | None = None,
        object_tokens: tuple[str, ...] = (),
        object_stems: tuple[str, ...] = (),
    ) -> float:
        primary_tokens = set(item.tokens["title"]) | set(item.tokens["question"]) | set(item.tokens["tags"])
        primary_stems = item.stems["title"] | item.stems["question"] | item.stems["tags"]
        full_tokens = primary_tokens | set(item.tokens["answer"])
        full_stems = primary_stems | item.stems["answer"]

        title_coverage = self._coverage(query_tokens, query_stems, set(item.tokens["title"]), item.stems["title"])
        question_coverage = self._coverage(
            query_tokens,
            query_stems,
            set(item.tokens["question"]),
            item.stems["question"],
        )
        tag_coverage = self._coverage(query_tokens, query_stems, set(item.tokens["tags"]), item.stems["tags"])
        primary_coverage = self._coverage(query_tokens, query_stems, primary_tokens, primary_stems)
        answer_coverage = self._coverage(
            query_tokens,
            query_stems,
            set(item.tokens["answer"]),
            item.stems["answer"],
        )
        full_coverage = self._coverage(query_tokens, query_stems, full_tokens, full_stems)
        significant_coverage, significant_count = self._significant_coverage(
            query_tokens,
            query_stems,
            full_tokens,
            full_stems,
        )

        primary_ngram_score = max(
            ngram_similarity(query_ngrams, item.ngrams["title"]),
            ngram_similarity(query_ngrams, item.ngrams["question"]),
            ngram_similarity(query_ngrams, item.ngrams["tags"]),
        )
        answer_ngram_score = ngram_similarity(query_ngrams, item.ngrams["answer"])
        primary_phrase_score = max(
            phrase_match_score(query_stems, item.tokens["title"]),
            phrase_match_score(query_stems, item.tokens["question"]),
            phrase_match_score(query_stems, item.tokens["tags"]),
        )
        answer_phrase_score = phrase_match_score(query_stems, item.tokens["answer"])
        primary_compound_score = max(
            compound_phrase_score(query_stems, item.tokens["title"]),
            compound_phrase_score(query_stems, item.tokens["question"]),
            compound_phrase_score(query_stems, item.tokens["tags"]),
        )
        answer_compound_score = compound_phrase_score(query_stems, item.tokens["answer"])
        primary_alias_score = alias_match_score(query_aliases, item.primary_aliases)
        info_source_score = (
            1.0
            if set(query_stems) & INFO_SEEKING_QUERY_STEMS and primary_stems & INFO_SOURCE_STEMS
            else 0.0
        )

        field_score = max(
            title_coverage,
            question_coverage * 0.95,
            tag_coverage * 0.9,
            primary_coverage * 0.86,
            primary_compound_score * 0.92,
            primary_alias_score * 0.95,
        )
        score = (
            field_score * 0.55
            + full_coverage * 0.2
            + primary_ngram_score * 0.08
            + answer_ngram_score * 0.04
            + primary_phrase_score * 0.08
            + answer_phrase_score * 0.3
            + primary_compound_score * 0.28
            + answer_compound_score * 0.08
            + primary_alias_score * 0.32
            + info_source_score * 0.14
        )

        if (
            primary_coverage < 0.34
            and primary_compound_score == 0
            and primary_alias_score == 0
            and answer_coverage > 0
            and answer_phrase_score == 0
        ):
            score *= 0.68
        if (
            len(query_tokens) <= 2
            and primary_coverage < 0.75
            and primary_compound_score == 0
            and primary_alias_score == 0
            and answer_phrase_score == 0
        ):
            score *= 0.82
        if significant_count >= 2:
            if significant_coverage < 0.34:
                score *= 0.38
            elif significant_coverage < 0.5:
                score *= 0.62
        elif significant_count == 1 and significant_coverage == 0:
            score *= 0.55

        if direct_fact_intent is not None and uses_direct_fact_field_reranking(direct_fact_intent):
            requested_fact_chunks = focus_direct_fact_chunks(item.entry.answer, direct_fact_intent)
            has_requested_fact = bool(requested_fact_chunks)

            object_match = 1.0
            object_phrase_score = 0.0
            object_alias_score = 0.0
            if object_tokens:
                object_coverage = self._coverage(
                    object_tokens,
                    object_stems,
                    primary_tokens,
                    primary_stems,
                )
                object_phrase_score = max(
                    phrase_match_score(object_stems, item.tokens["title"]),
                    phrase_match_score(object_stems, item.tokens["question"]),
                    phrase_match_score(object_stems, item.tokens["tags"]),
                )
                object_compound_score = max(
                    compound_phrase_score(object_stems, item.tokens["title"]),
                    compound_phrase_score(object_stems, item.tokens["question"]),
                    compound_phrase_score(object_stems, item.tokens["tags"]),
                )
                object_alias_score = alias_match_score(
                    build_compound_aliases(object_tokens, min_window_size=2),
                    item.primary_aliases,
                )
                object_match = max(
                    object_coverage,
                    object_phrase_score,
                    object_compound_score,
                    object_alias_score,
                )

            if object_tokens:
                score += object_match * 0.28
                if object_phrase_score >= 0.99 or object_alias_score >= 0.99:
                    score += 0.18

            if object_tokens and object_match < 0.42:
                score *= 0.42 if has_requested_fact else 0.16
            elif has_requested_fact:
                score += 0.12 + object_match * 0.16
            elif object_tokens and object_match >= 0.74:
                score += 0.08
            else:
                score *= 0.55

        return min(score, 1.0)
