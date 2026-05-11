import importlib.machinery
import json
import sys
import types
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.models.enums import Priority, UserRole

settings = get_settings()


class ClassificationOutput(BaseModel):
    category: str = Field(min_length=2)
    priority: Priority
    confidence: float = Field(ge=0, le=1)


@dataclass(frozen=True)
class CatalogItem:
    name: str
    description: str | None = None


def install_sklearn_stub() -> None:
    """Keep transformers generation from importing optional sklearn on Windows."""

    if "sklearn" in sys.modules:
        return

    sklearn = types.ModuleType("sklearn")
    sklearn.__path__ = []
    sklearn.__spec__ = importlib.machinery.ModuleSpec("sklearn", loader=None, is_package=True)

    metrics = types.ModuleType("sklearn.metrics")
    metrics.__spec__ = importlib.machinery.ModuleSpec("sklearn.metrics", loader=None)

    def roc_curve(*_: object, **__: object) -> None:
        raise RuntimeError("roc_curve is unavailable in the lightweight classifier runtime.")

    metrics.roc_curve = roc_curve
    sklearn.metrics = metrics
    sys.modules["sklearn"] = sklearn
    sys.modules["sklearn.metrics"] = metrics


class TicketClassifierService:
    DEFAULT_CONFIDENCE = 0.68
    FALLBACK_CONFIDENCE = 0.35
    FALLBACK_CATEGORY = "інше / первинна маршрутизація"

    def __init__(self) -> None:
        adapter_path = Path(settings.lora_adapter_path)
        if not adapter_path.exists():
            raise RuntimeError(
                f"LoRA adapter not found at {adapter_path}. Train the model and set LORA_ADAPTER_PATH."
            )

        try:
            import torch
            from peft import PeftModel

            install_sklearn_stub()
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "transformers, peft and torch are required for classification inference."
            ) from exc

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(settings.llm_base_model, trust_remote_code=True)
        base_model = AutoModelForCausalLM.from_pretrained(
            settings.llm_base_model,
            device_map=settings.llm_device,
            torch_dtype="auto",
            trust_remote_code=True,
        )
        self.model = PeftModel.from_pretrained(base_model, str(adapter_path))
        self.model.eval()

    def classify(
        self,
        *,
        role: UserRole,
        text: str,
        categories: list[CatalogItem],
    ) -> ClassificationOutput:
        prompt = self._build_prompt(role=role, text=text, categories=categories)
        raw = self._generate(prompt)
        parsed = self._parse_json(raw)
        allowed_categories = {item.name for item in categories}
        return self._validated_output(parsed, allowed_categories)

    def _build_prompt(
        self,
        *,
        role: UserRole,
        text: str,
        categories: list[CatalogItem],
    ) -> str:
        def compact(value: str, max_chars: int = 320) -> str:
            cleaned = " ".join(value.split())
            if len(cleaned) <= max_chars:
                return cleaned
            return cleaned[:max_chars].rsplit(" ", 1)[0].strip()

        category_names = ", ".join(item.name for item in categories)
        ticket_text = compact(text, max_chars=320)
        return (
            "Класифікуй звернення до довідкової системи КПІ. "
            "Поверни тільки валідний JSON без Markdown з полями "
            "category, priority.\n"
            f"Доступні категорії: {category_names}\n"
            "Обирай категорію за відповідальним підрозділом, а не за випадковим словом у тексті.\n"
            "Поле category має точно збігатися з однією доступною категорією.\n"
            "Якщо в тексті згадано кілька тем, обирай категорію того підрозділу, "
            "який має виконати основну дію або вирішити блокування.\n"
            "Пріоритети: low, medium, high.\n"
            "low - довідкове питання без блокування; medium - стандартне робоче звернення; "
            "high - заблокована дія, втрата доступу, гроші, дедлайн, безпека або ризик відрахування.\n"
            "Не став medium за замовчуванням: якщо користувач лише питає де/як/коли без блокування - low; "
            "якщо дія вже не працює, є дедлайн, кошти, доступ, безпека або юридичний ризик - high.\n"
            f"Роль автора: {role.value}\n"
            f"Текст звернення: {ticket_text}\n"
        )

    def _generate(self, prompt: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "You are a strict JSON classifier for Ukrainian university helpdesk tickets.",
            },
            {"role": "user", "content": prompt},
        ]
        if hasattr(self.tokenizer, "apply_chat_template"):
            model_input = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            model_input = prompt

        inputs = self.tokenizer(model_input, return_tensors="pt").to(self.model.device)
        with self.torch.no_grad():
            generated = self.model.generate(
                **inputs,
                max_new_tokens=settings.classifier_max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated_ids = generated[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(generated_ids, skip_special_tokens=True)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        stripped = raw.strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise RuntimeError(f"Classifier did not return JSON: {raw}")
        return json.loads(stripped[start : end + 1])

    @classmethod
    def _validated_output(
        cls,
        parsed: dict[str, Any],
        allowed_categories: set[str],
    ) -> ClassificationOutput:
        # Confidence is not trusted when generated by the LLM; keep it as a conservative service-side score.
        try:
            output = ClassificationOutput.model_validate(
                {
                    **parsed,
                    "confidence": cls.DEFAULT_CONFIDENCE,
                }
            )
        except ValidationError as exc:
            raise RuntimeError(f"Classifier returned invalid schema: {exc}") from exc

        if output.category in allowed_categories:
            return output

        if cls.FALLBACK_CATEGORY not in allowed_categories:
            raise RuntimeError(
                f"Classifier returned category outside catalog and fallback category is unavailable: {output.category}"
            )
        return ClassificationOutput(
            category=cls.FALLBACK_CATEGORY,
            priority=output.priority,
            confidence=cls.FALLBACK_CONFIDENCE,
        )


@lru_cache
def get_classifier_service() -> TicketClassifierService:
    return TicketClassifierService()
