from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.classifier_prompt import apply_classifier_chat_template  # noqa: E402
from app.services.voice_assistant import (  # noqa: E402
    BaseQwenAssistantService,
    KnowledgeBaseService,
    KnowledgeMatch,
)


@dataclass(frozen=True)
class AssistantExample:
    split: str
    source_id: str
    kind: str
    messages: list[dict[str, str]]
    answer: str


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def model_load_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    quantization = str(config.get("quantization", "4bit")).lower()
    kwargs: dict[str, Any] = {
        "device_map": "auto",
        "trust_remote_code": True,
    }
    if quantization == "none":
        kwargs["torch_dtype"] = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        return kwargs

    from transformers import BitsAndBytesConfig

    compute_dtype = (
        torch.bfloat16
        if torch.cuda.is_available() and torch.cuda.is_bf16_supported()
        else torch.float16
    )
    if quantization == "4bit":
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
    elif quantization == "8bit":
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
    else:
        raise ValueError(f"Unsupported quantization: {quantization}")
    return kwargs


def direct_answer_messages(question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "Ти телефонний консультант КПІ. Відповідай українською, усно, конкретно, "
                "без Markdown, без повторення питання і без службових пояснень."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Питання: {question}\n\n"
                "Сформуй одну зв'язну відповідь для телефонного дзвінка."
            ),
        },
    ]


def build_examples(config: dict[str, Any]) -> list[AssistantExample]:
    knowledge_base = KnowledgeBaseService(Path(config["knowledge_base_path"]))
    entries_by_id = {entry.id: entry for entry in knowledge_base.entries}
    rows = read_jsonl(Path(config["questions_path"]))
    examples: list[AssistantExample] = []

    include_direct = bool(config.get("include_question_answer_examples", True))
    include_context = bool(config.get("include_context_answer_examples", True))

    for row in rows:
        source_id = str(row["source_id"])
        entry = entries_by_id[source_id]
        question = str(row["question"]).strip()
        answer = BaseQwenAssistantService._clean_answer(entry.answer)
        split = str(row["split"])

        if include_direct:
            examples.append(
                AssistantExample(
                    split=split,
                    source_id=source_id,
                    kind="question_answer",
                    messages=direct_answer_messages(question),
                    answer=answer,
                )
            )

        if include_context:
            match = KnowledgeMatch(entry=entry, score=1.0)
            examples.append(
                AssistantExample(
                    split=split,
                    source_id=source_id,
                    kind="context_answer",
                    messages=BaseQwenAssistantService._build_phone_answer_messages(question, [match]),
                    answer=answer,
                )
            )

    return examples


def apply_answer_template(
    tokenizer: Any,
    messages: list[dict[str, str]],
    answer: str,
) -> tuple[str, str]:
    prompt = apply_classifier_chat_template(
        tokenizer,
        messages,
        add_generation_prompt=True,
    )
    full = apply_classifier_chat_template(
        tokenizer,
        [*messages, {"role": "assistant", "content": answer}],
        add_generation_prompt=False,
    )
    return prompt, full


def token_stats(values: list[int]) -> dict[str, int]:
    if not values:
        return {"count": 0, "min": 0, "max": 0, "avg": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "avg": round(sum(values) / len(values)),
    }


