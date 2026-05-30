from app.services.knowledge_base_admin import (
    knowledge_content_hash,
    normalize_seed_answer,
    normalize_seed_title,
    normalize_slug,
    normalize_tags,
)
from app.services.voice_assistant import KnowledgeBaseEntry, KnowledgeBaseService


def test_normalize_tags_strips_and_deduplicates_values() -> None:
    assert normalize_tags([" довідка ", "Довідка", "", "деканат"]) == ["довідка", "деканат"]


def test_normalize_slug_keeps_readable_ukrainian_slug() -> None:
    assert normalize_slug("Довідка про навчання!") == "довідка-про-навчання"


def test_normalize_seed_title_replaces_question_like_imported_titles() -> None:
    title = normalize_seed_title(
        {
            "id": "transfer-faculty",
            "title": "Чи можна після 1-го курса перейти на інший факультет?",
        }
    )

    assert title == "Переведення на інший факультет або спеціальність"


def test_normalize_seed_answer_cleans_library_entry() -> None:
    answer = normalize_seed_answer(
        {
            "id": "node-8024",
            "title": "Доступ в бібліотеку КПІ",
            "answer": "Так. Сайт бібліотеки: https://library.kpi.ua .",
        }
    )

    assert "користуватися" in answer
    assert "Сайт бібліотеки:" not in answer


def test_knowledge_content_hash_is_stable_for_equivalent_whitespace() -> None:
    first_hash = knowledge_content_hash(
        title="Довідка",
        question="Як отримати  довідку?",
        answer="Зверніться   до деканату.",
        source_url="https://example.test/info",
        tags=["деканат"],
    )
    second_hash = knowledge_content_hash(
        title="Довідка",
        question="Як отримати довідку?",
        answer="Зверніться до деканату.",
        source_url="https://example.test/info",
        tags=["деканат"],
    )

    assert first_hash == second_hash


def test_knowledge_base_service_can_be_built_from_database_entries() -> None:
    service = KnowledgeBaseService.from_entries(
        [
            KnowledgeBaseEntry(
                id="certificate",
                title="Довідка про навчання",
                question="Де отримати довідку про навчання?",
                answer="Довідку видає деканат.",
                source_url="https://example.test/certificate",
                tags=("довідка", "деканат"),
            ),
            KnowledgeBaseEntry(
                id="wifi",
                title="Wi-Fi",
                question="Як підключитися до Wi-Fi?",
                answer="Зверніться до KPI-Телеком.",
                source_url="https://example.test/wifi",
                tags=("інтернет",),
            ),
        ]
    )

    matches = service.search("де взяти довідку про навчання")

    assert matches
    assert matches[0].entry.id == "certificate"


def test_static_knowledge_base_finds_corporate_email_query() -> None:
    service = KnowledgeBaseService()

    matches = service.search("Як отримати корпоративну пошту КПІ?", limit=3)

    assert any(match.entry.source_url == "https://kpi.ua/faq-net" for match in matches)
