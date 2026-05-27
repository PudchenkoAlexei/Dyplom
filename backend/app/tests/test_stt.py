import json

from app.services.stt import (
    build_initial_prompt,
    build_stt_domain_terms,
    correct_domain_transcription_text,
)


def test_domain_transcription_correction_repairs_noisy_domain_word() -> None:
    text = correct_domain_transcription_text(
        "чи потрібен докумект",
        vocabulary=("документ",),
    )

    assert text == "чи потрібен документ"


def test_domain_transcription_correction_keeps_legitimate_word_forms() -> None:
    text = correct_domain_transcription_text(
        "який номер телефону",
        vocabulary=("телефон",),
    )

    assert text == "який номер телефону"


def test_domain_transcription_correction_does_not_merge_normal_topic_phrase() -> None:
    text = correct_domain_transcription_text(
        "як отримати навчальну довідку",
        vocabulary=("навчальнадовідка",),
    )

    assert text == "як отримати навчальну довідку"


def test_stt_domain_terms_are_built_from_knowledge_base(tmp_path) -> None:
    knowledge_base_path = tmp_path / "knowledge.json"
    knowledge_base_path.write_text(
        json.dumps(
            [
                {
                    "title": "Новий сервіс",
                    "question": "Як отримати спеціальну довідку?",
                    "tags": ["Спеціальна", "довідка"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    terms = set(build_stt_domain_terms(knowledge_base_path))

    assert "новий сервіс" in terms
    assert "спеціальну" in terms
    assert "довідку" in terms


def test_initial_prompt_mentions_phone_context_and_domain_terms() -> None:
    prompt = build_initial_prompt(("спеціальна", "довідка"))

    assert prompt is not None
    assert "Українська телефонна розмова" in prompt
    assert "спеціальна" in prompt
    assert "довідка" in prompt
