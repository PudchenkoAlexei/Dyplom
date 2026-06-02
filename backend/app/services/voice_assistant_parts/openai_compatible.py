# ruff: noqa: F403,F405
from .shared import *
from .models import GuidedSearchPlan, KnowledgeMatch
from .qwen import BaseQwenAssistantService
class OpenAICompatibleAssistantService:
    def __init__(
        self,
        *,
        model_name: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        temperature: float,
    ) -> None:
        self.model_name = f"{model_name} via OpenAI-compatible"
        self._model_id = model_name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature

    def _generate_from_messages(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError("httpx is required for OpenAI-compatible inference.") from exc

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model_id,
            "messages": messages,
            "max_tokens": max_new_tokens,
            "temperature": self._temperature,
            "stream": False,
        }

        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI-compatible assistant inference failed.") from exc

        if not isinstance(content, str):
            raise RuntimeError("OpenAI-compatible assistant returned non-text content.")
        return content

    def plan_search_queries(self, question: str) -> GuidedSearchPlan:
        messages = BaseQwenAssistantService._build_search_messages(question)
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=160,
        )
        queries = BaseQwenAssistantService._parse_search_queries(raw, fallback_query=question)
        return GuidedSearchPlan(queries=queries, raw_response=raw)

    def generate_answer(
        self,
        question: str,
        matches: list[KnowledgeMatch],
        *,
        allow_related_sources: bool = False,
        max_new_tokens: int | None = None,
        for_phone: bool = False,
    ) -> str:
        if for_phone:
            messages = BaseQwenAssistantService._build_phone_answer_messages(question, matches)
        else:
            messages = BaseQwenAssistantService._build_answer_messages(
                question,
                matches,
                allow_related_sources=allow_related_sources,
            )
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=max_new_tokens or settings.voice_assistant_max_new_tokens,
        )
        return BaseQwenAssistantService._clean_answer(raw)


AssistantService = BaseQwenAssistantService | OpenAICompatibleAssistantService
