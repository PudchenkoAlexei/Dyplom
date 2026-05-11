import argparse
from collections import Counter
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


EXPECTED_SPLIT_LAYOUT = {"train": 50, "validation": 5, "test": 5}
EXPECTED_PER_CATEGORY = sum(EXPECTED_SPLIT_LAYOUT.values())


class LabeledTicket(BaseModel):
    split: str = Field(pattern="^(train|validation|test)$")
    role: str = Field(pattern="^(student|teacher)$")
    text: str = Field(min_length=3)
    category: str = Field(min_length=2)
    priority: str = Field(pattern="^(low|medium|high)$")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("ml/data/curated/tickets_curated.jsonl"))
    parser.add_argument("--catalog", type=Path, default=Path("ml/configs/catalog.yaml"))
    args = parser.parse_args()

    catalog = yaml.safe_load(args.catalog.read_text(encoding="utf-8"))
    categories = set(catalog["categories"].keys())
    priorities = set(catalog["priorities"])

    errors: list[str] = []
    count = 0
    split_counts: dict[str, int] = {"train": 0, "validation": 0, "test": 0}
    category_counts: dict[str, int] = {}
    category_split_counts: Counter[tuple[str, str]] = Counter()
    seen_texts: dict[str, int] = {}
    with args.dataset.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            count += 1
            try:
                item = LabeledTicket.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as exc:
                errors.append(f"line {line_number}: {exc}")
                continue
            if item.category not in categories:
                errors.append(f"line {line_number}: unknown category {item.category!r}")
            if item.priority not in priorities:
                errors.append(f"line {line_number}: unknown priority {item.priority!r}")
            normalized_text = " ".join(item.text.casefold().split())
            if normalized_text in seen_texts:
                errors.append(
                    f"line {line_number}: duplicate text, first seen on line {seen_texts[normalized_text]}"
                )
            else:
                seen_texts[normalized_text] = line_number
            split_counts[item.split] += 1
            category_counts[item.category] = category_counts.get(item.category, 0) + 1
            category_split_counts[(item.category, item.split)] += 1

    missing_categories = sorted(categories - set(category_counts))
    for category in missing_categories:
        errors.append(f"missing category: {category!r}")
    for category in sorted(categories):
        total = category_counts.get(category, 0)
        if total != EXPECTED_PER_CATEGORY:
            errors.append(f"category {category!r}: expected {EXPECTED_PER_CATEGORY} examples, got {total}")
        for split, expected_count in EXPECTED_SPLIT_LAYOUT.items():
            actual_count = category_split_counts[(category, split)]
            if actual_count != expected_count:
                errors.append(
                    f"category {category!r}, split {split!r}: expected {expected_count}, got {actual_count}"
                )

    if errors:
        for error in errors[:100]:
            print(error)
        raise SystemExit(f"Dataset validation failed with {len(errors)} errors.")
    print(f"Dataset is valid: {count} examples.")
    print(f"Splits: {split_counts}")
    print(f"Categories: {dict(sorted(category_counts.items()))}")


if __name__ == "__main__":
    main()