def prepare_datasets(
    *,
    examples: list[AssistantExample],
    tokenizer: Any,
    max_length: int,
    min_response_tokens: int,
) -> tuple[Dataset, Dataset, dict[str, Any]]:
    rows_by_split = {"train": [], "validation": []}
    skipped: list[dict[str, Any]] = []
    lengths: list[int] = []
    train_kinds: dict[str, int] = {}

    for example in examples:
        if example.split not in rows_by_split:
            continue

        prompt, full = apply_answer_template(tokenizer, example.messages, example.answer)
        full_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
        prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
        available_response_tokens = max_length - len(prompt_ids)

        if available_response_tokens < min_response_tokens:
            skipped.append(
                {
                    "source_id": example.source_id,
                    "split": example.split,
                    "kind": example.kind,
                    "prompt_tokens": len(prompt_ids),
                    "full_tokens": len(full_ids),
                    "reason": "prompt_too_long",
                }
            )
            continue

        tokenized = tokenizer(
            full,
            truncation=True,
            max_length=max_length,
            add_special_tokens=False,
        )
        labels = tokenized["input_ids"].copy()
        masked = min(len(prompt_ids), len(labels))
        labels[:masked] = [-100] * masked
        if all(label == -100 for label in labels):
            skipped.append(
                {
                    "source_id": example.source_id,
                    "split": example.split,
                    "kind": example.kind,
                    "prompt_tokens": len(prompt_ids),
                    "full_tokens": len(full_ids),
                    "reason": "answer_truncated",
                }
            )
            continue

        tokenized["labels"] = labels
        rows_by_split[example.split].append(tokenized)
        lengths.append(len(tokenized["input_ids"]))
        if example.split == "train":
            train_kinds[example.kind] = train_kinds.get(example.kind, 0) + 1

    if not rows_by_split["train"]:
        raise ValueError("No train examples left after length filtering.")
    if not rows_by_split["validation"]:
        raise ValueError("No validation examples left after length filtering.")

    stats = {
        "train_examples": len(rows_by_split["train"]),
        "validation_examples": len(rows_by_split["validation"]),
        "train_kinds": dict(sorted(train_kinds.items())),
        "tokenized_length": token_stats(lengths),
        "skipped": skipped,
    }
    return Dataset.from_list(rows_by_split["train"]), Dataset.from_list(rows_by_split["validation"]), stats


def make_data_collator(tokenizer: Any):
    def data_collator(features: list[dict[str, Any]]) -> dict[str, torch.Tensor]:
        labels = [feature.pop("labels") for feature in features]
        batch = tokenizer.pad(features, padding=True, return_tensors="pt")
        max_batch_length = batch["input_ids"].shape[1]
        padded_labels = [
            label + [-100] * (max_batch_length - len(label))
            for label in labels
        ]
        batch["labels"] = torch.tensor(padded_labels, dtype=torch.long)
        return batch

    return data_collator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("ml/configs/train_assistant_qlora.yaml"))
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    examples = build_examples(config)
    train_dataset, eval_dataset, stats = prepare_datasets(
        examples=examples,
        tokenizer=tokenizer,
        max_length=int(config["max_length"]),
        min_response_tokens=int(config.get("min_response_tokens", 64)),
    )

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("Dry run complete. Model was not loaded and training was not started.")
        return

    model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        **model_load_kwargs(config),
    )
    if str(config.get("quantization", "4bit")).lower() in {"4bit", "8bit"}:
        model = prepare_model_for_kbit_training(model)
    if torch.cuda.is_available() and bool(config.get("gradient_checkpointing", True)):
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
    model.print_trainable_parameters()

    output_dir = args.output_dir or Path(config["output_dir"])
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        max_steps=args.max_steps if args.max_steps is not None else -1,
        num_train_epochs=float(config["num_train_epochs"]),
        learning_rate=float(config["learning_rate"]),
        per_device_train_batch_size=int(config["per_device_train_batch_size"]),
        per_device_eval_batch_size=int(config["per_device_eval_batch_size"]),
        gradient_accumulation_steps=int(config["gradient_accumulation_steps"]),
        warmup_ratio=float(config["warmup_ratio"]),
        weight_decay=float(config["weight_decay"]),
        logging_steps=int(config["logging_steps"]),
        eval_strategy="steps",
        eval_steps=int(config["eval_steps"]),
        save_strategy="steps",
        save_steps=int(config["save_steps"]),
        save_total_limit=int(config["save_total_limit"]),
        load_best_model_at_end=bool(config.get("load_best_model_at_end", True)),
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(),
        optim=str(config.get("optim", "paged_adamw_8bit")),
        report_to=str(config.get("report_to", "none")),
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=make_data_collator(tokenizer),
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))


if __name__ == "__main__":
    main()
