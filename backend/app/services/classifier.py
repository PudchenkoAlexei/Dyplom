import importlib.machinery
import json
import sys
import types
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.models.enums import Priority, UserRole
from app.services.classifier_prompt import (
    CatalogItem,
    apply_classifier_chat_template,
    build_classifier_messages,
    build_classifier_prompt,
)

settings = get_settings()


class ClassificationOutput(BaseModel):
    category: str = Field(min_length=2)
    priority: Priority
    confidence: float = Field(ge=0, le=1)
    confidence_source: str = "service_default"
    raw_response: str | None = None
    fallback_reason: str | None = None


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
    SERVICE_CONFIDENCE_SCORE = 0.68
    FALLBACK_CONFIDENCE_SCORE = 0.35
    DEFAULT_CONFIDENCE = SERVICE_CONFIDENCE_SCORE
    FALLBACK_CONFIDENCE = FALLBACK_CONFIDENCE_SCORE
    FALLBACK_PRIORITY = Priority.medium
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
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.llm_base_model, trust_remote_code=True
        )
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
        messages = build_classifier_messages(role=role, text=text, categories=categories)
        raw = self._generate(messages)
        allowed_categories = {item.name for item in categories}
        try:
            parsed = self._parse_json(raw)
        except (RuntimeError, json.JSONDecodeError) as exc:
            return self._fallback_output(
                allowed_categories,
                priority=self.FALLBACK_PRIORITY,
                raw_response=raw,
                reason=f"Classifier returned non-JSON output: {exc}",
            )
        return self._validated_output(parsed, allowed_categories, raw_response=raw)

    @staticmethod
    def _build_prompt(
        *,
        role: UserRole,
        text: str,
        categories: list[CatalogItem],
    ) -> str:
        return build_classifier_prompt(role=role, text=text, categories=categories)

    def _generate(self, messages: list[dict[str, str]]) -> str:
        model_input = apply_classifier_chat_template(
            self.tokenizer,
            messages,
            add_generation_prompt=True,
        )

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
        raw_response: str | None = None,
    ) -> ClassificationOutput:
        # Confidence is not generated by the classifier; it is a conservative service-side routing score.
        try:
            output = ClassificationOutput.model_validate(
                {
                    **parsed,
                    "confidence": cls.SERVICE_CONFIDENCE_SCORE,
                    "confidence_source": "service_default",
                    "raw_response": raw_response,
                }
            )
        except ValidationError as exc:
            return cls._fallback_output(
                allowed_categories,
                priority=cls.FALLBACK_PRIORITY,
                raw_response=raw_response,
                reason=f"Classifier returned invalid schema: {exc}",
            )

        if output.category in allowed_categories:
            return output

        return cls._fallback_output(
            allowed_categories,
            priority=output.priority,
            raw_response=raw_response,
            reason=f"Classifier returned category outside catalog: {output.category}",
        )

    @classmethod
    def _fallback_output(
        cls,
        allowed_categories: set[str],
        *,
        priority: Priority,
        raw_response: str | None,
        reason: str,
    ) -> ClassificationOutput:
        if cls.FALLBACK_CATEGORY not in allowed_categories:
            raise RuntimeError(
                "Classifier output could not be used and fallback category is unavailable."
            )
        return ClassificationOutput(
            category=cls.FALLBACK_CATEGORY,
            priority=priority,
            confidence=cls.FALLBACK_CONFIDENCE_SCORE,
            confidence_source="fallback",
            raw_response=raw_response,
            fallback_reason=reason,
        )


@lru_cache
def get_classifier_service() -> TicketClassifierService:
    return TicketClassifierService()
