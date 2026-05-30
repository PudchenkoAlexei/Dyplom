from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import KnowledgeEntryStatus
from app.models.knowledge import KnowledgeEntry
from app.schemas.knowledge import KnowledgeEntryRead

KNOWLEDGE_BASE_SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "kpi_faq_knowledge_base.json"
SEED_TITLE_OVERRIDES_BY_SLUG = {
    "distance-learning": "Державні місця на заочному навчанні",
    "faq-net": "Корпоративна та електронна пошта КПІ",
    "gbook-12": "Конкурси, гранти та стипендії",
    "rest": "Відпочинок студентів та аспірантів",
    "transfer-faculty": "Переведення на інший факультет або спеціальність",
}
SEED_QUESTION_OVERRIDES_BY_SLUG = {
    "faq-net": "Як отримати корпоративну пошту або електронний акаунт КПІ?",
}
SEED_ANSWER_OVERRIDES_BY_SLUG = {
    "academic-vacation": (
        "Так. Академічну відпустку можна оформити, якщо обставини унеможливлюють "
        "виконання освітньої програми: за медичними показаннями, через участь у програмі "
        "академічної мобільності, призов або вступ на військову службу, довгострокове "
        "службове відрядження, сімейні обставини, вагітність і пологи, догляд за дитиною. "
        "Консультацію можна отримати в юридичному відділі університету: 1 корпус, кімната 296."
    ),
    "faq-education": (
        "Другу вищу освіту в КПІ можна отримати за напрямами підготовки, зазначеними для "
        "вступників. Питаннями другої освіти, перепідготовки, підвищення кваліфікації та "
        "стажування займається Навчально-методичний комплекс «Інститут післядипломної освіти» "
        "(НМК «ІПО»). Прийом документів і консультації: Київ, пр. Перемоги, 37, навчальний "
        "корпус №1, енергокрило, офіс 40, кімната 5, телефон 406-85-13. Паралельна освіта "
        "також можлива через підрозділи КПІ, спеціалізовані комплекси або програми подвійних "
        "дипломів; умови треба уточнювати у відповідному підрозділі."
    ),
    "faq-net": (
        "Студенти, аспіранти та викладачі КПІ можуть отримати корпоративний обліковий запис "
        "@edu.kpi.ua. Для створення або відновлення доступу потрібно звернутися до "
        "адміністратора свого підрозділу. Корпоративний акаунт використовується для "
        "університетських сервісів, зокрема Екампусу, mykpi, Moodle, Classroom, Meet, "
        "календаря, Gmail і Диска. Для зовнішніх організацій офіційна електронна пошта КПІ: "
        "mail@kpi.ua. Співробітники можуть оформити інститутський e-mail через службу "
        "технічної підтримки: корпус 7, кімната 130а; потрібно мати посвідчення співробітника "
        "і заповнити заяву."
    ),
    "node-8024": (
        "Так. Студенти інших навчальних закладів можуть користуватися послугами бібліотеки КПІ. "
        "Адреса: Київ, пр. Перемоги, 37, будівля на площі Знань. Телефон: 204-80-72."
    ),
}
SEED_TAG_OVERRIDES_BY_SLUG = {
    "faq-net": [
        "корпоративна пошта",
        "електронна пошта",
        "edu.kpi.ua",
        "акаунт",
        "Gmail",
        "Moodle",
        "Екампус",
        "адміністратор підрозділу",
    ],
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        value = " ".join(str(tag).split())
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        normalized.append(value[:120])
        seen.add(key)
    return normalized


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE)
    slug = re.sub(r"-{2,}", "-", slug.replace("_", "-")).strip("-")
    return (slug or "entry")[:160]


def normalize_seed_title(raw: dict) -> str:
    slug = normalize_slug(str(raw.get("id") or raw.get("title") or "entry"))
    override = SEED_TITLE_OVERRIDES_BY_SLUG.get(slug)
    if override:
        return override
    return " ".join(str(raw["title"]).split())


def normalize_seed_question(raw: dict) -> str:
    slug = normalize_slug(str(raw.get("id") or raw.get("title") or "entry"))
    override = SEED_QUESTION_OVERRIDES_BY_SLUG.get(slug)
    if override:
        return override
    return str(raw["question"])


def normalize_seed_answer(raw: dict) -> str:
    slug = normalize_slug(str(raw.get("id") or raw.get("title") or "entry"))
    override = SEED_ANSWER_OVERRIDES_BY_SLUG.get(slug)
    if override:
        return override
    return str(raw["answer"])


