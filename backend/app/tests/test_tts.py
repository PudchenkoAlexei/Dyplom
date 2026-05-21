from app.services.tts import prepare_text_for_speech


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
