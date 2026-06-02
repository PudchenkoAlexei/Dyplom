# ruff: noqa: F403,F405
from .shared import *

@dataclass(frozen=True)
class KnowledgeBaseEntry:
    id: str
    title: str
    question: str
    answer: str
    source_url: str
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "KnowledgeBaseEntry":
        return cls(
            id=str(raw["id"]),
            title=str(raw["title"]),
            question=str(raw["question"]),
            answer=str(raw["answer"]),
            source_url=str(raw["source_url"]),
            tags=tuple(str(tag) for tag in raw.get("tags", [])),
        )

    @property
    def primary_text(self) -> str:
        return " ".join([self.title, self.question, " ".join(self.tags)])

    @property
    def full_text(self) -> str:
        return " ".join([self.primary_text, self.answer])


@dataclass(frozen=True)
class KnowledgeMatch:
    entry: KnowledgeBaseEntry
    score: float


@dataclass(frozen=True)
class GuidedSearchPlan:
    queries: tuple[str, ...]
    raw_response: str


@dataclass(frozen=True)
class DirectFactIntent:
    name: str
    query_pattern: re.Pattern[str]
    fact_keywords: tuple[str, ...]


class GenerativeModel(Protocol):
    def eval(self) -> Any: ...

    def generate(self, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class EntrySearchIndex:
    entry: KnowledgeBaseEntry
    tokens: dict[str, tuple[str, ...]]
    stems: dict[str, set[str]]
    ngrams: dict[str, set[str]]
    primary_aliases: set[str]

