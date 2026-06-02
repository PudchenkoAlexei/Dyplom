# ruff: noqa: F403,F405
from .shared import *
from .models import DirectFactIntent
from .normalization import normalize_for_search, normalize_text, stem_token
DIRECT_FACT_INTENTS = (
    DirectFactIntent(
        name="адресу або місце розташування",
        query_pattern=re.compile(
            r"\b(адрес\w*|де\s+(?:знаход\w*|розташован\w*)|локац\w*|місцезнаходжен\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=(
            "адрес",
            "знаход",
            "розташ",
            "локац",
            "місцезнаходжен",
            "корпус",
            "кабінет",
            "кімн",
            "аудитор",
            "поверх",
            "проспект",
            "вул",
            "вулиц",
        ),
    ),
    DirectFactIntent(
        name="телефон або номер для зв'язку",
        query_pattern=re.compile(
            r"\b(телефон\w*|номер\w*|подзвон\w*|зателефон\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=("телефон", "тел.", "номер", "дзвон", "зв'яз", "контакт"),
    ),
    DirectFactIntent(
        name="електронну пошту",
        query_pattern=re.compile(
            r"\b(email|e-mail|емейл\w*|пошт\w*|електронн\w+\s+адрес\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=("email", "e-mail", "пошта", "електронн", "@"),
    ),
    DirectFactIntent(
        name="час, дату, графік або дедлайн",
        query_pattern=re.compile(
            r"\b(о\s+котрій|час\w*|графік\w*|розклад\w*|дата\w*|дедлайн\w*|термін\w*|початок\w*|"
            r"до\s+якого\s+(?:числа|терміну)|коли\s+(?:почина\w*|закінчу\w*|відбуд\w*|буде))\b",
            re.IGNORECASE,
        ),
        fact_keywords=("час", "графік", "розклад", "дата", "дедлайн", "термін", "початок", "до "),
    ),
    DirectFactIntent(
        name="вартість, оплату або суму",
        query_pattern=re.compile(
            r"\b(варт\w*|скільки\s+кошту\w*|оплат\w*|ціна\w*|сума\w*|рахунок\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=("варт", "кошту", "оплат", "ціна", "сума", "рахунок", "квитанц"),
    ),
    DirectFactIntent(
        name="пакет документів або перелік вимог",
        query_pattern=re.compile(
            r"\b(документ\w*|пакет\w*|перелік\w*|що\s+потрібн\w*|які\s+потрібн\w*)\b",
            re.IGNORECASE,
        ),
        fact_keywords=(
            "документ",
            "пакет",
            "перелік",
            "заява",
            "копія",
            "оригінал",
            "квитанц",
            "згода",
            "довідка",
            "паспорт",
            "потріб",
            "надати",
            "подати",
        ),
    ),
)

FACT_FIELD_BOUNDARY_RE = re.compile(
    r"\s+(?=("
    r"адрес[а-яіїєґ'’\s-]{0,80}:|"
    r"телефон[а-яіїєґ'’\s-]{0,60}:|"
    r"тел\.\s*:?|"
    r"email\s*:|"
    r"e-mail\s*:|"
    r"електронн[а-яіїєґ'’\s-]{0,60}пошт[а-яіїєґ'’\s-]{0,20}:|"
    r"пошт[а-яіїєґ'’\s-]{0,40}:|"
    r"графік[а-яіїєґ'’\s-]{0,60}:|"
    r"режим\s+роботи\s*:|"
    r"розклад[а-яіїєґ'’\s-]{0,60}:|"
    r"дата[а-яіїєґ'’\s-]{0,40}:|"
    r"дедлайн[а-яіїєґ'’\s-]{0,40}:|"
    r"кінцевий\s+термін[а-яіїєґ'’\s-]{0,40}:|"
    r"термін[а-яіїєґ'’\s-]{0,40}:|"
    r"вартість[а-яіїєґ'’\s-]{0,40}:|"
    r"ціна[а-яіїєґ'’\s-]{0,40}:|"
    r"сума[а-яіїєґ'’\s-]{0,40}:|"
    r"початок\s+[а-яіїєґ'’]+"
    r"))",
    re.IGNORECASE,
)
PHONE_FIELD_LABEL_RE = re.compile(
    r"\b(?:тел\.?|телефони?|номер(?:и)?(?:\s+телефон(?:у|а|ів))?|"
    r"контактн[а-яіїєґ'’\s-]{0,40}телефон[а-яіїєґ'’]*)\s*:?\s*",
    re.IGNORECASE,
)
PHONE_NUMBER_RE = re.compile(
    r"(?:"
    r"\+?380[\s)]*\d{2}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}|"
    r"\(?\d{2,5}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}|"
    r"\d{3}[-\s]\d{2}[-\s]\d{2}"
    r")",
    re.IGNORECASE,
)
EMAIL_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CONTACT_TAIL_RE = re.compile(
    r"\s*,?\s+\b(?:тел\.?|телефони?|телефон[а-яіїєґ'’]*|номер[а-яіїєґ'’]*|"
    r"email|e-mail|пошт[а-яіїєґ'’]*|сайт[а-яіїєґ'’]*)\b.*$",
    re.IGNORECASE,
)
PHONE_CONTEXT_PREFIX_RE = re.compile(
    r"\b(?:не\s+існує|немає|не\s+зазначено|не\s+вказано|не\s+передбачено|є\s+довідков)",
    re.IGNORECASE,
)
SENTENCE_ABBREVIATION_DOT = "\uE000"
SENTENCE_ABBREVIATION_RE = re.compile(
    r"\b(?:"
    r"\u0430\u0443\u0434|"
    r"\u0431\u0443\u0434|"
    r"\u0432\u0443\u043b|"
    r"\u0456\u043c|"
    r"\u043a\u0430\u0431|"
    r"\u043a\u0456\u043c|"
    r"\u043a\u043e\u0440\u043f|"
    r"\u043c|"
    r"\u043f\u0440|"
    r"\u0440|"
    r"\u0441\u0442|"
    r"\u0442\u0435\u043b"
    r")\.",
    re.IGNORECASE,
)


def _protect_sentence_abbreviations(text: str) -> str:
    return SENTENCE_ABBREVIATION_RE.sub(
        lambda match: match.group(0)[:-1] + SENTENCE_ABBREVIATION_DOT,
        text,
    )


def _restore_sentence_abbreviations(text: str) -> str:
    return text.replace(SENTENCE_ABBREVIATION_DOT, ".")


def detect_direct_fact_intent(question: str) -> DirectFactIntent | None:
    normalized_question = normalize_for_search(question)
    for intent in DIRECT_FACT_INTENTS:
        if intent.query_pattern.search(normalized_question):
            return intent
    return None


def split_fact_chunks(text: str) -> list[str]:
    with_field_boundaries = FACT_FIELD_BOUNDARY_RE.sub("\n", text)
    protected_text = _protect_sentence_abbreviations(with_field_boundaries)
    with_sentence_boundaries = re.sub(r"(?<=[.!?…])\s+", "\n", protected_text)
    with_sentence_boundaries = _restore_sentence_abbreviations(with_sentence_boundaries)
    chunks = [
        normalize_text(chunk.strip(" \t\r\n;"))
        for chunk in with_sentence_boundaries.splitlines()
    ]
    return [chunk for chunk in chunks if chunk]


def has_fact_keyword(normalized_chunk: str, keyword: str) -> bool:
    normalized_keyword = normalize_for_search(keyword).strip()
    if not normalized_keyword:
        return False
    if len(normalized_keyword) <= 3 and normalized_keyword.isalpha():
        return bool(
            re.search(
                rf"(?<![0-9a-zа-щьюяґєії']){re.escape(normalized_keyword)}(?![0-9a-zа-щьюяґєії'])",
                normalized_chunk,
                re.IGNORECASE,
            )
        )
    return normalized_keyword in normalized_chunk


def is_informative_direct_fact_chunk(chunk: str, intent: DirectFactIntent) -> bool:
    normalized_chunk = normalize_for_search(chunk)
    if not any(has_fact_keyword(normalized_chunk, keyword) for keyword in intent.fact_keywords):
        return False
    if re.search(r"\b(?:за\s+адресою|за\s+посиланням|на\s+сайті)\s*\.?$", normalized_chunk):
        return False
    if re.search(r"\bпідписатися\s+на\s*,", normalized_chunk):
        return False
    return True


def select_direct_fact_chunks(text: str, intent: DirectFactIntent) -> list[str]:
    return [
        chunk
        for chunk in split_fact_chunks(text)
        if is_informative_direct_fact_chunk(chunk, intent)
    ]


def select_direct_fact_chunks_with_context(text: str, intent: DirectFactIntent) -> list[str]:
    chunks = split_fact_chunks(text)
    selected_indexes = [
        index
        for index, chunk in enumerate(chunks)
        if is_informative_direct_fact_chunk(chunk, intent)
    ]
    selected_index_set = set(selected_indexes)
    result: list[str] = []

    for index in selected_indexes:
        context_chunks: list[str] = []
        previous_index = index - 1
        while previous_index >= 0 and previous_index not in selected_index_set and len(context_chunks) < 3:
            previous_chunk = chunks[previous_index]
            if len(previous_chunk) > 220 or not CONTEXTUAL_CAVEAT_RE.search(previous_chunk):
                break
            context_chunks.append(previous_chunk)
            previous_index -= 1
        result.extend(reversed(context_chunks))
        result.append(chunks[index])

    deduped: list[str] = []
    seen: set[str] = set()
    for chunk in result:
        key = normalize_for_search(chunk)
        if key in seen:
            continue
        deduped.append(chunk)
        seen.add(key)
    return deduped


def is_phone_intent(intent: DirectFactIntent) -> bool:
    return "телефон" in intent.name or "номер" in intent.name


def is_address_intent(intent: DirectFactIntent) -> bool:
    return "адрес" in intent.name or "місце" in intent.name


def is_email_intent(intent: DirectFactIntent) -> bool:
    return "пошту" in intent.name


def is_strict_contact_intent(intent: DirectFactIntent) -> bool:
    return is_phone_intent(intent) or is_email_intent(intent)


def uses_direct_fact_field_reranking(intent: DirectFactIntent) -> bool:
    return (
        is_phone_intent(intent)
        or is_address_intent(intent)
        or is_email_intent(intent)
        or "час" in intent.name
    )


def normalize_phone_value(value: str) -> str:
    return normalize_text(value.strip(" ,;:.()"))


def is_valid_phone_value(value: str) -> bool:
    cleaned = normalize_phone_value(value)
    digits = re.sub(r"\D+", "", cleaned)
    if len(digits) < 7:
        return False
    groups = re.findall(r"\d+", cleaned)
    if len(digits) == 7 and groups and len(groups[0]) != 3:
        return False
    if len(digits) <= 8 and groups and all(len(group) <= 2 for group in groups):
        return False
    if len(digits) <= 8 and any(group == "00" for group in groups):
        return False
    if re.fullmatch(r"(?:19|20)\d{2}[.-]\d{1,2}[.-]\d{1,2}", cleaned):
        return False
    if re.fullmatch(r"\d{1,2}[.-]\d{1,2}[.-]\d{2,4}", cleaned):
        return False
    if re.fullmatch(r"\d{1,2}[\s.:]\d{2}\s*[-–—]\s*\d{1,2}[\s.:]\d{2}", cleaned):
        return False
    return True


def extract_phone_numbers_from_chunk(chunk: str) -> list[str]:
    label_match = PHONE_FIELD_LABEL_RE.search(chunk)
    search_area = chunk[label_match.end() :] if label_match else chunk
    numbers: list[str] = []
    seen: set[str] = set()
    for match in PHONE_NUMBER_RE.finditer(search_area):
        number = normalize_phone_value(match.group(0))
        key = re.sub(r"\D+", "", number)
        if not is_valid_phone_value(number) or key in seen:
            continue
        numbers.append(number)
        seen.add(key)
    return numbers


def format_phone_fact_chunks(chunks: list[str]) -> list[str]:
    numbers: list[str] = []
    seen: set[str] = set()
    first_phone_chunk_index: int | None = None
    for index, chunk in enumerate(chunks):
        chunk_numbers = extract_phone_numbers_from_chunk(chunk)
        if chunk_numbers and first_phone_chunk_index is None:
            first_phone_chunk_index = index
        for number in chunk_numbers:
            key = re.sub(r"\D+", "", number)
            if key in seen:
                continue
            numbers.append(number)
            seen.add(key)

    if not numbers:
        return [chunk for chunk in chunks if not PHONE_FIELD_LABEL_RE.search(chunk)]

    label = "Телефон" if len(numbers) == 1 else "Телефони"
    prefix = [
        chunk
        for chunk in chunks[: first_phone_chunk_index or 0]
        if PHONE_CONTEXT_PREFIX_RE.search(chunk)
    ]
    return [*prefix, f"{label}: {', '.join(numbers)}."]


def extract_email_addresses_from_chunk(chunk: str) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_ADDRESS_RE.finditer(chunk):
        email = match.group(0).strip(" ,;:.")
        key = email.casefold()
        if key in seen:
            continue
        emails.append(email)
        seen.add(key)
    return emails


def format_email_fact_chunks(chunks: list[str]) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_emails = extract_email_addresses_from_chunk(chunk)
        for email in chunk_emails:
            key = email.casefold()
            if key in seen:
                continue
            emails.append(email)
            seen.add(key)

    if not emails:
        return chunks

    label = "Електронна пошта" if len(emails) == 1 else "Електронні пошти"
    return [f"{label}: {', '.join(emails)}."]


def trim_address_chunk(chunk: str) -> str:
    trimmed = CONTACT_TAIL_RE.sub("", chunk)
    trimmed = re.sub(r"\s+[,.;:]", lambda match: match.group(0).strip(), trimmed)
    return normalize_text(trimmed.strip(" ,;"))


def focus_direct_fact_chunks(text: str, intent: DirectFactIntent) -> list[str]:
    chunks = select_direct_fact_chunks_with_context(text, intent)
    if not chunks:
        return []

    if is_phone_intent(intent):
        return format_phone_fact_chunks(chunks)

    if is_address_intent(intent):
        focused = [trim_address_chunk(chunk) for chunk in chunks]
        return [chunk for chunk in focused if chunk]

    if is_email_intent(intent):
        return format_email_fact_chunks(chunks)

    return chunks


def is_direct_fact_query_term(token: str, stem: str, intent: DirectFactIntent) -> bool:
    for keyword in intent.fact_keywords:
        normalized_keyword = normalize_for_search(keyword).strip()
        if len(normalized_keyword) < 3:
            continue
        keyword_token = normalized_keyword.split()[0]
        keyword_stem = stem_token(keyword_token)
        if (
            keyword_token in token
            or keyword_token in stem
            or keyword_stem in stem
            or stem in keyword_stem
        ):
            return True
    return False


def direct_fact_object_terms(
    query_tokens: tuple[str, ...],
    query_stems: tuple[str, ...],
    intent: DirectFactIntent | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if intent is None:
        return (), ()

    object_pairs = [
        (token, stem)
        for token, stem in zip(query_tokens, query_stems)
        if len(stem) >= 4 and not is_direct_fact_query_term(token, stem, intent)
    ]
    return (
        tuple(token for token, _ in object_pairs),
        tuple(stem for _, stem in object_pairs),
    )
