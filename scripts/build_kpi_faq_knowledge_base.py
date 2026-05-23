from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

FAQ_URL = "https://kpi.ua/faq"
DEFAULT_OUTPUT = Path("backend/app/data/kpi_faq_knowledge_base.json")

STOP_HEADINGS = {
    "Останні матеріали сайту",
    "Структура",
    "Організації",
    "Можливості освіти",
    "Інформаційні ресурси",
    "Для користувачів",
    "Актуальне",
}

SKIP_LINK_TEXTS = {
    "",
    "Головна",
    "Контактні дані",
    "Обов'язкова інформація",
    "Карта сайту",
    "Нові матеріали",
}

TAG_STOP_WORDS = {
    "або",
    "але",
    "без",
    "вже",
    "для",
    "до",
    "за",
    "з",
    "із",
    "і",
    "й",
    "кпі",
    "на",
    "не",
    "по",
    "про",
    "та",
    "у",
    "чи",
    "що",
    "як",
    "яка",
    "який",
}

INLINE_FAQ_QUESTION_RE = re.compile(r"(^|(?<=[.!;:])\s+)([^.!?;:/]{3,120}\?)\s*")


@dataclass(frozen=True)
class Link:
    text: str
    url: str


@dataclass(frozen=True)
class FaqPage:
    title: str
    question: str
    answer: str
    url: str


def clean_text(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", unescape(value).replace("🔗", "")).strip()
    return re.sub(r"\s+-\s*$", "", cleaned).strip()


def strip_inline_faq_questions(value: str) -> str:
    return INLINE_FAQ_QUESTION_RE.sub(lambda match: match.group(1), value)


def trim_answer(value: str, max_chars: int) -> str:
    cleaned = clean_text(value)
    if max_chars <= 0:
        return cleaned
    if len(cleaned) <= max_chars:
        return cleaned

    trimmed = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
    sentence_end = max(trimmed.rfind("."), trimmed.rfind("!"), trimmed.rfind("?"))
    if sentence_end >= int(max_chars * 0.45):
        return trimmed[: sentence_end + 1].strip()
    return f"{trimmed.rstrip(',;:')}."


def fetch_url(url: str, *, timeout: int = 20, retries: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; KPIHelpdeskKnowledgeBaseBuilder/1.0; "
                        "+https://kpi.ua/faq)"
                    )
                },
            )
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last_error}") from last_error


class AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._href: str | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attrs_map = dict(attrs)
        self._href = attrs_map.get("href")
        self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        self.links.append(Link(text=clean_text(" ".join(self._chunks)), url=self._href))
        self._href = None
        self._chunks = []


class ArticleExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.detailed_question = ""
        self.blocks: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._detail_depth = 0
        self._body_depth = 0
        self._current_tag: str | None = None
        self._chunks: list[str] = []
        self._stopped = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "header", "nav", "footer", "aside"}:
            self._skip_depth += 1
            return
        if self._skip_depth or self._stopped:
            return

        attrs_map = dict(attrs)
        class_names = set((attrs_map.get("class") or "").split())
        if "field--name-field-detailed-question" in class_names:
            self._detail_depth = 1
        elif self._detail_depth:
            self._detail_depth += 1

        if "field--name-body" in class_names:
            self._body_depth = 1
        elif self._body_depth:
            self._body_depth += 1

        if tag == "h1" or ((self._detail_depth or self._body_depth) and tag in {"h2", "h3", "p", "li"}):
            self._current_tag = tag
            self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._current_tag is None or self._stopped:
            return
        self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "header", "nav", "footer", "aside"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._stopped:
            if self._detail_depth:
                self._detail_depth -= 1
            if self._body_depth:
                self._body_depth -= 1
            return

        if self._current_tag == tag:
            text = clean_text(" ".join(self._chunks))
            if tag == "h1" and text:
                self.title = text
            elif self._detail_depth and text:
                self.detailed_question = clean_text(f"{self.detailed_question} {text}")
            elif self._body_depth and text:
                if tag in {"h2", "h3"} and any(text.startswith(heading) for heading in STOP_HEADINGS):
                    self._stopped = True
                else:
                    self.blocks.append((tag, text))

            self._current_tag = None
            self._chunks = []

        if self._detail_depth:
            self._detail_depth -= 1
        if self._body_depth:
            self._body_depth -= 1


