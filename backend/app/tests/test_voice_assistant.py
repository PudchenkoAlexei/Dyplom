import json
import sys
from types import SimpleNamespace

import pytest

from app.services.voice_assistant import (
    BaseQwenAssistantService,
    GuidedSearchPlan,
    KnowledgeBaseEntry,
    KnowledgeBaseService,
    KnowledgeMatch,
    OpenAICompatibleAssistantService,
    VoiceAssistantService,
    settings,
)


def test_voice_assistant_has_separate_generation_model_config() -> None:
    from app.services.voice_assistant import settings

    assert settings.voice_assistant_model
    assert settings.voice_assistant_inference_engine in {"transformers", "openai_compatible"}
    assert settings.voice_assistant_reuse_classifier_model is False
    assert settings.voice_assistant_quantization in {"none", "8bit", "4bit"}
    assert settings.voice_assistant_phone_use_llm is True
    assert settings.voice_assistant_phone_inference_engine in {
        "transformers",
        "openai_compatible",
    }
    assert settings.voice_assistant_phone_model
    assert settings.voice_assistant_phone_quantization in {"none", "8bit", "4bit"}
    assert settings.voice_assistant_phone_max_new_tokens >= 0
    assert isinstance(settings.voice_assistant_phone_ai_guided_retrieval, bool)
    assert settings.voice_assistant_phone_max_context_items == 1


def test_quantized_model_load_kwargs_use_bitsandbytes_config() -> None:
    import torch

    if not torch.cuda.is_available():
        pytest.skip("bitsandbytes quantized loading is only exercised when CUDA is available")

    kwargs = BaseQwenAssistantService._build_model_load_kwargs(torch, quantization="4bit")

    assert kwargs["device_map"] == "auto"
    assert kwargs["quantization_config"].load_in_4bit is True


