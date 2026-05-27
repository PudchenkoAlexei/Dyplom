from __future__ import annotations

import argparse
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", default="Qwen/Qwen3-4B-Instruct-2507")
    parser.add_argument("--adapter", type=Path, default=Path("ml/models/qwen3-kpi-assistant-qlora-4b"))
    parser.add_argument("--output-dir", type=Path, default=Path("ml/models/qwen3-kpi-assistant-merged-hf"))
    parser.add_argument("--torch-dtype", choices=["float16", "bfloat16"], default="float16")
    parser.add_argument("--max-shard-size", default="4GB")
    args = parser.parse_args()

    dtype = torch.float16 if args.torch_dtype == "float16" else torch.bfloat16
    if not args.adapter.exists():
        raise FileNotFoundError(f"Adapter directory does not exist: {args.adapter}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Loading base model on CPU: {args.base_model}", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=dtype,
        device_map={"": "cpu"},
        low_cpu_mem_usage=True,
        trust_remote_code=True,
    )
    print(f"Loading adapter: {args.adapter}", flush=True)
    model = PeftModel.from_pretrained(model, str(args.adapter), is_trainable=False)
    print("Merging adapter into base model...", flush=True)
    model = model.merge_and_unload()
    model.eval()

    print(f"Saving merged model: {args.output_dir}", flush=True)
    model.save_pretrained(
        args.output_dir,
        safe_serialization=True,
        max_shard_size=args.max_shard_size,
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    tokenizer.save_pretrained(args.output_dir)
    print("Merge complete.", flush=True)


if __name__ == "__main__":
    main()
