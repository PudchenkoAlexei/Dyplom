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

    setattr(metrics, "roc_curve", roc_curve)
    setattr(sklearn, "metrics", metrics)
    sys.modules["sklearn"] = sklearn
    sys.modules["sklearn.metrics"] = metrics


class TicketClassifierService:
    SERVICE_CONFIDENCE_SCORE = 0.68
    FALLBACK_CONFIDENCE_SCORE = 0.35
    DEFAULT_CONFIDENCE = SERVICE_CONFIDENCE_SCORE
    FALLBACK_CONFIDENCE = FALLBACK_CONFIDENCE_SCORE
    FALLBACK_PRIORITY = Priority.medium
    FALLBACK_CATEGORY = "інше"
    CATEGORY_ALIASES = {"інше / первинна маршрутизація": FALLBACK_CATEGORY}

    @staticmethod
    def _build_model_load_kwargs(torch_module: Any, *, quantization: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "device_map": settings.llm_device,
            "trust_remote_code": True,
        }
        if quantization == "none":
            kwargs["torch_dtype"] = "auto"
            return kwargs

        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError(
                "bitsandbytes quantized classifier loading requires transformers."
            ) from exc

        compute_dtype = (
            torch_module.bfloat16
            if torch_module.cuda.is_available() and torch_module.cuda.is_bf16_supported()
            else torch_module.float16
        )
        if quantization == "4bit":
            kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=compute_dtype,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
            )
        elif quantization == "8bit":
            kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
        else:
            raise RuntimeError(f"Unsupported classifier quantization: {quantization}")
        return kwargs

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
            **self._build_model_load_kwargs(
                torch,
                quantization=settings.classifier_quantization,
            ),
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

    @staticmethod
    def _normalize_category_name(value: str) -> str:
        return " ".join(value.casefold().split())

    @classmethod
    def _match_allowed_category(cls, category: str, allowed_categories: set[str]) -> str | None:
        normalized = cls._normalize_category_name(category)
        normalized_allowed = {
            cls._normalize_category_name(allowed): allowed for allowed in allowed_categories
        }
        if normalized in normalized_allowed:
            return normalized_allowed[normalized]
        for alias, target in cls.CATEGORY_ALIASES.items():
            if normalized == cls._normalize_category_name(alias):
                return normalized_allowed.get(cls._normalize_category_name(target))

        category_without_description = category.split("(", 1)[0].strip(" \t\r\n-–—:;,.")
        normalized_without_description = cls._normalize_category_name(category_without_description)
        if normalized_without_description in normalized_allowed:
            return normalized_allowed[normalized_without_description]
        for alias, target in cls.CATEGORY_ALIASES.items():
            if normalized_without_description == cls._normalize_category_name(alias):
                return normalized_allowed.get(cls._normalize_category_name(target))
        return None

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

        matched_category = cls._match_allowed_category(output.category, allowed_categories)
        if matched_category:
            output.category = matched_category
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
