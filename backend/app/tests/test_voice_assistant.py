from app.services.voice_assistant import KnowledgeBaseService, VoiceAssistantService


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
    monkeypatch.setattr("app.services.voice_assistant.settings.voice_assistant_min_confidence", 0.99)
    service = VoiceAssistantService()

    response = service._answer_sync("Чи можна замовити довідку про невідому процедуру?")

    assert response.source == "fallback"
    assert response.can_create_ticket is True
    assert response.sources == []
