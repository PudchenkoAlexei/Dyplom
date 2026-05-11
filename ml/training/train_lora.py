import argparse
import json
from pathlib import Path

import torch
import yaml
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments


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


def assistant_json(example: dict) -> str:
    return json.dumps(
        {
            "category": example["category"],
            "priority": example["priority"],
        },
        ensure_ascii=False,
    )


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
        {"role": "assistant", "content": assistant_json(example)},
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("ml/configs/train_lora.yaml"))
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))

    examples = read_jsonl(Path(config["dataset_path"]))
    splits = split_examples(examples)
    category_items = read_catalog_items(Path(config["catalog_path"]))
    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    def tokenize(example: dict) -> dict:
        messages = make_messages(example, category_items)
        prompt = tokenizer.apply_chat_template(messages[:2], tokenize=False, add_generation_prompt=True)
        text = tokenizer.apply_chat_template(messages, tokenize=False)
        tokenized = tokenizer(
            text,
            truncation=True,
            max_length=int(config["max_length"]),
        )
        prompt_length = len(
            tokenizer(
                prompt,
                truncation=True,
                max_length=int(config["max_length"]),
            )["input_ids"]
        )
        labels = tokenized["input_ids"].copy()
        labels[: min(prompt_length, len(labels))] = [-100] * min(prompt_length, len(labels))
        if all(label == -100 for label in labels):
            raise ValueError("Assistant response was truncated; reduce prompt size or increase max_length.")
        tokenized["labels"] = labels
        return tokenized

    def data_collator(features: list[dict]) -> dict:
        labels = [feature.pop("labels") for feature in features]
        batch = tokenizer.pad(features, padding=True, return_tensors="pt")
        max_length = batch["input_ids"].shape[1]
        padded_labels = [
            label + [-100] * (max_length - len(label))
            for label in labels
        ]
        batch["labels"] = torch.tensor(padded_labels, dtype=torch.long)
        return batch

    train_dataset = Dataset.from_list(splits["train"]).map(tokenize, remove_columns=list(splits["train"][0].keys()))
    eval_dataset = Dataset.from_list(splits["validation"]).map(
        tokenize,
        remove_columns=list(splits["validation"][0].keys()),
    )

    model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True,
    )
    if torch.cuda.is_available() and config.get("gradient_checkpointing", True):
        model.config.use_cache = False
        model.gradient_checkpointing_enable()
    lora_config = LoraConfig(
        r=int(config["lora"]["r"]),
        lora_alpha=int(config["lora"]["alpha"]),
        lora_dropout=float(config["lora"]["dropout"]),
        target_modules=config["lora"]["target_modules"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    output_dir = args.output_dir or Path(config["output_dir"])
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        max_steps=args.max_steps if args.max_steps is not None else -1,
        num_train_epochs=float(config["num_train_epochs"]),
        learning_rate=float(config["learning_rate"]),
        per_device_train_batch_size=int(config["per_device_train_batch_size"]),
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=int(config["gradient_accumulation_steps"]),
        warmup_ratio=float(config["warmup_ratio"]),
        weight_decay=float(config["weight_decay"]),
        logging_steps=int(config["logging_steps"]),
        save_steps=int(config["save_steps"]),
        eval_strategy="steps",
        eval_steps=int(config["save_steps"]),
        save_total_limit=3,
        load_best_model_at_end=bool(config.get("load_best_model_at_end", True)),
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=torch.cuda.is_available(),
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))


if __name__ == "__main__":
    main()
