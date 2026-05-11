import argparse
import importlib.machinery
import json
from pathlib import Path
import sys
import types

import torch
import yaml
from peft import PeftModel


def install_sklearn_stub() -> None:
    """Avoid importing Windows-unstable sklearn/pyarrow during plain generation."""

    if "sklearn" in sys.modules:
        return

    sklearn = types.ModuleType("sklearn")
    sklearn.__path__ = []
    sklearn.__spec__ = importlib.machinery.ModuleSpec("sklearn", loader=None, is_package=True)

    metrics = types.ModuleType("sklearn.metrics")
    metrics.__spec__ = importlib.machinery.ModuleSpec("sklearn.metrics", loader=None)

    def roc_curve(*_: object, **__: object) -> None:
        raise RuntimeError("roc_curve is unavailable in the lightweight evaluation runtime.")

    metrics.roc_curve = roc_curve
    sklearn.metrics = metrics
    sys.modules["sklearn"] = sklearn
    sys.modules["sklearn.metrics"] = metrics


install_sklearn_stub()

from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def split_examples(examples: list[dict]) -> dict[str, list[dict]]:
    explicit = {name: [item for item in examples if item.get("split") == name] for name in ["train", "validation", "test"]}
    if explicit["train"] and explicit["validation"]:
        return explicit

    shuffled = examples[:]
    generator = torch.Generator().manual_seed(42)
    order = torch.randperm(len(shuffled), generator=generator).tolist()
    shuffled = [shuffled[index] for index in order]
    train_end = int(len(shuffled) * 0.8)
    validation_end = int(len(shuffled) * 0.9)
    return {
        "train": shuffled[:train_end],
        "validation": shuffled[train_end:validation_end],
        "test": shuffled[validation_end:],
    }


def read_catalog_items(path: Path) -> list[dict[str, str]]:
    catalog = yaml.safe_load(path.read_text(encoding="utf-8"))
    descriptions = catalog.get("category_descriptions", {})
    return [
        {
            "name": name,
            "department": department,
            "description": descriptions.get(name, ""),
        }
        for name, department in catalog["categories"].items()
    ]


def read_catalog_categories(path: Path) -> list[str]:
    return [item["name"] for item in read_catalog_items(path)]


def shorten_text(text: str, max_chars: int = 320) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rsplit(" ", 1)[0].strip()


def category_guide(category_items: list[dict[str, str]] | list[str]) -> str:
    lines = []
    for item in category_items:
        if isinstance(item, str):
            lines.append(f"- {item}")
        else:
            details = shorten_text(item.get("description") or "звернення цієї теми", max_chars=45)
            lines.append(f"- {item['name']}: {details}")
    return "\n".join(lines)


def routing_hints() -> str:
    return (
        "довідки/середній бал/підпис/наказ -> деканат / довідки студентів; "
        "розклад/сесія/оцінювання/заборгованість до відрахування -> навчальний процес; "
        "поновлення/переведення/академвідпустка/відрахування -> переведення / поновлення / відрахування; "
        "оцінки/ролі/курси саме в Електронному кампусі -> Електронний кампус; "
        "диплом/дублікат/апостиль -> документи про освіту; "
        "вступна заява/кабінет вступника/підготовчі курси -> вступ; "
        "посвідка/віза/ДМС іноземця -> міжнародні студенти; "
        "Wi-Fi/VPN/Moodle/пошта -> мережа / пошта / інтернет; "
        "Scopus/Web of Science/книги -> бібліотека."
    )


def make_messages(example: dict, category_items: list[dict[str, str]] | list[str]) -> list[dict]:
    ticket_text = shorten_text(example["text"])
    category_names = [item if isinstance(item, str) else item["name"] for item in category_items]
    categories = ", ".join(category_names)
    return [
        {
            "role": "system",
            "content": "You are a strict JSON classifier for Ukrainian university helpdesk tickets.",
        },
        {
            "role": "user",
            "content": (
                "Класифікуй звернення до довідкової системи КПІ. "
                "Поверни тільки валідний JSON без Markdown з полями "
                "category, priority.\n"
                f"Доступні категорії: {categories}\n"
                "Обирай категорію за відповідальним підрозділом, а не за випадковим словом у тексті.\n"
                "Поле category має точно збігатися з однією доступною категорією.\n"
                "Якщо в тексті згадано кілька тем, обирай категорію того підрозділу, "
                "який має виконати основну дію або вирішити блокування.\n"
                "Пріоритети: low, medium, high.\n"
                "low - довідкове питання без блокування; medium - стандартне робоче звернення; "
                "high - заблокована дія, втрата доступу, гроші, дедлайн, безпека або ризик відрахування.\n"
                "Не став medium за замовчуванням: якщо користувач лише питає де/як/коли без блокування - low; "
                "якщо дія вже не працює, є дедлайн, кошти, доступ, безпека або юридичний ризик - high.\n"
                f"Роль автора: {example['role']}\n"
                f"Текст звернення: {ticket_text}"
            ),
        },
    ]