def test_openai_compatible_assistant_calls_chat_completions(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeHTTPError(Exception):
        pass

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "Довідку видає деканат."}}]}

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: float,
    ) -> FakeResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setitem(
        sys.modules,
        "httpx",
        SimpleNamespace(post=fake_post, HTTPError=FakeHTTPError),
    )

    service = OpenAICompatibleAssistantService(
        model_name="local-qwen",
        base_url="http://127.0.0.1:8080/v1/",
        api_key="local-token",
        timeout_seconds=12,
        temperature=0,
    )
    match = KnowledgeMatch(entry=KnowledgeBaseService().entries[0], score=1)

    answer = service.generate_answer("Як отримати довідку?", [match], max_new_tokens=77, for_phone=True)

    assert answer == "Довідку видає деканат."
    assert captured["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert captured["timeout"] == 12
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "local-qwen"
    assert payload["max_tokens"] == 77
    assert payload["temperature"] == 0
    assert payload["stream"] is False
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer local-token"


def test_clean_answer_removes_urls_from_generated_text() -> None:
    answer = BaseQwenAssistantService._clean_answer(
        "Докладна інформація на сайті - https://pk.kpi.ua/entry-1-course-ms/"
    )

    assert "http" not in answer
    assert answer == "Докладна інформація на сайті"


def test_phone_answer_prompt_requires_definition_first_for_explanatory_questions() -> None:
    match = KnowledgeMatch(entry=KnowledgeBaseService().entries[0], score=1)

    messages = BaseQwenAssistantService._build_phone_answer_messages(
        "Що таке академічна різниця?",
        [match],
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "Спочатку дай коротке визначення простими словами" in prompt
    assert "не на можливу помилку розпізнавання" in prompt


def test_phone_answer_prompt_focuses_direct_fact_questions_on_requested_field() -> None:
    entry = KnowledgeBaseEntry(
        id="direct-fact",
        title="Тестовий підрозділ",
        question="Де знаходиться тестовий підрозділ?",
        answer=(
            "Оголошення публікуються за адресою http://example.test . "
            "Ви можете підписатися на http://example.test/feed , щоб отримувати повідомлення. "
            "Тестовий підрозділ: Адреса підрозділу: навчальний корпус 1, кабінет 101, 1-й поверх "
            "Початок роботи о 9.00 Телефони: 111-11-11"
        ),
        source_url="https://example.test",
        tags=("тест",),
    )
    match = KnowledgeMatch(entry=entry, score=1)

    messages = BaseQwenAssistantService._build_phone_answer_messages(
        "Яка адреса тестового підрозділу?",
        [match],
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "Користувач просить конкретний факт" in prompt
    assert "навчальний корпус 1, кабінет 101, 1-й поверх" in prompt
    assert "публікуються" not in prompt
    assert "підписатися" not in prompt
    assert "Телефони" not in prompt


def test_phone_answer_prompt_keeps_requested_fact_from_unfinished_source_tail() -> None:
    entry = KnowledgeBaseEntry(
        id="direct-phone-tail",
        title="Тестовий підрозділ",
        question="Який телефон тестового підрозділу?",
        answer=(
            "Тестовий підрозділ: Адреса підрозділу: навчальний корпус 1, кабінет 101 "
            "Телефони: 111-11-11, 222-22-22"
        ),
        source_url="https://example.test",
        tags=("тест",),
    )
    match = KnowledgeMatch(entry=entry, score=1)

    messages = BaseQwenAssistantService._build_phone_answer_messages(
        "Який телефон тестового підрозділу?",
        [match],
    )
    prompt = "\n".join(message["content"] for message in messages)

    assert "111-11-11, 222-22-22" in prompt
    assert "навчальний корпус 1" not in prompt


def test_phone_direct_fact_answer_preserves_exact_contact_values() -> None:
    entry = KnowledgeBaseEntry(
        id="direct-contact",
        title="Тестовий підрозділ",
        question="Який телефон тестового підрозділу?",
        answer=(
            "Оголошення публікуються на сайті. "
            "Адреса підрозділу: навчальний корпус 1, кабінет 101 "
            "Телефони: 111-11-11, 222-22-22"
        ),
        source_url="https://example.test",
        tags=("тест",),
    )

    answer = VoiceAssistantService._direct_phone_fact_answer(
        "Який телефон тестового підрозділу?",
        entry,
    )

    assert answer == "Телефони: 111-11-11, 222-22-22."


def test_phone_direct_fact_answer_keeps_address_with_abbreviated_prospect() -> None:
    entry = KnowledgeBaseEntry(
        id="library-address",
        title="Доступ в бібліотеку КПІ",
        question="Чи можуть сторонні особи користуватися бібліотекою КПІ?",
        answer=(
            "Так. Студенти інших навчальних закладів можуть користовутися послугами бібліотеки. "
            "Адреса: 252056, Київ, пр. Перемоги, 37., тел. 204-80-72 "
            "(будівля на площі Знань). Сайт бібліотеки: https://library.kpi.ua ."
        ),
        source_url="https://example.test/library",
        tags=("бібліотека",),
    )

    answer = VoiceAssistantService._direct_phone_fact_answer(
        "яка адреса бібліотеки кпі",
        entry,
    )

    assert answer is not None
    assert answer != "Адреса: 252056, Київ, пр."
    assert answer.startswith("Адреса: 252056, Київ, пр. Перемоги, 37")
    assert "204-80-72" not in answer


def test_phone_direct_fact_answer_returns_only_requested_phone_from_compact_contact_block() -> None:
    entry = KnowledgeBaseEntry(
        id="library-phone",
        title="Доступ в бібліотеку КПІ",
        question="Чи можуть сторонні особи користуватися бібліотекою КПІ?",
        answer=(
            "Так. Студенти інших навчальних закладів можуть користовутися послугами бібліотеки. "
            "Адреса: 252056, Київ, пр. Перемоги, 37., тел. 204-80-72 "
            "(будівля на площі Знань). Сайт бібліотеки: https://library.kpi.ua ."
        ),
        source_url="https://example.test/library",
        tags=("бібліотека",),
    )

    answer = VoiceAssistantService._direct_phone_fact_answer(
        "який номер телефону бібліотеки кпі",
        entry,
    )

    assert answer == "Телефон: 204-80-72."


def test_phone_direct_fact_answer_ignores_dates_and_hours_near_contacts() -> None:
    entry = KnowledgeBaseEntry(
        id="contacts-with-hours",
        title="Тестовий архів",
        question="Який телефон тестового архіву?",
        answer=(
            "Телефони: 204-95-68, 204-91-78, 204-95-67. "
            "Прийом відвідувачів: 10.00-16.00, перерва 13.00-14.00. "
            "Дата оновлення: 29.07.93."
        ),
        source_url="https://example.test/archive",
        tags=("архів",),
    )

    answer = VoiceAssistantService._direct_phone_fact_answer(
        "Який номер телефону тестового архіву?",
        entry,
    )

    assert answer == "Телефони: 204-95-68, 204-91-78, 204-95-67."
    assert "10.00" not in answer
    assert "29.07.93" not in answer


def test_phone_direct_fact_answer_does_not_return_date_as_phone() -> None:
    entry = KnowledgeBaseEntry(
        id="invalid-phone-date",
        title="Тестова довідка",
        question="Який телефон тестової довідки?",
        answer="Телефон для уточнення: 29.07.93.",
        source_url="https://example.test/date",
        tags=("довідка",),
    )

    answer = VoiceAssistantService._direct_phone_fact_answer(
        "Який номер телефону тестової довідки?",
        entry,
    )

    assert answer == ""


def test_phone_direct_fact_answer_returns_only_email_addresses() -> None:
    entry = KnowledgeBaseEntry(
        id="email-contact",
        title="Оренда приміщень",
        question="Яка електронна пошта для оренди?",
        answer="e-mail: orenda@kpi.ua Кампус університету. Інші питання: info@example.test.",
        source_url="https://example.test/rent",
        tags=("оренда",),
    )

    answer = VoiceAssistantService._direct_phone_fact_answer(
        "Яка електронна пошта для оренди?",
        entry,
    )

    assert answer == "Електронні пошти: orenda@kpi.ua, info@example.test."
    assert "Кампус" not in answer


def test_phone_direct_fact_answer_keeps_contextual_caveat_before_contact() -> None:
    entry = KnowledgeBaseEntry(
        id="contact-with-caveat",
        title="Контакти умовного підрозділу",
        question="Який телефон умовного підрозділу?",
        answer=(
            "Підрозділу під такою назвою не існує. "
            "Є довідкова служба університету. "
            "Телефон: 111-22-33."
        ),
        source_url="https://example.test/contact",
        tags=("контакти",),
    )

    answer = VoiceAssistantService._direct_phone_fact_answer(
        "Який телефон умовного підрозділу?",
        entry,
    )

    assert answer.startswith("Підрозділу під такою назвою не існує.")
    assert "Телефон: 111-22-33" in answer


def test_clean_answer_removes_exact_repeated_sentences() -> None:
    answer = BaseQwenAssistantService._clean_answer(
        "Перше речення. Друге речення. Друге речення. Третє речення."
    )

    assert answer == "Перше речення. Друге речення. Третє речення."


def test_clean_answer_polishes_common_phone_llm_language_errors() -> None:
    answer = BaseQwenAssistantService._clean_answer(
        "Якщо хочеш отримати довідку, треба подати документи, які підтвердюють зміну. "
        "Якщо потрібно, можу пояснити, що треба зготувати."
    )

    assert "хочеш" not in answer
    assert "підтверджують" in answer
    assert "можу пояснити" not in answer
    assert "підготувати" not in answer


def test_knowledge_base_finds_student_reference() -> None:
    service = KnowledgeBaseService()

    matches = service.search("Як отримати довідку про навчання?")

    assert matches
    assert matches[0].entry.source_url == "https://kpi.ua/reference"
    assert matches[0].score > 0


def test_knowledge_base_finds_generated_faq_topics() -> None:
    service = KnowledgeBaseService()

    cases = [
        ("Які документи потрібні для переведення в КПІ?", "https://kpi.ua/gbook"),
        ("Що робити якщо мене не допускають до сесії?", "https://kpi.ua/faq-session"),
        ("Як перевестися на бюджет?", "https://kpi.ua/perevod"),
        ("Який телефон бухгалтерії?", "https://kpi.ua/accounting-phone"),
    ]

    for question, expected_url in cases:
        matches = service.search(question)

        assert matches
        assert matches[0].entry.source_url == expected_url


def test_knowledge_base_prefers_specific_topic_over_generic_document_words() -> None:
    service = KnowledgeBaseService()

    matches = service.search("Які документи потрібні для дубліката диплома?", limit=5)

    assert matches
    assert matches[0].entry.source_url == "https://kpi.ua/graduation-attestation"


def test_voice_assistant_answers_academic_mobility_info_question_with_soft_match(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_ai_guided_retrieval", False)
    service = VoiceAssistantService()

    response = service._answer_sync("Де дізнатися про академічну мобільність Erasmus?")

    assert response.source == "knowledge_base"
    assert response.sources[0].url == "https://kpi.ua/gbook-12"
    assert "відділ академічної мобільності" in response.answer_text


def test_knowledge_base_matches_split_compound_topic_names() -> None:
    service = KnowledgeBaseService()

    cases = [
        ("Який номер телефону кіно клубу КПІ?", "https://kpi.ua/FAQs"),
        ("Що таке академ різниця?", "https://kpi.ua/academic"),
        ("З яких причин можна взяти академ відпустку?", "https://kpi.ua/academic_vacation"),
    ]

    for question, expected_url in cases:
        matches = service.search(question)

        assert matches
        assert matches[0].entry.source_url == expected_url


def test_knowledge_base_builds_compound_aliases_for_new_topics(tmp_path) -> None:
    knowledge_base_path = tmp_path / "knowledge.json"
    knowledge_base_path.write_text(
        json.dumps(
            [
                {
                    "id": "new-compound-topic",
                    "title": "Тесткомісія",
                    "question": "Як звернутися до тесткомісії?",
                    "answer": "Телефони: 111-11-11.",
                    "source_url": "https://example.test/compound",
                    "tags": ["Тесткомісія"],
                },
                {
                    "id": "generic-phone",
                    "title": "Телефонний довідник",
                    "question": "Який загальний телефон?",
                    "answer": "Телефон: 222-22-22.",
                    "source_url": "https://example.test/phone",
                    "tags": ["телефон"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service = KnowledgeBaseService(knowledge_base_path)

    matches = service.search("Який телефон тест комісії?", limit=2)

    assert matches
    assert matches[0].entry.source_url == "https://example.test/compound"


def test_phone_mode_answers_direct_fact_for_split_compound_topic(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    service = VoiceAssistantService()

    response = service._answer_sync("Який номер телефону кіно клубу КПІ?", for_phone=True)

    assert response.source == "knowledge_base"
    assert response.sources[0].url == "https://kpi.ua/FAQs"
    assert response.answer_text == "Телефони: 454-99-01, 454-99-02."


def test_phone_mode_prioritizes_requested_object_for_direct_phone_fact(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    service = VoiceAssistantService()

    response = service._answer_sync("який номер телефону в бібліотекі кпі", for_phone=True)

    assert response.source == "knowledge_base"
    assert response.confidence >= settings.voice_assistant_min_confidence
    assert response.sources[0].url == "https://kpi.ua/node/8024"
    assert response.answer_text == "Телефон: 204-80-72."


def test_phone_mode_does_not_ask_llm_to_invent_missing_phone(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge_base_path = tmp_path / "knowledge.json"
    knowledge_base_path.write_text(
        json.dumps(
            [
                {
                    "id": "no-phone",
                    "title": "Тестовий деканат",
                    "question": "Контакти тестового деканату",
                    "answer": "Адреса: корпус 1, кабінет 101. Телефон у джерелі не зазначено.",
                    "source_url": "https://example.test/no-phone",
                    "tags": ["деканат"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", True)
    monkeypatch.setattr(
        "app.services.voice_assistant.settings.voice_assistant_phone_ai_guided_retrieval",
        False,
    )
    monkeypatch.setattr(
        "app.services.voice_assistant.get_phone_qwen_assistant_service",
        lambda: (_ for _ in ()).throw(RuntimeError("phone contact should stay extractive")),
    )
    service = VoiceAssistantService()
    service.knowledge_base = KnowledgeBaseService(knowledge_base_path)

    response = service._answer_sync("Який телефон тестового деканату?", for_phone=True)

    assert response.source == "knowledge_base"
    assert response.used_llm is False
    assert response.answer_text == "У наданій офіційній інформації телефон не вказано."


def test_phone_mode_allows_soft_match_when_query_requests_direct_fact(
    tmp_path,
    monkeypatch,
) -> None:
    knowledge_base_path = tmp_path / "knowledge.json"
    knowledge_base_path.write_text(
        json.dumps(
            [
                {
                    "id": "test-center",
                    "title": "Тестцентр",
                    "question": "Контакти тестцентру",
                    "answer": "Адреса Тестцентру: корпус 1, кімната 2. Телефон: 111-11-11.",
                    "source_url": "https://example.test/center",
                    "tags": ["Тестцентр"],
                },
                {
                    "id": "student-behavior",
                    "title": "Поведінка студентів",
                    "question": "Де можуть знаходитись студенти?",
                    "answer": "Студенти повинні дотримуватися правил поведінки в університеті.",
                    "source_url": "https://example.test/behavior",
                    "tags": ["знаходитись", "студенти"],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    service = VoiceAssistantService()
    service.knowledge_base = KnowledgeBaseService(knowledge_base_path)

    response = service._answer_sync("де знаходитись тестцентр", for_phone=True)

    assert response.source == "knowledge_base"
    assert response.confidence >= settings.voice_assistant_min_confidence
    assert response.sources[0].url == "https://example.test/center"
    assert response.answer_text == "Адреса Тестцентру: корпус 1, кімната 2."


def test_voice_assistant_falls_back_for_unknown_question(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_ai_guided_retrieval", False)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_min_confidence", 0.99)
    service = VoiceAssistantService()

    response = service._answer_sync("Чи можна замовити довідку про невідому процедуру?")

    assert response.source == "fallback"
    assert response.can_create_ticket is False
    assert "заяв" not in response.answer_text.lower()
    assert response.sources == []


def test_knowledge_base_includes_answer_context_for_academic_mobility() -> None:
    service = KnowledgeBaseService()

    matches = service.search("Де дізнатись про академічну мобільність?", limit=3)

    assert any(match.entry.source_url == "https://kpi.ua/gbook-12" for match in matches)


def test_voice_assistant_uses_reliable_retrieval_without_direct_rules(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    service = VoiceAssistantService()

    response = service._answer_sync("Де дізнатись про академічну мобільність?")

    assert response.source == "knowledge_base"
    assert response.sources[0].url == "https://kpi.ua/gbook-12"


def test_voice_assistant_does_not_offer_ticket_when_llm_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_ai_guided_retrieval", False)
    monkeypatch.setattr(
        "app.services.voice_assistant.get_base_qwen_assistant_service",
        lambda: (_ for _ in ()).throw(RuntimeError("model unavailable")),
    )
    service = VoiceAssistantService()

    response = service._answer_sync("Де дізнатись про академічну мобільність?")

    assert response.source == "llm_unavailable"
    assert response.can_create_ticket is False
    assert "заяв" not in response.answer_text.lower()


def test_voice_assistant_falls_back_for_ambiguous_broad_dormitory_question(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_ai_guided_retrieval", False)
    service = VoiceAssistantService()

    response = service._answer_sync("Куди звертатися з питанням по гуртожитку?")

    assert response.source == "fallback"
    assert response.sources == []


def test_voice_assistant_falls_back_for_missing_payment_requisites_source(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", False)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_ai_guided_retrieval", False)
    service = VoiceAssistantService()

    response = service._answer_sync("Де взяти реквізити для оплати навчання?")

    assert response.source == "fallback"
    assert response.sources == []


def test_guided_retrieval_lets_model_drive_faq_search(monkeypatch) -> None:
    class FakeAssistant:
        model_name = "fake-qwen"

        def plan_search_queries(self, question: str) -> GuidedSearchPlan:
            assert question
            return GuidedSearchPlan(
                queries=("академічна мобільність", "Erasmus обмін"),
                raw_response="{}",
            )

        def generate_answer(
            self,
            question: str,
            matches: list[KnowledgeMatch],
            *,
            allow_related_sources: bool = False,
        ) -> str:
            assert question
            assert matches
            assert allow_related_sources is True
            return "За схожими джерелами зверніться до відділу академічної мобільності."

    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_phone_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_ai_guided_retrieval", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_min_confidence", 0.99)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_soft_min_confidence", 0.1)
    monkeypatch.setattr(
        "app.services.voice_assistant.get_base_qwen_assistant_service",
        lambda: FakeAssistant(),
    )
    service = VoiceAssistantService()

    response = service._answer_sync("Де дізнатись про обмін?")

    assert response.source == "llm_guided"
    assert response.used_llm is True
    assert response.model_name == "fake-qwen"
    assert response.sources


def test_phone_mode_skips_guided_retrieval_and_can_disable_phone_token_limit(
    monkeypatch,
) -> None:
    class FakeAssistant:
        model_name = "fake-qwen"

        def plan_search_queries(self, question: str) -> GuidedSearchPlan:
            raise AssertionError("phone mode should not use guided retrieval by default")

        def generate_answer(
            self,
            question: str,
            matches: list[KnowledgeMatch],
            *,
            allow_related_sources: bool = False,
            max_new_tokens: int | None = None,
            for_phone: bool = False,
        ) -> str:
            assert question
            assert matches
            assert max_new_tokens is None
            assert for_phone is True
            return "Довідку про навчання можна отримати у деканаті."

    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_phone_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_ai_guided_retrieval", True)
    monkeypatch.setattr(
        "app.services.voice_assistant.settings.voice_assistant_phone_ai_guided_retrieval",
        False,
    )
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_phone_max_new_tokens", 0)
    monkeypatch.setattr(
        "app.services.voice_assistant.get_phone_qwen_assistant_service",
        lambda: FakeAssistant(),
    )
    service = VoiceAssistantService()

    response = service._answer_sync("Як отримати довідку про навчання?", for_phone=True)

    assert response.source == "llm"
    assert response.used_llm is True
    assert response.answer_text == "Довідку про навчання можна отримати у деканаті."


def test_phone_mode_can_use_explicit_phone_token_budget(monkeypatch) -> None:
    class FakeAssistant:
        model_name = "fake-qwen"

        def generate_answer(
            self,
            question: str,
            matches: list[KnowledgeMatch],
            *,
            allow_related_sources: bool = False,
            max_new_tokens: int | None = None,
            for_phone: bool = False,
        ) -> str:
            assert max_new_tokens == 77
            assert for_phone is True
            return "Довідку про навчання можна отримати у деканаті."

    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_phone_use_llm", True)
    monkeypatch.setattr(
        "app.services.voice_assistant.settings.voice_assistant_phone_ai_guided_retrieval",
        False,
    )
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_phone_max_new_tokens", 77)
    monkeypatch.setattr(
        "app.services.voice_assistant.get_phone_qwen_assistant_service",
        lambda: FakeAssistant(),
    )
    service = VoiceAssistantService()

    response = service._answer_sync("Як отримати довідку про навчання?", for_phone=True)

    assert response.source == "llm"
    assert response.used_llm is True


def test_phone_mode_generates_model_answer_on_each_call(monkeypatch) -> None:
    class FakeAssistant:
        model_name = "fake-qwen"
        calls = 0

        def generate_answer(
            self,
            question: str,
            matches: list[KnowledgeMatch],
            *,
            allow_related_sources: bool = False,
            max_new_tokens: int | None = None,
            for_phone: bool = False,
        ) -> str:
            self.calls += 1
            return f"Відповідь сформована моделлю {self.calls}."

    fake = FakeAssistant()

    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_phone_use_llm", True)
    monkeypatch.setattr(
        "app.services.voice_assistant.settings.voice_assistant_phone_ai_guided_retrieval",
        False,
    )
    monkeypatch.setattr(
        "app.services.voice_assistant.get_phone_qwen_assistant_service",
        lambda: fake,
    )
    service = VoiceAssistantService()

    first = service._answer_sync("Як отримати довідку про навчання?", for_phone=True)
    second = service._answer_sync("Як отримати довідку про навчання?", for_phone=True)

    assert fake.calls == 2
    assert first.source == "llm"
    assert second.source == "llm"
    assert second.used_llm is True
    assert second.model_name == "fake-qwen"
    assert second.answer_text != first.answer_text


def test_phone_mode_uses_fast_knowledge_base_answer_when_phone_llm_disabled(monkeypatch) -> None:
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_use_llm", True)
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_phone_use_llm", False)
    monkeypatch.setattr(
        "app.services.voice_assistant.get_phone_qwen_assistant_service",
        lambda: (_ for _ in ()).throw(RuntimeError("phone mode should stay fast")),
    )
    service = VoiceAssistantService()

    response = service._answer_sync("Як отримати довідку про навчання?", for_phone=True)

    assert response.source == "knowledge_base"
    assert response.used_llm is False
    assert response.model_name is None
    assert response.sources[0].url == "https://kpi.ua/reference"
    assert "довід" in response.answer_text.lower()
