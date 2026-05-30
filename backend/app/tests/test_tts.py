import asyncio
import sys
from types import SimpleNamespace

from app.services.tts import TextToSpeechService, add_punctuation_pauses, prepare_text_for_speech


def test_prepare_text_for_speech_expands_kpi_acronym() -> None:
    text = "\u0414\u043e\u0432\u0456\u0434\u043a\u0430 \u041a\u041f\u0406 \u0442\u0430 KPI-\u0422\u0435\u043b\u0435\u043a\u043e\u043c"

    speech_text = prepare_text_for_speech(text)

    assert "\u043a\u0430 \u043f\u0435 \u0456" in speech_text
    assert "\u041a\u041f\u0406" not in speech_text
    assert "KPI" not in speech_text
    assert "\u043a\u0430 \u043f\u0435 \u0456 \u0422\u0435\u043b\u0435\u043a\u043e\u043c" in speech_text


def test_prepare_text_for_speech_expands_common_abbreviations() -> None:
    text = "\u041a\u041f\u0406 \u0456\u043c. \u0406\u0433\u043e\u0440\u044f \u0421\u0456\u043a\u043e\u0440\u0441\u044c\u043a\u043e\u0433\u043e, FAQ, URL"

    speech_text = prepare_text_for_speech(text)

    assert "\u0456\u043c\u0435\u043d\u0456 \u0406\u0433\u043e\u0440\u044f" in speech_text
    assert "\u043a\u0430 \u043f\u0435 \u0456, \u0456\u043c\u0435\u043d\u0456" in speech_text
    assert "\u043f\u043e\u0448\u0438\u0440\u0435\u043d\u0438\u0445 \u043f\u0438\u0442\u0430\u043d\u044c" in speech_text
    assert "\u043f\u043e\u0441\u0438\u043b\u0430\u043d\u043d\u044f" in speech_text


def test_prepare_text_for_speech_handles_mixed_kpi_and_abbreviation_without_space() -> None:
    speech_text = prepare_text_for_speech("КПI ім.Ігоря Сікорського")

    assert "ка пе і, імені Ігоря" in speech_text
    assert "КПI" not in speech_text
    assert "іменіІгоря" not in speech_text


def test_add_punctuation_pauses_keeps_dates_and_times_intact() -> None:
    text = (
        "\u0417\u0430\u044f\u0432\u0430, \u043a\u043e\u043f\u0456\u044f; "
        "\u0434\u043e\u0432\u0456\u0434\u043a\u0430: \u0437 9:00 \u0434\u043e 10:00. "
        "\u041f\u043e\u0441\u0442\u0430\u043d\u043e\u0432\u0430 \u0432\u0456\u0434 27.01.2010 \u0440. \u2116 55"
    )

    speech_text = add_punctuation_pauses(text)

    assert "\u0417\u0430\u044f\u0432\u0430, \u043a\u043e\u043f\u0456\u044f;\n" in speech_text
    assert "\u0434\u043e\u0432\u0456\u0434\u043a\u0430:\n" in speech_text
    assert "9:00" in speech_text
    assert "10:00" in speech_text
    assert "27.01.2010" in speech_text
    assert "\u0440.\n\u2116" in speech_text


def test_add_punctuation_pauses_keeps_short_comma_clauses_inline() -> None:
    speech_text = add_punctuation_pauses("Паспорт, копія паспорта, заява.")

    assert speech_text == "Паспорт, копія паспорта, заява."


def test_add_punctuation_pauses_breaks_after_comma_before_long_clause() -> None:
    speech_text = add_punctuation_pauses(
        "Заява, копія паспорта громадянина України та паспорта для виїзду за кордон."
    )

    assert "Заява,\nкопія паспорта" in speech_text


def test_prepare_text_for_speech_expands_phone_unfriendly_abbreviations() -> None:
    text = "\u0414\u043e\u0432\u0456\u0434\u043a\u0430 \u0443 \u0417\u0412\u041e, \u043c. \u041a\u0438\u0457\u0432, \u0432\u0443\u043b. \u041f\u043e\u043b\u0456\u0442\u0435\u0445\u043d\u0456\u0447\u043d\u0430, \u043a\u0456\u043c. 296, \u2116 16, \u0442\u0435\u043b. 204-80-72"

    speech_text = prepare_text_for_speech(text)

    assert "\u0443 \u0437\u0430\u043a\u043b\u0430\u0434\u0456 \u0432\u0438\u0449\u043e\u0457 \u043e\u0441\u0432\u0456\u0442\u0438" in speech_text
    assert "\u043c\u0456\u0441\u0442\u043e \u041a\u0438\u0457\u0432" in speech_text
    assert "\u0432\u0443\u043b\u0438\u0446\u044f \u041f\u043e\u043b\u0456\u0442\u0435\u0445\u043d\u0456\u0447\u043d\u0430" in speech_text
    assert "\u043a\u0456\u043c\u043d\u0430\u0442\u0430 296" in speech_text
    assert "\u043d\u043e\u043c\u0435\u0440 16" in speech_text
    assert "\u0442\u0435\u043b\u0435\u0444\u043e\u043d 204-80-72" in speech_text


def test_prepare_text_for_speech_spells_postal_index_in_address() -> None:
    speech_text = prepare_text_for_speech("Адреса: 252056, Київ, пр. Перемоги, 37.")

    assert "два п'ять два нуль п'ять шість" in speech_text
    assert "252056" not in speech_text
    assert "проспект Перемоги" in speech_text


def test_synthesize_does_not_truncate_when_char_limit_is_zero(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeCommunicate:
        def __init__(self, text: str, voice: str, *, rate: str) -> None:
            captured["text"] = text
            captured["voice"] = voice
            captured["rate"] = rate

        async def stream(self):
            yield {"type": "audio", "data": b"audio"}

    monkeypatch.setitem(
        sys.modules,
        "edge_tts",
        SimpleNamespace(Communicate=FakeCommunicate),
    )
    monkeypatch.setattr("app.services.tts.settings.voice_assistant_tts_enabled", True)
    monkeypatch.setattr("app.services.tts.settings.voice_assistant_tts_max_chars", 0)

    text = "long answer " * 120

    result = asyncio.run(TextToSpeechService().synthesize(text))

    assert captured["text"] == text.strip()
    assert result.audio == b"audio"


def test_synthesize_calls_tts_for_repeated_text(monkeypatch) -> None:
    calls = {"count": 0}

    class FakeCommunicate:
        def __init__(self, text: str, voice: str, *, rate: str) -> None:
            calls["count"] += 1

        async def stream(self):
            yield {"type": "audio", "data": b"audio"}

    monkeypatch.setitem(
        sys.modules,
        "edge_tts",
        SimpleNamespace(Communicate=FakeCommunicate),
    )
    monkeypatch.setattr("app.services.tts.settings.voice_assistant_tts_enabled", True)

    service = TextToSpeechService()
    first = asyncio.run(service.synthesize("Довідку видає деканат."))
    second = asyncio.run(service.synthesize("Довідку видає деканат."))

    assert calls["count"] == 2
    assert first.audio == b"audio"
    assert second.audio == first.audio