def accuracy_score(y_true: list[str], y_pred: list[str]) -> float:
    if not y_true:
        return 0.0
    return sum(expected == actual for expected, actual in zip(y_true, y_pred, strict=True)) / len(y_true)


def classification_report(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true) | set(y_pred))
    report: dict[str, dict[str, float] | float] = {}
    total_support = len(y_true)
    weighted_precision = 0.0
    weighted_recall = 0.0
    weighted_f1 = 0.0

    for label in labels:
        true_positive = sum(expected == label and actual == label for expected, actual in zip(y_true, y_pred, strict=True))
        false_positive = sum(expected != label and actual == label for expected, actual in zip(y_true, y_pred, strict=True))
        false_negative = sum(expected == label and actual != label for expected, actual in zip(y_true, y_pred, strict=True))
        support = sum(expected == label for expected in y_true)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        report[label] = {
            "precision": precision,
            "recall": recall,
            "f1-score": f1,
            "support": support,
        }
        weighted_precision += precision * support
        weighted_recall += recall * support
        weighted_f1 += f1 * support

    report["accuracy"] = accuracy_score(y_true, y_pred)
    report["weighted avg"] = {
        "precision": weighted_precision / total_support if total_support else 0.0,
        "recall": weighted_recall / total_support if total_support else 0.0,
        "f1-score": weighted_f1 / total_support if total_support else 0.0,
        "support": total_support,
    }
    return report


def extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object in output: {text}")
    return json.loads(text[start : end + 1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("ml/configs/train_lora.yaml"))
    parser.add_argument("--split", default="test", choices=["train", "validation", "test"])
    parser.add_argument("--output", type=Path, default=Path("ml/outputs/evaluation_metrics.json"))
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))

    examples = split_examples(read_jsonl(Path(config["dataset_path"])))[args.split]
    category_items = read_catalog_items(Path(config["catalog_path"]))
    category_names = [item["name"] for item in category_items]
    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base_model, config["output_dir"])
    model.eval()

    y_category_true: list[str] = []
    y_category_pred: list[str] = []
    y_priority_true: list[str] = []
    y_priority_pred: list[str] = []
    failures: list[dict] = []
    predictions: list[dict] = []

    for index, example in enumerate(examples, start=1):
        messages = make_messages({**example, "category": "", "priority": "low"}, category_items)[:2]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        raw = tokenizer.decode(generated, skip_special_tokens=True)
        try:
            parsed = extract_json(raw)
            y_category_true.append(example["category"])
            y_category_pred.append(parsed.get("category", ""))
            y_priority_true.append(example["priority"])
            y_priority_pred.append(parsed.get("priority", ""))
            predictions.append(
                {
                    "text": example["text"],
                    "expected_category": example["category"],
                    "predicted_category": parsed.get("category", ""),
                    "expected_priority": example["priority"],
                    "predicted_priority": parsed.get("priority", ""),
                    "raw_output": raw,
                }
            )
        except Exception as exc:
            failures.append({"text": example["text"], "raw_output": raw, "error": str(exc)})
        if index % 5 == 0 or index == len(examples):
            print(f"evaluated {index}/{len(examples)}", file=sys.stderr, flush=True)

    metrics = {
        "split": args.split,
        "count": len(examples),
        "parsed": len(y_category_true),
        "parse_failures": len(failures),
        "category_accuracy": accuracy_score(y_category_true, y_category_pred) if y_category_true else 0,
        "priority_accuracy": accuracy_score(y_priority_true, y_priority_pred) if y_priority_true else 0,
        "unknown_categories": sorted(set(y_category_pred) - set(category_names)),
        "category_report": classification_report(y_category_true, y_category_pred) if y_category_true else {},
        "priority_report": classification_report(y_priority_true, y_priority_pred) if y_priority_true else {},
        "mismatches": [
            item
            for item in predictions
            if item["expected_category"] != item["predicted_category"]
            or item["expected_priority"] != item["predicted_priority"]
        ],
        "failures": failures[:20],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: metrics[key] for key in ["count", "parsed", "category_accuracy", "priority_accuracy"]},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
