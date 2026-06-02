# ruff: noqa: F403,F405
import sys

from .shared import *
from .models import DirectFactIntent, KnowledgeBaseEntry, KnowledgeMatch
from .normalization import normalize_text
from .direct_facts import (
    detect_direct_fact_intent,
    focus_direct_fact_chunks,
    is_email_intent,
    is_phone_intent,
    is_strict_contact_intent,
    select_direct_fact_chunks,
)
from .knowledge_base import KnowledgeBaseService
from .qwen import BaseQwenAssistantService
from .openai_compatible import AssistantService, OpenAICompatibleAssistantService
from .db_loader import load_published_knowledge_base


def _public_voice_assistant_module() -> Any:
    return sys.modules.get("app.services.voice_assistant", sys.modules[__name__])
class VoiceAssistantService:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBaseService()

    @staticmethod
    def _get_llm(for_phone: bool) -> AssistantService:
        public_api = _public_voice_assistant_module()
        service = (
            public_api.get_phone_qwen_assistant_service()
            if for_phone
            else public_api.get_base_qwen_assistant_service()
        )
        return cast(AssistantService, service)

    @staticmethod
    def _direct_phone_fact_answer(question: str, entry: KnowledgeBaseEntry) -> str:
        intent = detect_direct_fact_intent(question)
        if intent is None:
            return ""

        clean_text = BaseQwenAssistantService._clean_answer(entry.answer, trim_incomplete=False)
        relevant_chunks = focus_direct_fact_chunks(clean_text, intent)
        if not relevant_chunks:
            return ""

        answer = normalize_text(" ".join(relevant_chunks))
        if len(answer) > 420:
            return ""
        if answer and answer[-1] not in ".!?…":
            answer = f"{answer}."
        return answer

    @staticmethod
    def _missing_direct_contact_answer(intent: DirectFactIntent) -> str:
        if is_phone_intent(intent):
            return "У наданій офіційній інформації телефон не вказано."
        if is_email_intent(intent):
            return "У наданій офіційній інформації електронну пошту не вказано."
        return ""

    async def answer(
        self,
        question_text: str,
        *,
        for_phone: bool = False,
        db: AsyncSession | None = None,
    ) -> VoiceAssistantResponse:
        question = normalize_text(question_text)
        knowledge_base: KnowledgeBaseService | None = None
        if db is not None:
            try:
                knowledge_base = await load_published_knowledge_base(db)
            except Exception:
                logger.exception("Failed to load published knowledge base from database.")
        return await asyncio.to_thread(
            self._answer_sync,
            question,
            for_phone=for_phone,
            knowledge_base=knowledge_base,
        )

    def _answer_sync(
        self,
        question: str,
        *,
        for_phone: bool = False,
        knowledge_base: KnowledgeBaseService | None = None,
    ) -> VoiceAssistantResponse:
        active_knowledge_base = knowledge_base or self.knowledge_base
        direct_matches = active_knowledge_base.search(question)
        matches = direct_matches
        guided_retrieval_used = False
        llm_unavailable = False
        llm: AssistantService | None = None
        llm_enabled = settings.voice_assistant_use_llm and (
            settings.voice_assistant_phone_use_llm if for_phone else True
        )
        guided_retrieval_enabled = (
            settings.voice_assistant_phone_ai_guided_retrieval
            if for_phone
            else settings.voice_assistant_ai_guided_retrieval
        )

        if llm_enabled and guided_retrieval_enabled:
            try:
                llm = self._get_llm(for_phone)
                search_plan = llm.plan_search_queries(question)
                guided_matches = self._search_with_guided_queries(
                    question,
                    search_plan.queries,
                    active_knowledge_base,
                )
                if self._should_accept_guided_matches(
                    question,
                    direct_matches,
                    guided_matches,
                    active_knowledge_base,
                ):
                    matches = guided_matches
                    guided_retrieval_used = True
            except Exception:
                logger.exception("Voice assistant guided retrieval failed.")
                llm_unavailable = True

        reliable_match = self._has_reliable_match(matches)
        soft_match = self._has_soft_match(matches)
        direct_fact_soft_match = (
            for_phone
            and soft_match
            and bool(matches)
            and self._has_requested_direct_fact(question, matches[0].entry)
        )
        if not guided_retrieval_used and self._has_ambiguous_soft_match(direct_matches, question=question):
            return self._fallback_response(question)
        if not reliable_match and not ((llm_enabled and soft_match) or direct_fact_soft_match):
            return self._fallback_response(question)

        best_score = matches[0].score if matches else 0
        context_matches = self._filter_context_matches(
            matches,
            reliable_match=reliable_match,
        )
        if for_phone:
            context_matches = context_matches[: settings.voice_assistant_phone_max_context_items]
            if context_matches:
                direct_fact_intent = detect_direct_fact_intent(question)
                for context_match in context_matches:
                    direct_fact_answer = self._direct_phone_fact_answer(question, context_match.entry)
                    if direct_fact_answer:
                        source = "llm_guided" if guided_retrieval_used else "knowledge_base"
                        return VoiceAssistantResponse(
                            question_text=question,
                            answer_text=direct_fact_answer,
                            confidence=context_match.score,
                            source=source,
                            sources=self._sources([context_match]),
                            can_create_ticket=False,
                            used_llm=guided_retrieval_used,
                            model_name=llm.model_name if guided_retrieval_used and llm is not None else None,
                        )
                if direct_fact_intent is not None and is_strict_contact_intent(direct_fact_intent):
                    missing_answer = self._missing_direct_contact_answer(direct_fact_intent)
                    if missing_answer:
                        source = "llm_guided" if guided_retrieval_used else "knowledge_base"
                        return VoiceAssistantResponse(
                            question_text=question,
                            answer_text=missing_answer,
                            confidence=best_score,
                            source=source,
                            sources=self._sources(context_matches),
                            can_create_ticket=False,
                            used_llm=guided_retrieval_used,
                            model_name=llm.model_name if guided_retrieval_used and llm is not None else None,
                        )
        used_llm = False
        model_name: str | None = None
        answer_text = ""

        if llm_enabled and not llm_unavailable:
            try:
                assistant = llm or self._get_llm(for_phone)
                llm = assistant
                generation_kwargs: dict[str, Any] = {
                    "allow_related_sources": not reliable_match,
                }
                if for_phone:
                    if settings.voice_assistant_phone_max_new_tokens > 0:
                        generation_kwargs["max_new_tokens"] = (
                            settings.voice_assistant_phone_max_new_tokens
                        )
                    generation_kwargs["for_phone"] = True
                answer_text = assistant.generate_answer(question, context_matches, **generation_kwargs)
                used_llm = bool(answer_text)
                model_name = assistant.model_name if used_llm else None
            except Exception:
                logger.exception("Voice assistant LLM generation failed.")
                if context_matches:
                    answer_text = self._extractive_answer(context_matches[0].entry)
                elif llm_enabled:
                    return self._llm_unavailable_response(question, context_matches)

        if not answer_text:
            if context_matches:
                answer_text = self._extractive_answer(context_matches[0].entry)
            elif llm_enabled:
                return self._llm_unavailable_response(question, context_matches)

        if used_llm and guided_retrieval_used:
            source = "llm_guided"
        elif used_llm:
            source = "llm"
        else:
            source = "knowledge_base"

        return VoiceAssistantResponse(
            question_text=question,
            answer_text=answer_text,
            confidence=best_score,
            source=source,
            sources=self._sources(context_matches),
            can_create_ticket=False,
            used_llm=used_llm,
            model_name=model_name,
        )

    def _search_with_guided_queries(
        self,
        question: str,
        queries: tuple[str, ...],
        knowledge_base: KnowledgeBaseService,
    ) -> list[KnowledgeMatch]:
        groups = [
            knowledge_base.search(query, limit=settings.voice_assistant_search_candidates)
            for query in (*queries, question)
        ]
        return self._merge_matches(groups, limit=settings.voice_assistant_max_context_items)

    def _should_accept_guided_matches(
        self,
        question: str,
        direct_matches: list[KnowledgeMatch],
        guided_matches: list[KnowledgeMatch],
        knowledge_base: KnowledgeBaseService,
    ) -> bool:
        if not guided_matches:
            return False
        if not direct_matches:
            return True

        direct_top = direct_matches[0]
        guided_top = guided_matches[0]
        direct_score = direct_top.score
        guided_score = guided_top.score

        if guided_top.entry.id == direct_top.entry.id:
            return guided_score >= direct_score

        guided_original_score = knowledge_base.score_entry_for_question(
            question,
            guided_top.entry,
        )

        if direct_score >= settings.voice_assistant_min_confidence:
            return guided_original_score >= direct_score + 0.08

        if direct_score < settings.voice_assistant_soft_min_confidence:
            return guided_score >= settings.voice_assistant_soft_min_confidence

        if (
            direct_score < settings.voice_assistant_min_confidence
            and guided_score >= settings.voice_assistant_soft_min_confidence
            and guided_score >= direct_score + 0.2
        ):
            return True

        return guided_original_score >= direct_score + 0.05

    @staticmethod
    def _merge_matches(
        groups: list[list[KnowledgeMatch]],
        *,
        limit: int,
    ) -> list[KnowledgeMatch]:
        best_by_entry: dict[str, KnowledgeMatch] = {}
        for group in groups:
            for match in group:
                existing = best_by_entry.get(match.entry.id)
                if existing is None or match.score > existing.score:
                    best_by_entry[match.entry.id] = match

        matches = list(best_by_entry.values())
        matches.sort(key=lambda item: item.score, reverse=True)
        return matches[:limit]

    @staticmethod
    def _best_score(matches: list[KnowledgeMatch]) -> float:
        return matches[0].score if matches else 0.0

    @staticmethod
    def _filter_context_matches(
        matches: list[KnowledgeMatch],
        *,
        reliable_match: bool,
    ) -> list[KnowledgeMatch]:
        if not matches:
            return []

        top_score = matches[0].score
        absolute_floor = (
            settings.voice_assistant_min_confidence
            if reliable_match
            else settings.voice_assistant_soft_min_confidence
        )
        min_score = max(
            absolute_floor,
            top_score * settings.voice_assistant_context_score_ratio,
        )
        filtered = [match for match in matches if match.score >= min_score]
        return filtered[: settings.voice_assistant_max_context_items] or matches[:1]

    @staticmethod
    def _has_reliable_match(matches: list[KnowledgeMatch]) -> bool:
        if not matches:
            return False
        best_score = matches[0].score
        return best_score >= settings.voice_assistant_min_confidence

    @staticmethod
    def _has_soft_match(matches: list[KnowledgeMatch]) -> bool:
        if not matches:
            return False
        best_score = matches[0].score
        return best_score >= settings.voice_assistant_soft_min_confidence

    @staticmethod
    def _has_requested_direct_fact(question: str, entry: KnowledgeBaseEntry) -> bool:
        intent = detect_direct_fact_intent(question)
        if intent is None:
            return False

        clean_text = BaseQwenAssistantService._clean_answer(entry.answer, trim_incomplete=False)
        return bool(select_direct_fact_chunks(clean_text, intent))

    @classmethod
    def _has_ambiguous_soft_match(
        cls,
        matches: list[KnowledgeMatch],
        *,
        question: str = "",
    ) -> bool:
        if len(matches) < 2:
            return False
        best_score = matches[0].score
        second_score = matches[1].score
        if best_score >= settings.voice_assistant_min_confidence:
            return False
        if question and cls._has_requested_direct_fact(question, matches[0].entry):
            second_has_requested_fact = cls._has_requested_direct_fact(question, matches[1].entry)
            if not second_has_requested_fact or best_score >= second_score + 0.015:
                return False
        return second_score >= settings.voice_assistant_soft_min_confidence and (
            best_score - second_score <= 0.06
            or second_score >= best_score * 0.88
        )

    @staticmethod
    def _extractive_answer(entry: KnowledgeBaseEntry) -> str:
        return BaseQwenAssistantService._clean_answer(entry.answer)

    @staticmethod
    def _sources(matches: list[KnowledgeMatch]) -> list[VoiceAssistantSource]:
        return [
            VoiceAssistantSource(
                title=match.entry.title,
                url=match.entry.source_url,
                score=match.score,
            )
            for match in matches
        ]

    def _fallback_response(self, question: str) -> VoiceAssistantResponse:
        return VoiceAssistantResponse(
            question_text=question,
            answer_text=(
                "Я не знайшов точну відповідь в офіційній базі знань КПІ. "
                "Спробуйте переформулювати питання або додати більше деталей."
            ),
            confidence=0,
            source="fallback",
            sources=[],
            can_create_ticket=False,
            used_llm=False,
            model_name=None,
        )

    def _llm_unavailable_response(
        self,
        question: str,
        matches: list[KnowledgeMatch],
    ) -> VoiceAssistantResponse:
        return VoiceAssistantResponse(
            question_text=question,
            answer_text=(
                "ШІ-модель зараз не змогла сформувати автоматичну відповідь. "
                "Спробуйте повторити питання трохи пізніше або уточнити формулювання."
            ),
            confidence=matches[0].score if matches else 0,
            source="llm_unavailable",
            sources=self._sources(matches),
            can_create_ticket=False,
            used_llm=False,
            model_name=None,
        )


