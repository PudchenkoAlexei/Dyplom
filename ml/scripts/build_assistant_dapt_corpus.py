from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any


DEFAULT_KNOWLEDGE_BASE = Path("backend/app/data/kpi_faq_knowledge_base.json")
DEFAULT_OUTPUT_DIR = Path("ml/data/assistant_dapt")
SPLITS = ("train", "validation", "test")
INLINE_QUESTION_RE = re.compile(r"(^|(?<=[.!;:])\s+)([^.!?;:/]{3,180}\?)\s*")
URL_RE = re.compile(r"https?://\S+")


@dataclass(frozen=True)
class KnowledgeEntry:
    id: str
    title: str
    question: str
    answer: str
    source_url: str
    tags: tuple[str, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "KnowledgeEntry":
        return cls(
            id=str(raw["id"]).strip(),
            title=clean_text(str(raw["title"])),
            question=clean_question(str(raw["question"])),
            answer=clean_answer(str(raw["answer"])),
            source_url=str(raw["source_url"]).strip(),
            tags=tuple(clean_text(str(tag)) for tag in raw.get("tags", []) if str(tag).strip()),
        )


def clean_text(value: str) -> str:
    value = value.replace("🔗", " ")
    value = value.replace("\u00a0", " ")
    value = value.replace("’", "'")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def clean_answer(value: str) -> str:
    answer = clean_text(value)
    answer = INLINE_QUESTION_RE.sub(lambda match: match.group(1), answer)
    answer = re.sub(r"\*\*(.*?)\*\*", r"\1", answer)
    answer = URL_RE.sub(" ", answer)
    return clean_text(answer)


def clean_question(value: str) -> str:
    return clean_text(URL_RE.sub(" ", value))


def sentence_chunks(value: str, *, max_chars: int) -> list[str]:
    if len(value) <= max_chars:
        return [value]

    sentences = re.split(r"(?<=[.!?…])\s+", value)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        next_len = current_len + len(sentence) + (1 if current else 0)
        if current and next_len > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len = next_len

    if current:
        chunks.append(" ".join(current))
    return chunks


def stable_id(*parts: str) -> str:
    digest = hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def keywords_for(entry: KnowledgeEntry, *, limit: int = 14) -> str:
    values: list[str] = [entry.title]
    for tag in entry.tags:
        normalized = tag.casefold()
        if len(tag) < 3 or normalized in {value.casefold() for value in values}:
            continue
        values.append(tag)
        if len(values) >= limit:
            break
    return ", ".join(values)


def make_record(
    *,
    entry: KnowledgeEntry,
    kind: str,
    split: str,
    text: str,
    chunk_index: int = 0,
) -> dict[str, str | int]:
    return {
        "id": stable_id(entry.id, kind, str(chunk_index), text),
        "split": split,
        "kind": kind,
        "source_id": entry.id,
        "source_title": entry.title,
        "source_url": entry.source_url,
        "chunk_index": chunk_index,
        "text": clean_text(text),
    }


def build_records_for_entry(
    entry: KnowledgeEntry,
    *,
    split: str,
    max_answer_chars: int,
) -> list[dict[str, str | int]]:
    records: list[dict[str, str | int]] = []
    answer_chunks = sentence_chunks(entry.answer, max_chars=max_answer_chars)
    keyword_text = keywords_for(entry)

    for index, answer in enumerate(answer_chunks):
        suffix = f" Частина {index + 1}." if len(answer_chunks) > 1 else ""
        records.append(
            make_record(
                entry=entry,
                kind="official_source_card",
                split=split,
                chunk_index=index,
                text=(
                    f"Тема довідкової служби КПІ: {entry.title}.{suffix} "
                    f"Офіційна довідкова інформація: {answer}"
                ),
            )
        )
        records.append(
            make_record(
                entry=entry,
                kind="voice_answer_example",
                split=split,
                chunk_index=index,
                text=(
                    "Приклад відповіді голосової довідки КПІ. "
                    f"Запит користувача: {entry.question} "
                    f"Відповідь без повторення запиту: {answer}"
                ),
            )
        )
        records.append(
            make_record(
                entry=entry,
                kind="retrieval_topic_card",
                split=split,
                chunk_index=index,
                text=(
                    f"Пошукові ознаки теми довідки: {keyword_text}. "
                    f"Назва теми: {entry.title}. Зміст відповіді: {answer}"
                ),
            )
        )

    return records


def split_entries(
    entries: list[KnowledgeEntry],
    *,
    validation_ratio: float,
    test_ratio: float,
    seed: int,
) -> dict[str, str]:
    if not entries:
        return {}

    shuffled = entries[:]
    random.Random(seed).shuffle(shuffled)
    total = len(shuffled)
    validation_count = max(1, round(total * validation_ratio))
    test_count = max(1, round(total * test_ratio))
    if validation_count + test_count >= total:
        validation_count = 1 if total >= 3 else 0
        test_count = 1 if total >= 3 else 0
    train_count = total - validation_count - test_count

    split_map: dict[str, str] = {}
    for entry in shuffled[:train_count]:
        split_map[entry.id] = "train"
    for entry in shuffled[train_count : train_count + validation_count]:
        split_map[entry.id] = "validation"
    for entry in shuffled[train_count + validation_count :]:
        split_map[entry.id] = "test"
    return split_map


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_entries(path: Path) -> list[KnowledgeEntry]:
    raw_entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_entries, list):
        raise ValueError(f"Knowledge base must be a list: {path}")
    entries = [KnowledgeEntry.from_dict(item) for item in raw_entries]
    return [entry for entry in entries if entry.id and entry.answer]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--knowledge-base", type=Path, default=DEFAULT_KNOWLEDGE_BASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--validation-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-answer-chars", type=int, default=2600)
    args = parser.parse_args()

    entries = load_entries(args.knowledge_base)
    split_map = split_entries(
        entries,
        validation_ratio=args.validation_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
    )

    records: list[dict[str, Any]] = []
    eval_questions: list[dict[str, Any]] = []
    for entry in entries:
        split = split_map[entry.id]
        records.extend(
            build_records_for_entry(entry, split=split, max_answer_chars=args.max_answer_chars)
        )
        eval_questions.append(
            {
                "id": stable_id(entry.id, entry.question),
                "split": split,
                "source_id": entry.id,
                "source_title": entry.title,
                "source_url": entry.source_url,
                "question": entry.question,
                "expected_answer": entry.answer,
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        split_records = [record for record in records if record["split"] == split]
        write_jsonl(args.output_dir / f"{split}.jsonl", split_records)
    write_jsonl(args.output_dir / "eval_questions.jsonl", eval_questions)

    split_counts = Counter(record["split"] for record in records)
    kind_counts = Counter(record["kind"] for record in records)
    source_split_counts = Counter(split_map.values())
    character_count = sum(len(record["text"]) for record in records)
    metadata = {
        "knowledge_base": str(args.knowledge_base),
        "entries": len(entries),
        "source_split_counts": dict(sorted(source_split_counts.items())),
        "records": len(records),
        "record_split_counts": dict(sorted(split_counts.items())),
        "record_kind_counts": dict(sorted(kind_counts.items())),
        "characters": character_count,
        "rough_token_estimate": round(character_count / 3.6),
        "seed": args.seed,
        "max_answer_chars": args.max_answer_chars,
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Built assistant DAPT corpus from {len(entries)} knowledge entries.")
    print(f"Records: {len(records)}")
    print(f"Splits: {dict(sorted(split_counts.items()))}")
    print(f"Kinds: {dict(sorted(kind_counts.items()))}")
    print(f"Output: {args.output_dir}")


if __name__ == "__main__":
    main()
