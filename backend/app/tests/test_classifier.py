from app.services.classifier import TicketClassifierService


def test_classifier_json_extraction() -> None:
    raw = '```json\n{"category":"стипендія","priority":"medium"}\n```'

    parsed = TicketClassifierService._parse_json(raw)

    assert parsed == {"category": "стипендія", "priority": "medium"}


def test_classifier_replaces_generated_confidence_with_service_score() -> None:
    parsed = {"category": "стипендія", "priority": "medium", "confidence": 1.0}

    output = TicketClassifierService._validated_output(
        parsed,
        {"стипендія", "інше / первинна маршрутизація"},
    )

    assert output.category == "стипендія"
    assert output.confidence == TicketClassifierService.DEFAULT_CONFIDENCE


def test_classifier_falls_back_for_unknown_category() -> None:
    parsed = {"category": "диплом", "priority": "medium"}

    output = TicketClassifierService._validated_output(
        parsed,
        {"стипендія", "інше / первинна маршрутизація"},
    )

    assert output.category == "інше / первинна маршрутизація"
    assert output.confidence == TicketClassifierService.FALLBACK_CONFIDENCE