@lru_cache
def get_knowledge_base_service() -> KnowledgeBaseService:
    return KnowledgeBaseService()


@lru_cache
def get_base_qwen_assistant_service() -> AssistantService:
    if settings.voice_assistant_inference_engine == "openai_compatible":
        return OpenAICompatibleAssistantService(
            model_name=settings.voice_assistant_model,
            base_url=settings.voice_assistant_openai_base_url,
            api_key=settings.voice_assistant_openai_api_key,
            timeout_seconds=settings.voice_assistant_openai_timeout_seconds,
            temperature=settings.voice_assistant_openai_temperature,
        )
    return BaseQwenAssistantService()


@lru_cache
def get_phone_qwen_assistant_service() -> AssistantService:
    if settings.voice_assistant_phone_inference_engine == "openai_compatible":
        return OpenAICompatibleAssistantService(
            model_name=settings.voice_assistant_phone_model,
            base_url=settings.voice_assistant_phone_openai_base_url,
            api_key=settings.voice_assistant_phone_openai_api_key,
            timeout_seconds=settings.voice_assistant_phone_openai_timeout_seconds,
            temperature=settings.voice_assistant_phone_openai_temperature,
        )
    return BaseQwenAssistantService(
        model_name=settings.voice_assistant_phone_model,
        reuse_classifier_model=settings.voice_assistant_phone_reuse_classifier_model,
        quantization=settings.voice_assistant_phone_quantization,
    )


@lru_cache
def get_voice_assistant_service() -> VoiceAssistantService:
    return VoiceAssistantService()
