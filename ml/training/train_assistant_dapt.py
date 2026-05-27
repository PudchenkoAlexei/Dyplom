from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from datasets import Dataset
import torch
import yaml
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
from transformers import default_data_collator


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def read_text_dataset(path: Path) -> Dataset:
    rows = read_jsonl(path)
    texts = [{"text": str(item["text"])} for item in rows if str(item.get("text", "")).strip()]
    if not texts:
        raise ValueError(f"No training text found in {path}")
    return Dataset.from_list(texts)


def torch_dtype_from_config(config: dict[str, Any]) -> torch.dtype:
    dtype_name = str(config.get("torch_dtype", "bfloat16")).lower()
    if dtype_name in {"bf16", "bfloat16"}:
        return torch.bfloat16
    if dtype_name in {"fp16", "float16"}:
        return torch.float16
    if dtype_name in {"fp32", "float32"}:
        return torch.float32
    raise ValueError(f"Unsupported torch_dtype: {dtype_name}")


def model_load_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    quantization = str(config.get("quantization", "none")).lower()
    if quantization != "none":
        raise ValueError(
            "train_assistant_dapt.py is for full continued pretraining, not quantized LoRA/QLoRA."
        )

    kwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "torch_dtype": torch_dtype_from_config(config),
        "low_cpu_mem_usage": bool(config.get("low_cpu_mem_usage", True)),
    }
    attn_implementation = config.get("attn_implementation")
    if attn_implementation:
        kwargs["attn_implementation"] = str(attn_implementation)
    return kwargs


def tokenize_and_pack(
    dataset: Dataset,
    tokenizer: AutoTokenizer,
    *,
    block_size: int,
) -> Dataset:
    def tokenize_batch(batch: dict[str, list[str]]) -> dict[str, list[list[int]]]:
        return tokenizer(batch["text"], add_special_tokens=True)

    tokenized = dataset.map(
        tokenize_batch,
        batched=True,
        remove_columns=list(dataset.column_names),
        desc="Tokenizing",
    )

    def group_texts(examples: dict[str, list[list[int]]]) -> dict[str, list[list[int]]]:
        concatenated = {key: sum(values, []) for key, values in examples.items()}
        total_length = len(concatenated["input_ids"])
        total_length = (total_length // block_size) * block_size
        if total_length == 0:
            return {key: [] for key in [*concatenated.keys(), "labels"]}

        result = {
            key: [
                values[index : index + block_size]
                for index in range(0, total_length, block_size)
            ]
            for key, values in concatenated.items()
        }
        result["labels"] = result["input_ids"].copy()
        return result

    packed = tokenized.map(group_texts, batched=True, desc="Packing")
    if len(packed) == 0:
        raise ValueError("Packed dataset is empty. Reduce max_length or add more training text.")
    return packed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("ml/configs/train_assistant_dapt.yaml"))
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if not bool(config.get("train_full_parameters", True)):
        raise ValueError("Assistant DAPT config must keep train_full_parameters: true.")

    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    block_size = int(config["max_length"])
    train_dataset = tokenize_and_pack(
        read_text_dataset(Path(config["train_path"])),
        tokenizer,
        block_size=block_size,
    )
    eval_dataset = tokenize_and_pack(
        read_text_dataset(Path(config["validation_path"])),
        tokenizer,
        block_size=block_size,
    )

    print(f"Train blocks: {len(train_dataset)}")
    print(f"Validation blocks: {len(eval_dataset)}")
    print(f"Block size: {block_size}")
    if args.dry_run:
        print("Dry run complete. Model was not loaded and training was not started.")
        return

    model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        **model_load_kwargs(config),
    )
    if torch.cuda.is_available() and bool(config.get("gradient_checkpointing", True)):
        model.config.use_cache = False
        model.gradient_checkpointing_enable()

    output_dir = args.output_dir or Path(config["output_dir"])
    max_steps = args.max_steps if args.max_steps is not None else int(config.get("max_steps", -1))
    configured_dtype = torch_dtype_from_config(config)
    use_bf16 = torch.cuda.is_available() and configured_dtype == torch.bfloat16
    use_fp16 = torch.cuda.is_available() and configured_dtype == torch.float16
    eval_steps = int(config["eval_steps"])
    save_steps = int(config["save_steps"])
    deepspeed_config = config.get("deepspeed") or None

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        max_steps=max_steps,
        num_train_epochs=float(config["num_train_epochs"]),
        learning_rate=float(config["learning_rate"]),
        per_device_train_batch_size=int(config["per_device_train_batch_size"]),
        per_device_eval_batch_size=int(config["per_device_eval_batch_size"]),
        gradient_accumulation_steps=int(config["gradient_accumulation_steps"]),
        warmup_ratio=float(config["warmup_ratio"]),
        weight_decay=float(config["weight_decay"]),
        logging_steps=int(config["logging_steps"]),
        eval_strategy="steps",
        eval_steps=eval_steps,
        save_strategy="steps",
        save_steps=save_steps,
        save_total_limit=int(config["save_total_limit"]),
        load_best_model_at_end=bool(config.get("load_best_model_at_end", True)),
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=use_bf16,
        fp16=use_fp16,
        optim=str(config.get("optim", "adamw_torch")),
        report_to=str(config.get("report_to", "none")),
        deepspeed=deepspeed_config,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        tokenizer=tokenizer,
        data_collator=default_data_collator,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))


if __name__ == "__main__":
    main()
