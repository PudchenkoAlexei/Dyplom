from __future__ import annotations

import json
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


KPI_GROUPS_SOURCE_URL = "https://api.campus.kpi.ua/group/all"

FALLBACK_STUDENT_GROUPS = (
    "ІП-31",
    "ІП-32",
    "ІП-33",
    "ІП-41",
    "ІП-42",
    "ІП-43",
    "ІО-31",
    "ІО-32",
    "ІО-41",
    "ІО-42",
    "ІС-31",
    "ІС-32",
    "ІС-41",
    "ІС-42",
    "КА-31",
    "КА-32",
    "КА-41",
    "КА-42",
    "КМ-31",
    "КМ-32",
    "КМ-41",
    "КМ-42",
    "ФІ-31",
    "ФІ-32",
    "ФІ-41",
    "ФІ-42",
)


def _load_groups_from_kpi_api() -> list[str]:
    request = Request(
        KPI_GROUPS_SOURCE_URL,
        headers={"User-Agent": "KPI Voice Helpdesk diploma project"},
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    records = payload.get("value", []) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        return []

    group_names: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name") or "").strip()
        if name:
            group_names.append(name)
    return group_names


@lru_cache(maxsize=1)
def get_student_groups() -> tuple[str, ...]:
    try:
        groups = _load_groups_from_kpi_api()
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        groups = []

    if not groups:
        groups = list(FALLBACK_STUDENT_GROUPS)

    return tuple(sorted(set(groups), key=str.casefold))


def is_known_student_group(group_name: str) -> bool:
    return group_name.strip() in get_student_groups()
