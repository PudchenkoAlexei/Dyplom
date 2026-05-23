import sys
from types import SimpleNamespace

import pytest

from app.services.voice_assistant import (
    BaseQwenAssistantService,
    GuidedSearchPlan,
    KnowledgeBaseService,
    KnowledgeMatch,
    OpenAICompatibleAssistantService,
    VoiceAssistantService,
)


def test_voice_assistant_has_separate_generation_model_config() -> None:
    from app.services.voice_assistant import settings

    assert settings.voice_assistant_model
    assert settings.voice_assistant_inference_engine in {"transformers", "openai_compatible"}
    assert settings.voice_assistant_model != settings.llm_base_model
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
