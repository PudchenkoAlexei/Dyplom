from app.models.enums import UserRole
from app.services.classifier import TicketClassifierService
from app.services.classifier_prompt import CatalogItem, apply_classifier_chat_template


class DummyTokenizer:
    def __init__(self) -> None:
        self.kwargs = None

    def apply_chat_template(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        return "rendered"


def test_classifier_chat_template_disables_thinking() -> None:
    tokenizer = DummyTokenizer()

    rendered = apply_classifier_chat_template(
        tokenizer,
        [{"role": "user", "content": "test"}],
        add_generation_prompt=True,
    )

    assert rendered == "rendered"
    assert tokenizer.kwargs["enable_thinking"] is False


def test_classifier_json_extraction() -> None:
    raw = '```json\n{"category":"стипендія","priority":"medium"}\n```'

    parsed = TicketClassifierService._parse_json(raw)

    assert parsed == {"category": "стипендія", "priority": "medium"}


def test_classifier_prompt_includes_category_descriptions() -> None:
    prompt = TicketClassifierService._build_prompt(
        role=UserRole.student,
        text="Не бачу стипендіальний рейтинг у кабінеті.",
        categories=[
            CatalogItem(name="стипендія", description="рейтинги, виплати, банківські реквізити"),
            CatalogItem(name="навчальний процес", description="розклад, сесія, практики"),
        ],
    )

    assert "Доступні категорії та орієнтири" in prompt
    assert "стипендія (рейтинги, виплати" in prompt
    assert "Текст звернення: Не бачу стипендіальний рейтинг у кабінеті." in prompt


def test_classifier_replaces_generated_confidence_with_service_score() -> None:
    parsed = {"category": "стипендія", "priority": "medium", "confidence": 1.0}

    output = TicketClassifierService._validated_output(
        parsed,
        {"стипендія", "інше / первинна маршрутизація"},
    )

    assert output.category == "стипендія"
    assert output.confidence == TicketClassifierService.DEFAULT_CONFIDENCE
    assert output.confidence_source == "service_default"


def test_classifier_falls_back_for_unknown_category() -> None:
    parsed = {"category": "диплом", "priority": "medium"}

    output = TicketClassifierService._validated_output(
        parsed,
        {"стипендія", "інше / первинна маршрутизація"},
    )

    assert output.category == "інше / первинна маршрутизація"
    assert output.confidence == TicketClassifierService.FALLBACK_CONFIDENCE
    assert output.confidence_source == "fallback"
    assert output.fallback_reason is not None


def test_classifier_falls_back_for_invalid_schema() -> None:
    parsed = {"category": "стипендія", "priority": "urgent"}

    output = TicketClassifierService._validated_output(
        parsed,
        {"стипендія", "інше / первинна маршрутизація"},
        raw_response='{"category":"стипендія","priority":"urgent"}',
    )

    assert output.category == "інше / первинна маршрутизація"
    assert output.priority.value == "medium"
    assert output.confidence_source == "fallback"
    assert output.raw_response is not None
