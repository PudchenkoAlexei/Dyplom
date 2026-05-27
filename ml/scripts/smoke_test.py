"""Quick interactive sanity check on the trained classifier.

Runs ~16 hand-picked queries (one per category) covering short/long, easy/hard cases.
Prints each example with expected vs predicted category/priority and parse status.
Faster than the full test-split eval (uses max_new_tokens=64).
"""

import argparse
import importlib.machinery
import json
import sys
import time
import types
from pathlib import Path

import torch
import yaml
from peft import PeftModel

BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.classifier_prompt import (  # noqa: E402
    CatalogItem,
    apply_classifier_chat_template,
    build_classifier_messages,
)
from app.services.classifier import TicketClassifierService  # noqa: E402


def install_sklearn_stub() -> None:
    if "sklearn" in sys.modules:
        return
    sklearn = types.ModuleType("sklearn")
    sklearn.__path__ = []
    sklearn.__spec__ = importlib.machinery.ModuleSpec("sklearn", loader=None, is_package=True)
    metrics = types.ModuleType("sklearn.metrics")
    metrics.__spec__ = importlib.machinery.ModuleSpec("sklearn.metrics", loader=None)

    def roc_curve(*_, **__):
        raise RuntimeError("roc_curve unavailable in smoke runtime.")

    setattr(metrics, "roc_curve", roc_curve)
    setattr(sklearn, "metrics", metrics)
    sys.modules["sklearn"] = sklearn
    sys.modules["sklearn.metrics"] = metrics


install_sklearn_stub()
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402


def model_load_kwargs(config: dict) -> dict:
    quantization = str(config.get("quantization", "none"))
    kwargs: dict = {
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


SMOKE_QUERIES = [
    # (text, expected_category, expected_priority, note)
    ("Чи можу я очікувати додаткову академічну стипендію за наукову роботу?", "стипендія", "medium", "процедура"),
    ("Я подав заяву на поселення в гуртожиток, але в особистому кабінеті статус не оновлюється кілька днів.", "гуртожиток / проживання", "high", "статус поселення"),
    ("Куди звертатися, якщо в кабінеті вступника зник статус заяви після рекомендацій?", "вступ", "high", "блокуюче"),
    ("Як перенести лабораторну, якщо я був на змаганнях університету?", "навчальний процес", "medium", "перенесення"),
    ("Чи можна оформити заяву в деканаті в електронному вигляді?", "деканат / довідки студентів", "low", "процедурне"),
    ("Куди звертатися, якщо в моєму дипломі не вписана спеціалізація?", "документи про освіту", "high", "помилка диплома"),
    ("Як офіційно повернутися до навчання після відрахування за неоплату?", "переведення / поновлення / відрахування", "high", "поновлення"),
    ("Чи буде університет компенсувати мою візу для участі в Erasmus?", "академічна мобільність", "medium", "фінанси обміну"),
    ("Як отримати правовий супровід через домашнє насильство?", "соціальна / психологічна підтримка", "high", "критичне"),
    ("Куди писати, якщо корпоративна пошта KPI блокує мої вкладення?", "мережа / пошта / інтернет", "high", "пошта не працює"),
    ("Як виставити підсумкову оцінку в Електронному кампусі для куратора?", "Електронний кампус", "medium", "куратор"),
    ("Чи можна замовити сканування глави книги через бібліотеку КПІ?", "бібліотека", "low", "послуга"),
    ("Куди йти за консультацією щодо посвідки, якщо документи на руках, але прийом відсутній?", "міжнародні студенти", "medium", "посвідка"),
    ("Як отримати екстрений доступ до корпусу під час повітряної тривоги?", "безпека / перепустки", "high", "укриття"),
    ("Чи можливо отримати знижку на оплату навчання за досягнення в науці?", "оплата навчання / фінанси", "low", "знижка"),
    ("До якого підрозділу подавати пропозицію щодо студентського волонтерства?", "інше", "low", "ініціатива"),
]

def read_catalog_items(catalog: dict) -> list[CatalogItem]:
    descriptions = catalog.get("category_descriptions", {})
    return [
        CatalogItem(name=name, description=descriptions.get(name, department))
        for name, department in catalog["categories"].items()
    ]


def extract_json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON in: {raw[:200]}")
    return json.loads(raw[start:end + 1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("ml/configs/train_lora.yaml"))
    parser.add_argument("--max-new-tokens", type=int, default=64)
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    catalog = yaml.safe_load(Path(config["catalog_path"]).read_text(encoding="utf-8"))
    category_items = read_catalog_items(catalog)
    categories = list(catalog["categories"].keys())
    allowed_categories = set(categories)

    print(f"Base model: {config['base_model']}")
    print(f"Adapter:    {config['output_dir']}")
    print(f"Categories: {len(categories)}")
    print()

    t0 = time.time()
    print("Loading tokenizer...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    print("Loading base model...", flush=True)
    base = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        **model_load_kwargs(config),
    )
    print("Loading PEFT adapter...", flush=True)
    model = PeftModel.from_pretrained(base, config["output_dir"])
    model.eval()
    print(f"Models loaded in {time.time() - t0:.1f}s\n", flush=True)

    cat_correct = 0
    prio_correct = 0
    parse_fail = 0
    out_of_catalog = 0
    inference_time = 0.0

    for i, (text, expected_cat, expected_prio, note) in enumerate(SMOKE_QUERIES, 1):
        messages = build_classifier_messages(role="student", text=text, categories=category_items)
        prompt = apply_classifier_chat_template(tokenizer, messages, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        t1 = time.time()
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        dt = time.time() - t1
        inference_time += dt
        gen = out[0][inputs["input_ids"].shape[-1]:]
        raw = tokenizer.decode(gen, skip_special_tokens=True)

        try:
            parsed = extract_json(raw)
            pred_cat = parsed.get("category", "")
            pred_cat = (
                TicketClassifierService._match_allowed_category(pred_cat, allowed_categories)
                or pred_cat
            )
            pred_prio = parsed.get("priority", "")
        except Exception as e:
            print(f"[{i:2d}] PARSE FAIL: {e}")
            print(f"     raw: {raw[:150]}")
            parse_fail += 1
            continue

        cat_ok = pred_cat == expected_cat
        prio_ok = pred_prio == expected_prio
        cat_in_catalog = pred_cat in categories
        if cat_ok:
            cat_correct += 1
        if prio_ok:
            prio_correct += 1
        if not cat_in_catalog:
            out_of_catalog += 1

        marker_cat = "OK" if cat_ok else ("?? " if cat_in_catalog else "OOC")
        marker_prio = "OK" if prio_ok else "??"
        print(f"[{i:2d}] {marker_cat:3s} {marker_prio:2s}  ({dt:.1f}s)  «{text[:70]}{'...' if len(text) > 70 else ''}»")
        if not cat_ok or not prio_ok:
            print(f"     expected: cat={expected_cat!r} prio={expected_prio!r}")
            print(f"     got:      cat={pred_cat!r} prio={pred_prio!r}")
        print(f"     note: {note}")

    n = len(SMOKE_QUERIES)
    print()
    print("=" * 60)
    print(f"Total: {n} queries")
    print(f"Category accuracy: {cat_correct}/{n} = {cat_correct/n:.3f}")
    print(f"Priority accuracy: {prio_correct}/{n} = {prio_correct/n:.3f}")
    print(f"Parse failures:    {parse_fail}/{n}")
    print(f"Out-of-catalog:    {out_of_catalog}/{n}")
    print(f"Total inference:   {inference_time:.1f}s ({inference_time/n:.2f}s per query avg)")


if __name__ == "__main__":
    main()