def faq_links(index_html: str, base_url: str) -> list[Link]:
    parser = AnchorCollector()
    parser.feed(index_html)

    links: list[Link] = []
    seen_urls: set[str] = set()
    in_faq_list = False
    for link in parser.links:
        text = clean_text(link.text)
        if text == "Академвідпустка":
            in_faq_list = True
        if not in_faq_list:
            continue
        if text.startswith("Останні матеріали"):
            break
        if text in SKIP_LINK_TEXTS:
            continue

        url = urljoin(base_url, link.url)
        parsed = urlparse(url)
        if parsed.netloc not in {"kpi.ua", "www.kpi.ua"}:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        links.append(Link(text=text, url=url))
    return links


def extract_page(html: str, url: str, fallback_title: str, *, max_answer_chars: int) -> FaqPage | None:
    parser = ArticleExtractor()
    parser.feed(html)

    title = parser.title or fallback_title
    question = parser.detailed_question
    answer_blocks: list[str] = []

    for tag, text in parser.blocks:
        if text == title or text in SKIP_LINK_TEXTS:
            continue
        if re.fullmatch(r"\d{2}-\d{2}-\d{4}", text):
            continue
        if text.endswith("?"):
            if not question:
                question = text
            continue
        if len(text) < 12:
            continue
        answer_blocks.append(text)

    answer = trim_answer(
        strip_inline_faq_questions(" ".join(answer_blocks)),
        max_answer_chars,
    )
    if not answer:
        return None
    return FaqPage(title=title, question=question or title, answer=answer, url=url)


def stable_id(url: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^0-9A-Za-z_-]+", "-", path).strip("-").lower()
    if slug:
        return slug[:80]
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def tags_for(page: FaqPage, *, limit: int = 10) -> list[str]:
    words = re.findall(r"[0-9A-Za-zА-ЩЬЮЯҐЄІЇа-щьюяґєії']{3,}", f"{page.title} {page.question}")
    tags: list[str] = []
    seen: set[str] = set()
    for word in words:
        normalized = word.casefold().strip("'")
        if normalized in TAG_STOP_WORDS or normalized in seen:
            continue
        seen.add(normalized)
        tags.append(word)
        if len(tags) >= limit:
            break
    return tags


def page_to_entry(page: FaqPage) -> dict[str, object]:
    return {
        "id": stable_id(page.url),
        "title": page.title,
        "question": page.question,
        "answer": page.answer,
        "source_url": page.url,
        "tags": tags_for(page),
    }


def build_knowledge_base(
    *,
    faq_url: str,
    limit: int | None,
    request_delay: float,
    max_answer_chars: int,
) -> tuple[list[dict[str, object]], list[str]]:
    index_html = fetch_url(faq_url)
    links = faq_links(index_html, faq_url)
    if limit:
        links = links[:limit]
    if not links:
        raise RuntimeError("No FAQ links were found on the index page.")

    entries: list[dict[str, object]] = []
    skipped: list[str] = []
    for index, link in enumerate(links, start=1):
        try:
            page = extract_page(
                fetch_url(link.url),
                link.url,
                fallback_title=link.text,
                max_answer_chars=max_answer_chars,
            )
            if page is None:
                skipped.append(link.url)
            else:
                entries.append(page_to_entry(page))
        except RuntimeError as exc:
            skipped.append(f"{link.url}: {exc}")

        if index < len(links):
            time.sleep(request_delay)

    return entries, skipped


def write_json(path: Path, entries: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--faq-url", default=FAQ_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--request-delay", type=float, default=0.4)
    parser.add_argument("--max-answer-chars", type=int, default=0)
    args = parser.parse_args()

    entries, skipped = build_knowledge_base(
        faq_url=args.faq_url,
        limit=args.limit,
        request_delay=args.request_delay,
        max_answer_chars=args.max_answer_chars,
    )
    write_json(args.output, entries)

    print(f"FAQ entries written: {len(entries)}")
    print(f"Output: {args.output}")
    if skipped:
        print(f"Skipped: {len(skipped)}")
        for item in skipped[:10]:
            print(f"- {item}")


if __name__ == "__main__":
    main()
