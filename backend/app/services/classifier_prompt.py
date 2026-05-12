from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

SYSTEM_PROMPT = "You are a strict JSON classifier for Ukrainian university helpdesk tickets."


@dataclass(frozen=True)
class CatalogItem:
    name: str
    description: str | None = None


CategoryItem = CatalogItem | Mapping[str, str | None] | str


def shorten_text(text: str, max_chars: int = 320) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rsplit(" ", 1)[0].strip()


def category_name(item: CategoryItem) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        return str(item["name"])
    return item.name


def category_description(item: CategoryItem) -> str | None:
    if isinstance(item, str):
        return None
    if isinstance(item, Mapping):
        description = item.get("description")
    else:
        description = item.description
    return description.strip() if description else None


def category_guide(category_items: list[CategoryItem]) -> str:
    parts = []
    for item in category_items:
        name = category_name(item)
        description = category_description(item)
        if description:
            parts.append(f"{name} ({shorten_text(description, max_chars=28)})")
        else:
            parts.append(name)
    return "; ".join(parts)


def routing_hints() -> str:
    return (
        "вступні заяви/кабінет вступника/бюджет чи контракт до зарахування -> вступ; "
        "диплом/дублікат/апостиль/документи випускника -> документи про освіту; "
        "поновлення/переведення після зарахування/відрахування -> переведення / поновлення / відрахування; "
        "розклад/залік/оцінка/сесія -> навчальний процес; "
        "довідка/печатка/деканат -> деканат / довідки студентів; "
        "Erasmus/обмін/кредити за кордоном -> академічна мобільність; "
        "посвідка/ДМС/іноземний студент -> міжнародні студенти; "
        "логін/пошта/VPN/Moodle/Wi-Fi -> мережа / пошта / інтернет; "
        "особистий кабінет Електронного кампусу -> Електронний кампус; "
        "Scopus/книги/абонемент бібліотеки -> бібліотека; "
        "перепустка/доступ/охорона/інцидент -> безпека / перепустки."
    )


def role_value(role: Enum | str) -> str:
    return role.value if isinstance(role, Enum) else str(role)


def classifier_response_json(category: str, priority: str) -> str:
    return json.dumps(
        {
            "category": category,
            "priority": priority,
        },
        ensure_ascii=False,
    )


def build_classifier_prompt(
    *,
    role: Enum | str,
    text: str,
    categories: list[CategoryItem],
) -> str:
    ticket_text = shorten_text(text, max_chars=320)
    return (
        "Класифікуй звернення до довідкової системи КПІ. "
        "Поверни тільки валідний JSON без Markdown з полями "
        "category, priority.\n"
        f"Доступні категорії та орієнтири: {category_guide(categories)}.\n"
        "Обирай category точно з переліку за відповідальним підрозділом, не за випадковим словом.\n"
        f"Маршрутизація для схожих тем: {routing_hints()}\n"
        "Якщо в тексті згадано кілька тем, обирай категорію того підрозділу, "
        "який має виконати основну дію або вирішити блокування.\n"
        "priority: low=інфо/процедура без поточної проблеми; "
        "medium=оформити або перевірити без втрати доступу, грошей чи строку; "
        "high=заблоковано/зникло/не працює, гроші, дедлайн, безпека або відрахування. "
        "Не став medium за замовчуванням.\n"
        f"Роль автора: {role_value(role)}\n"
        f"Текст звернення: {ticket_text}\n"
    )


def build_classifier_messages(
    *,
    role: Enum | str,
    text: str,
    categories: list[CategoryItem],
    assistant_response: str | None = None,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": build_classifier_prompt(role=role, text=text, categories=categories),
        },
    ]
    if assistant_response is not None:
        messages.append({"role": "assistant", "content": assistant_response})
    return messages