def normalize_seed_tags(raw: dict) -> list[str]:
    slug = normalize_slug(str(raw.get("id") or raw.get("title") or "entry"))
    override = SEED_TAG_OVERRIDES_BY_SLUG.get(slug)
    return normalize_tags(override if override is not None else raw.get("tags", []))


async def make_unique_slug(
    db: AsyncSession,
    value: str,
    *,
    exclude_id: UUID | None = None,
) -> str:
    base = normalize_slug(value)[:150]
    candidate = base
    suffix = 2
    while True:
        query = select(KnowledgeEntry.id).where(KnowledgeEntry.slug == candidate)
        if exclude_id:
            query = query.where(KnowledgeEntry.id != exclude_id)
        existing = await db.scalar(query)
        if not existing:
            return candidate
        suffix_text = f"-{suffix}"
        candidate = f"{base[: 160 - len(suffix_text)]}{suffix_text}"
        suffix += 1


def knowledge_content_hash(
    *,
    title: str,
    question: str,
    answer: str,
    source_url: str,
    tags: list[str],
) -> str:
    payload = {
        "answer": " ".join(answer.split()),
        "question": " ".join(question.split()),
        "source_url": source_url.strip(),
        "tags": normalize_tags(tags),
        "title": " ".join(title.split()),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def set_entry_content_hash(entry: KnowledgeEntry) -> None:
    entry.content_hash = knowledge_content_hash(
        title=entry.title,
        question=entry.question,
        answer=entry.answer,
        source_url=entry.source_url,
        tags=entry.tags_json,
    )


def entry_to_read(entry: KnowledgeEntry) -> KnowledgeEntryRead:
    return KnowledgeEntryRead(
        id=entry.id,
        slug=entry.slug,
        title=entry.title,
        question=entry.question,
        answer=entry.answer,
        source_url=entry.source_url,
        tags=list(entry.tags_json or []),
        status=entry.status,
        content_hash=entry.content_hash,
        published_at=entry.published_at,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


async def seed_knowledge_base_from_json(db: AsyncSession) -> None:
    existing_count = await db.scalar(select(func.count(KnowledgeEntry.id)))
    if existing_count:
        await normalize_seeded_knowledge_entries(db)
        return

    raw_entries = json.loads(KNOWLEDGE_BASE_SEED_PATH.read_text(encoding="utf-8"))
    now = utc_now()
    for raw in raw_entries:
        title = normalize_seed_title(raw)
        question = normalize_seed_question(raw)
        answer = normalize_seed_answer(raw)
        tags = normalize_seed_tags(raw)
        entry = KnowledgeEntry(
            slug=await make_unique_slug(db, str(raw.get("id") or raw["title"])),
            title=title,
            question=question,
            answer=answer,
            source_url=str(raw["source_url"]),
            tags_json=tags,
            status=KnowledgeEntryStatus.published,
            content_hash=knowledge_content_hash(
                title=title,
                question=question,
                answer=answer,
                source_url=str(raw["source_url"]),
                tags=tags,
            ),
            published_at=now,
        )
        db.add(entry)
        await db.flush()


async def normalize_seeded_knowledge_entries(db: AsyncSession) -> None:
    slugs = (
        set(SEED_TITLE_OVERRIDES_BY_SLUG)
        | set(SEED_QUESTION_OVERRIDES_BY_SLUG)
        | set(SEED_ANSWER_OVERRIDES_BY_SLUG)
        | set(SEED_TAG_OVERRIDES_BY_SLUG)
    )
    result = await db.execute(select(KnowledgeEntry).where(KnowledgeEntry.slug.in_(slugs)))
    for entry in result.scalars().all():
        changed = False
        normalized_title = SEED_TITLE_OVERRIDES_BY_SLUG.get(entry.slug)
        if normalized_title and entry.title != normalized_title:
            entry.title = normalized_title
            changed = True
        normalized_question = SEED_QUESTION_OVERRIDES_BY_SLUG.get(entry.slug)
        if normalized_question and entry.question != normalized_question:
            entry.question = normalized_question
            changed = True
        normalized_answer = SEED_ANSWER_OVERRIDES_BY_SLUG.get(entry.slug)
        if normalized_answer and entry.answer != normalized_answer:
            entry.answer = normalized_answer
            changed = True
        normalized_tags = SEED_TAG_OVERRIDES_BY_SLUG.get(entry.slug)
        if normalized_tags is not None and entry.tags_json != normalize_tags(normalized_tags):
            entry.tags_json = normalize_tags(normalized_tags)
            changed = True
        if changed:
            set_entry_content_hash(entry)
