# ruff: noqa: F403,F405
from .shared import *
from .models import DirectFactIntent, GenerativeModel, GuidedSearchPlan, KnowledgeMatch
from .normalization import normalize_for_search, normalize_text
from .direct_facts import detect_direct_fact_intent, focus_direct_fact_chunks
from .search_utils import dedupe_repeated_sentences
class BaseQwenAssistantService:
    def __init__(
        self,
        *,
        model_name: str | None = None,
        reuse_classifier_model: bool | None = None,
        quantization: str | None = None,
    ) -> None:
        target_model_name = model_name or settings.voice_assistant_model
        should_reuse_classifier = (
            settings.voice_assistant_reuse_classifier_model
            if reuse_classifier_model is None
            else reuse_classifier_model
        )
        target_quantization = quantization or settings.voice_assistant_quantization
        self.uses_classifier_model = False
        if should_reuse_classifier:
            try:
                classifier = get_classifier_service()
                self.torch = classifier.torch
                self.tokenizer = classifier.tokenizer
                self.model: GenerativeModel = cast(GenerativeModel, classifier.model)
                self.model_name = f"{settings.llm_base_model} без LoRA"
                self.uses_classifier_model = True
                self.model.eval()
                return
            except RuntimeError:
                logger.exception("Could not reuse classifier model for voice assistant.")

        try:
            import torch

            install_sklearn_stub()
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("transformers and torch are required for assistant inference.") from exc

        self.torch = torch
        self.model_name = target_model_name
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                target_model_name,
                trust_remote_code=True,
            )
            model_kwargs = self._build_model_load_kwargs(
                torch,
                quantization=target_quantization,
            )
            self.model = cast(
                GenerativeModel,
                AutoModelForCausalLM.from_pretrained(
                    target_model_name,
                    trust_remote_code=True,
                    **model_kwargs,
                ),
            )
        except Exception as exc:
            raise RuntimeError("Could not load assistant generation model.") from exc
        if target_quantization != "none":
            self.model_name = f"{target_model_name} ({target_quantization})"
        self.model.eval()

    @staticmethod
    def _build_model_load_kwargs(torch_module: Any, *, quantization: str) -> dict[str, Any]:
        if quantization == "none":
            return {
                "device_map": settings.llm_device,
                "torch_dtype": "auto",
            }

        if not torch_module.cuda.is_available():
            raise RuntimeError("Quantized assistant inference requires CUDA/GPU.")

        try:
            from transformers import BitsAndBytesConfig
        except ImportError as exc:
            raise RuntimeError("bitsandbytes is required for quantized assistant inference.") from exc

        if quantization == "8bit":
            return {
                "device_map": settings.llm_device,
                "quantization_config": BitsAndBytesConfig(load_in_8bit=True),
            }
        if quantization == "4bit":
            return {
                "device_map": settings.llm_device,
                "quantization_config": BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch_module.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                ),
            }

        raise RuntimeError(f"Unsupported assistant quantization mode: {quantization}")

    def _generate_from_messages(
        self,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int,
    ) -> str:
        model_input = apply_classifier_chat_template(
            self.tokenizer,
            messages,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(model_input, return_tensors="pt")
        model_device = getattr(self.model, "device", None)
        if model_device is not None:
            inputs = inputs.to(model_device)

        adapter_context: AbstractContextManager[Any] = nullcontext()
        disable_adapter = getattr(self.model, "disable_adapter", None)
        if self.uses_classifier_model and callable(disable_adapter):
            adapter_context = cast(
                Callable[[], AbstractContextManager[Any]],
                disable_adapter,
            )()
        with self.torch.no_grad(), adapter_context:
            generated = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated_ids = generated[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(generated_ids, skip_special_tokens=True)

    def plan_search_queries(self, question: str) -> GuidedSearchPlan:
        messages = self._build_search_messages(question)
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=160,
        )
        queries = self._parse_search_queries(raw, fallback_query=question)
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
            messages = self._build_phone_answer_messages(question, matches)
        else:
            messages = self._build_answer_messages(
                question,
                matches,
                allow_related_sources=allow_related_sources,
            )
        raw = self._generate_from_messages(
            messages,
            max_new_tokens=max_new_tokens or settings.voice_assistant_max_new_tokens,
        )
        return self._clean_answer(raw)

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any]:
        stripped = raw.strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise RuntimeError(f"Model did not return JSON: {raw}")
        parsed = json.loads(stripped[start : end + 1])
        if not isinstance(parsed, dict):
            raise RuntimeError(f"Model returned non-object JSON: {raw}")
        return parsed

    @staticmethod
    def _parse_search_queries(raw: str, *, fallback_query: str) -> tuple[str, ...]:
        try:
            parsed = BaseQwenAssistantService._extract_json_object(raw)
        except (RuntimeError, json.JSONDecodeError):
            parsed = {}

        raw_queries = parsed.get("queries")
        if isinstance(raw_queries, str):
            query_values = [raw_queries]
        elif isinstance(raw_queries, list):
            query_values = [item for item in raw_queries if isinstance(item, str)]
        else:
            query_values = []

        normalized_queries: list[str] = []
        seen: set[str] = set()
        for query in [*query_values, fallback_query]:
            normalized = normalize_text(query)[:160]
            dedupe_key = normalize_for_search(normalized)
            if len(normalized) < 3 or dedupe_key in seen:
                continue
            normalized_queries.append(normalized)
            seen.add(dedupe_key)
            if len(normalized_queries) >= settings.voice_assistant_search_query_count:
                break

        return tuple(normalized_queries or [normalize_text(fallback_query)])

    @staticmethod
    def _build_search_messages(question: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "Ти планувальник пошуку для голосової довідкової КПІ. "
                    "Твоя єдина дія - викликати інструмент search_kpi_faq через JSON. "
                    "Не відповідай користувачу напряму, не міркуй уголос, не генеруй <think>. "
                    "Сформуй до кількох коротких українських пошукових запитів, які допоможуть "
                    "знайти релевантні FAQ-джерела навіть після помилок розпізнавання мовлення."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання користувача: {question}\n\n"
                    "Поверни тільки JSON без Markdown у форматі: "
                    '{"tool":"search_kpi_faq","queries":["запит 1","запит 2"]}. '
                    "Запити мають бути короткими, без URL і без вигаданих фактів."
                ),
            },
        ]

    @staticmethod
    def _build_answer_messages(
        question: str,
        matches: list[KnowledgeMatch],
        *,
        allow_related_sources: bool,
    ) -> list[dict[str, str]]:
        context = "\n\n".join(
            (
                f"Тема джерела {index}: {match.entry.title}\n"
                f"Довідкова інформація для відповіді: {match.entry.answer}"
            )
            for index, match in enumerate(matches, start=1)
        )
        freedom_rule = (
            "Джерела можуть бути лише частково релевантними. Якщо збіг приблизний, прямо скажи, "
            "що інформація схожа або неповна, і дай обережну відповідь тільки в межах доступних джерел. "
            "Можеш узагальнювати й пояснювати за аналогією з релевантними фрагментами, але не називай "
            "точні дедлайни, суми, телефони чи обов'язкові процедури, якщо їх немає в джерелах."
            if allow_related_sources
            else (
                "Відповідай на основі джерел. Можеш природно перефразовувати, поєднувати релевантні "
                "фрагменти й пояснювати їх простішими словами. Якщо джерела не містять певної деталі, "
                "чесно скажи, що в наданій інформації цього немає."
            )
        )
        return [
            {
                "role": "system",
                "content": (
                    "Ти голосовий консультант довідкової служби КПІ. "
                    "Відповідай українською, природно для усного мовлення і тільки з наданих джерел. "
                    "Одразу починай із відповіді; не повторюй питання, FAQ, заголовки, URL, джерела, "
                    "заявку чи оператора. Не генеруй <think> і не пояснюй хід думок. "
                    "Пиши щільно: не обмежуй кількість речень, але кожне речення має додавати "
                    "новий факт, документ, умову, адресу або дію. Прибирай вступи, оцінки й загальні "
                    "фрази без нової інформації. "
                    "Не скорочуй пакети документів: якщо є перелік, двокрапка або пункти через крапку "
                    "з комою, назви кожен пункт. Якщо спільне слово стосується кількох документів, "
                    "повтори його для кожного документа. "
                    "Пиши літературною українською, виправляй русизми, кальки, невдалі відмінки "
                    "й неприродні формулювання. Використовуй однотипні граматичні форми в переліках. "
                    f"{freedom_rule} "
                    "Не вигадуй офіційні правила, контакти, дедлайни, суми або гарантії поза джерелами. "
                    "Не пропонуй створювати заявку, звернення або передавати питання оператору."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання користувача: {question}\n\n"
                    f"Доступні джерела:\n{context}\n\n"
                    "Сформуй одну зв'язну змістовну відповідь для озвучення голосом. "
                    "Почни з конкретної відповіді, без вступної фрази й без загальних міркувань. "
                    "Без Markdown, URL, списків, службових пояснень і згадок про створення заявки."
                ),
            },
        ]

    @staticmethod
    def _focus_facts_for_phone(text: str, intent: DirectFactIntent | None) -> str:
        clean_text = BaseQwenAssistantService._clean_answer(text, trim_incomplete=False)
        if intent is None:
            return clean_text

        relevant_chunks = focus_direct_fact_chunks(clean_text, intent)
        if not relevant_chunks:
            return clean_text
        return normalize_text(" ".join(relevant_chunks[:5]))

    @staticmethod
    def _build_phone_answer_messages(
        question: str,
        matches: list[KnowledgeMatch],
    ) -> list[dict[str, str]]:
        direct_fact_intent = detect_direct_fact_intent(question)
        context = "\n\n".join(
            f"Тема {index}: {match.entry.title}\n"
            f"Факти {index}: {BaseQwenAssistantService._focus_facts_for_phone(match.entry.answer, direct_fact_intent)}"
            for index, match in enumerate(matches, start=1)
        )
        direct_fact_instruction = ""
        if direct_fact_intent is not None:
            direct_fact_instruction = (
                f"Користувач просить конкретний факт: {direct_fact_intent.name}. "
                "Відповідай тільки цим фактом і найближчими необхідними уточненнями. "
                "Не додавай сусідні речення про оголошення, підписку, інші контакти, інші дії "
                "або загальний опис теми, якщо вони не відповідають на запитаний факт.\n\n"
            )
        definition_instruction = ""
        if re.search(r"\b(що таке|що означає|поясни|визначення)\b", normalize_for_search(question)):
            primary_topic = matches[0].entry.title if matches else "поняття"
            definition_instruction = (
                "Користувач просить пояснити поняття. Спочатку дай коротке визначення простими словами. "
                f"Орієнтуйся на тему джерела: '{primary_topic}', а не на можливу помилку розпізнавання "
                "в самому питанні. Якщо назва теми стисла або злита, розгорни її природною українською. "
                "Потім додай головні обмеження або умови з фактів.\n\n"
            )
        core_rules = (
            "Відповідай як живий телефонний консультант: спочатку пряма відповідь, потім потрібні деталі. "
            "Не цитуй джерело механічно; перефразовуй простими словами, але не додавай фактів, яких немає "
            "у наданих даних. Якщо користувач питає про документи, назви весь пакет документів з фактів. "
            "Якщо у фактах різні групи людей, не змішуй їхні умови. Не повторюй питання, не згадуй FAQ, "
            "джерела, URL, Markdown, заявку чи оператора. Не повторюй однакові речення та не замінюй "
            "офіційні назви вигаданими підрозділами. Звертайся нейтрально або на 'ви', ніколи не переходь "
            "на 'ти' і не додавай фрази на кшталт 'можу пояснити'. Говори грамотною природною українською "
            "для телефону."
        )
        return [
            {
                "role": "system",
                "content": (
                    "Ти телефонний консультант КПІ. Відповідай українською і тільки за наданими фактами. "
                    f"{core_rules}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Питання: {question}\n\n"
                    f"{context}\n\n"
                    f"{direct_fact_instruction}"
                    f"{definition_instruction}"
                    "Сформуй одну зв'язну відповідь для телефонного дзвінка. "
                    "Без Markdown, маркованих списків і службових пояснень."
                ),
            },
        ]

    @staticmethod
    def _clean_answer(raw: str, *, trim_incomplete: bool = True) -> str:
        answer = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        if "</think>" in answer:
            answer = answer.split("</think>", 1)[1].strip()
        answer = answer.strip("` \n\r\t")
        answer = re.sub(r"\*\*(.*?)\*\*", r"\1", answer)
        answer = re.sub(r"\s*(?:[-–—]\s*)?https?://\S+", "", answer)
        answer = re.sub(r"\s+(?=[,.;:!?])", "", answer)
        answer = re.sub(r"\s*[-–—]\s*$", "", answer)
        for pattern in ANSWER_INTRO_DROP_PATTERNS:
            answer = pattern.sub("", answer, count=1)
        for pattern, replacement in ANSWER_TEXT_REPLACEMENTS:
            answer = pattern.sub(replacement, answer)
        for pattern in ANSWER_TRAILING_DROP_PATTERNS:
            answer = pattern.sub("", answer)
        if trim_incomplete and answer and answer[-1] not in ".!?…":
            complete_answer = re.sub(r"\s+[^.!?…]*$", "", answer)
            if len(complete_answer) >= 40:
                answer = complete_answer
        return dedupe_repeated_sentences(answer)
