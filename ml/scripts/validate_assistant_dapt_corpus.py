from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any


REQUIRED_FILES = ("train.jsonl", "validation.jsonl", "test.jsonl", "eval_questions.jsonl")
REQUIRED_RECORD_FIELDS = {
    "id",
    "split",
    "kind",
    "source_id",
    "source_title",
    "source_url",
    "chunk_index",
    "text",
}
VALID_SPLITS = {"train", "validation", "test"}
VALID_KINDS = {"official_source_card", "voice_answer_example", "retrieval_topic_card"}
URL_RE = re.compile(r"https?://\S+")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"{path}:{line_number}: expected object")
            rows.append(item)
    return rows


def normalize_for_dedupe(value: str) -> str:
    return " ".join(value.casefold().split())


def validate_training_records(output_dir: Path) -> list[str]:
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    for split in VALID_SPLITS:
        path = output_dir / f"{split}.jsonl"
        if not path.exists():
            errors.append(f"missing file: {path}")
            continue
        for item in read_jsonl(path):
            if item.get("split") != split:
                errors.append(f"{path}: record {item.get('id')!r} has split {item.get('split')!r}")
            records.append(item)

    seen_ids: set[str] = set()
    seen_texts: dict[str, str] = {}
    sources_by_split: dict[str, set[str]] = defaultdict(set)
    split_counts: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()

    for item in records:
        missing = REQUIRED_RECORD_FIELDS - set(item)
        if missing:
            errors.append(f"record {item.get('id')!r}: missing fields {sorted(missing)}")
            continue

        record_id = str(item["id"])
        split = str(item["split"])
        kind = str(item["kind"])
        source_id = str(item["source_id"])
        text = str(item["text"])

        if record_id in seen_ids:
            errors.append(f"duplicate id: {record_id}")
        seen_ids.add(record_id)

        if split not in VALID_SPLITS:
            errors.append(f"record {record_id}: invalid split {split!r}")
        if kind not in VALID_KINDS:
            errors.append(f"record {record_id}: invalid kind {kind!r}")
        if len(text) < 80:
            errors.append(f"record {record_id}: text is too short")
        if URL_RE.search(text):
            errors.append(f"record {record_id}: text contains URL; keep URLs in source_url only")
        if "FAQ" in text or "faq" in text:
            errors.append(f"record {record_id}: text contains FAQ wording")

        normalized_text = normalize_for_dedupe(text)
        first_id = seen_texts.get(normalized_text)
        if first_id:
            errors.append(f"record {record_id}: duplicate text, first seen in {first_id}")
        else:
            seen_texts[normalized_text] = record_id

        split_counts[split] += 1
        kind_counts[kind] += 1
        sources_by_split[split].add(source_id)

    for split in VALID_SPLITS:
        if split_counts[split] == 0:
            errors.append(f"split {split!r} is empty")

    split_items = list(sources_by_split.items())
    for index, (left_split, left_sources) in enumerate(split_items):
        for right_split, right_sources in split_items[index + 1 :]:
            overlap = left_sources & right_sources
            if overlap:
                errors.append(
                    f"sources leak between {left_split!r} and {right_split!r}: {sorted(overlap)[:10]}"
                )

    if not errors:
        print(f"Training records: {len(records)}")
        print(f"Splits: {dict(sorted(split_counts.items()))}")
        print(f"Kinds: {dict(sorted(kind_counts.items()))}")
        print(
            "Source splits: "
            f"{dict(sorted((split, len(sources)) for split, sources in sources_by_split.items()))}"
        )
    return errors


def validate_eval_questions(output_dir: Path) -> list[str]:
    errors: list[str] = []
    path = output_dir / "eval_questions.jsonl"
    if not path.exists():
        return [f"missing file: {path}"]

    rows = read_jsonl(path)
    seen_questions: dict[str, str] = {}
    split_counts: Counter[str] = Counter()
    for item in rows:
        question = str(item.get("question", "")).strip()
        expected_answer = str(item.get("expected_answer", "")).strip()
        source_id = str(item.get("source_id", "")).strip()
        split = str(item.get("split", "")).strip()
        if split not in VALID_SPLITS:
            errors.append(f"eval question {item.get('id')!r}: invalid split {split!r}")
        if len(question) < 5:
            errors.append(f"eval question {item.get('id')!r}: question is too short")
        if len(expected_answer) < 30:
            errors.append(f"eval question {item.get('id')!r}: expected answer is too short")
        normalized = normalize_for_dedupe(question)
        first_source = seen_questions.get(normalized)
        if first_source and first_source != source_id:
            errors.append(
                f"eval question {item.get('id')!r}: duplicate question from {first_source!r}"
            )
        else:
            seen_questions[normalized] = source_id
        split_counts[split] += 1

    if not errors:
        print(f"Eval questions: {len(rows)}")
        print(f"Eval splits: {dict(sorted(split_counts.items()))}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("ml/data/assistant_dapt"))
    args = parser.parse_args()

    errors: list[str] = []
    for filename in REQUIRED_FILES:
        if not (args.data_dir / filename).exists():
            errors.append(f"missing file: {args.data_dir / filename}")

    if not errors:
        errors.extend(validate_training_records(args.data_dir))
        errors.extend(validate_eval_questions(args.data_dir))

    if errors:
        for error in errors[:100]:
            print(error)
        raise SystemExit(f"Assistant DAPT corpus validation failed with {len(errors)} errors.")
    print("Assistant DAPT corpus is valid.")


if __name__ == "__main__":
    main()
