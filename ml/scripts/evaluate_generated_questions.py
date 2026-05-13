import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

import torch
import yaml
from peft import PeftModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ml.training.evaluate_classifier import (  # noqa: E402
    extract_json,
    read_catalog_items,
)
from app.services.classifier_prompt import (  # noqa: E402
    CatalogItem,
    apply_classifier_chat_template,
    build_classifier_messages,
)


SIMPLE_QUESTIONS: list[tuple[str, str, str]] = [
    ("Як подати заяву на надбавку до академічної стипендії?", "стипендія", "medium"),
    ("Коли стипендія за лютий буде на картці?", "стипендія", "low"),
    ("Як заплатити за гуртожиток через банк?", "гуртожиток / проживання", "low"),
    ("Чому в моєму гуртожитку відключено електрику кілька годин?", "гуртожиток / проживання", "high"),
    ("Чи можна подати документи на вступ онлайн?", "вступ", "low"),
    ("Чому система вступу не показує мою заяву?", "вступ", "high"),
    ("Як подати заяву на перездачу курсової?", "навчальний процес", "medium"),
    ("Чи можна перенести іспит на іншу дату?", "навчальний процес", "medium"),
    ("Як отримати довідку про середній бал?", "деканат / довідки студентів", "low"),
    ("Куди йти за виправленням помилки у наказі?", "деканат / довідки студентів", "medium"),
    ("Як замовити апостиль на додаток до диплома?", "документи про освіту", "medium"),
    ("Скільки коштує дублікат диплома?", "документи про освіту", "low"),
    ("Які документи потрібні для академвідпустки?", "переведення / поновлення / відрахування", "medium"),
    ("Які бали потрібні для подачі на Erasmus?", "академічна мобільність", "low"),
    ("Коли наступний дедлайн заявок на стажування?", "академічна мобільність", "low"),
    ("Чи є у КПІ безкоштовний психолог?", "соціальна / психологічна підтримка", "low"),
    ("Як отримати матеріальну допомогу студенту?", "соціальна / психологічна підтримка", "medium"),
    ("Як налаштувати корпоративну пошту в Outlook?", "мережа / пошта / інтернет", "low"),
    ("Чому VPN КПІ перестав працювати?", "мережа / пошта / інтернет", "high"),
    ("Як куратору додати студента в групу в кампусі?", "Електронний кампус", "medium"),
    ("Чому в кампусі немає доступу до моїх курсів?", "Електронний кампус", "high"),
    ("Які книги можна замовити онлайн через бібліотеку?", "бібліотека", "low"),
    ("Як отримати доступ до Web of Science?", "бібліотека", "medium"),
    ("Чи допомагає КПІ з пошуком житла іноземцям?", "міжнародні студенти", "low"),
    ("Як подати документи на студентську візу?", "міжнародні студенти", "medium"),
    ("Як замовити перепустку для гостя на захист дипломної?", "безпека / перепустки", "medium"),
    ("Куди телефонувати при пожежі в корпусі?", "безпека / перепустки", "high"),
    ("Як отримати платіжне доручення для оплати навчання?", "оплата навчання / фінанси", "medium"),
    ("Чому з моєї картки списали зайві кошти за навчання?", "оплата навчання / фінанси", "high"),
    ("До якого підрозділу йти з питанням про КПІ-стікери?", "інше / первинна маршрутизація", "low"),
]

HARD_QUESTIONS_BY_CATEGORY: dict[str, list[tuple[str, str] | tuple[str, str, str]]] = {
    "стипендія": [
        ("Чи переглянуть мою академічну стипендію, якщо я отримав 'добре' за один з модулів?", "medium"),
        ("Як вплине на стипендію перенесення іспиту через хворобу?", "medium"),
        ("Доброго дня! Я переселилась з гуртожитку в орендоване житло, і соціальна стипендія тепер не нараховується. Чи треба заново подавати документи, і де знайти зразок заяви?", "medium"),
        ("Вітаю! Минулого семестру я був академічним стипендіатом, цього семестру втратив через перерву. Чи можу я повернути академічну стипендію після здачі сесії, чи потрібно чекати наступного року?", "medium"),
        ("Як впливає перехід з контракту на бюджет на нарахування соціальної стипендії, якщо я подав документи ще будучи на контракті?", "medium"),
    ],
    "гуртожиток / проживання": [
        ("Чи можна заселитися в гуртожиток до початку навчального року?", "low"),
        ("Куди писати скаргу на адміністратора гуртожитку?", "high"),
        ("Доброго дня! Я орендувала кімнату через hostelpay, але адміністратор сказав, що це місце вже зайнято іншим студентом. Як вирішити цей конфлікт і отримати назад оплату?", "high"),
        ("Підкажіть, як офіційно оформити тимчасове проживання батьків у гуртожитку, якщо вони приїхали допомогти мені після операції?", "medium"),
    ],
    "вступ": [
        ("Чи можу я завантажити в електронний кабінет два документи про освіту, якщо обидва дійсні?", "low"),
        ("Куди звертатися, якщо документи з коледжу не приймаються в кабінеті вступника?", "high"),
        ("Доброго дня! Я абітурієнт, який хоче подати документи в КПІ, але система не показує мою спеціальність у списку. Як перевірити, чи я можу подавати документи на цю програму?", "medium"),
        ("Вітаю! Я подавав документи на бакалаврат через електронний кабінет, але система видала помилку 'Ваша заява не зареєстрована'. Поточний день — останній день подачі. Як швидко вирішити?", "high"),
        ("Чи можна змінити форму навчання після подання вступної заяви, якщо я вже подавав на денну, але передумав?", "medium"),
    ],
    "навчальний процес": [
        ("Як офіційно подати скаргу на викладача за необ'єктивне оцінювання?", "high"),
        ("Чи зараховуються модулі, складені дистанційно, якщо очно я не складав?", "medium"),
        ("Доброго дня! Викладач не з'являється на пари вже два тижні, не відповідає на повідомлення. Група не знає, чи буде складати екзамен. До кого звертатися?", "high"),
        ("Підкажіть, чи можу я подати заяву на ліквідацію академзаборгованості до наказу про відрахування, якщо я майже не встиг до дедлайну?", "high"),
    ],
    "деканат / довідки студентів": [
        ("Чи можна отримати довідку про навчання у вихідний день?", "low"),
        ("Куди звертатися, якщо у деканаті помилково оформили мене на іншу спеціальність?", "high"),
        ("Як підписати заяву про переведення, якщо декан у відрядженні два тижні?", "medium"),
        ("Доброго дня! Я подавала заяву в деканат тиждень тому, але мені не дали ні оригінал, ні копію. Деканат каже, що заяви немає в системі. Як це довести і подати знову?", "high"),
        ("Підкажіть, як отримати довідку про моє навчання, якщо я переведений із іншого ЗВО і ще не отримав студентського квитка КПІ?", "medium"),
    ],
    "документи про освіту": [
        ("Чи можна замовити переклад диплома через КПІ?", "low"),
        ("Куди звертатися, якщо в дублікаті диплома знайдено нову помилку?", "high"),
        ("Як отримати довідку про справжність диплома для роботодавця?", "medium"),
        ("Доброго дня! Я закінчив магістратуру 5 років тому, диплом отримав, але тепер мені потрібен оригінал додатка до нього (який я не забрав). Чи зберігається додаток в архіві КПІ?", "medium"),
        ("Вітаю! Я планую вступати в магістратуру за кордоном, для чого потрібен переклад диплома з апостилем. КПІ робить апостиль чи треба окремо в МОН?", "medium"),
    ],
    "переведення / поновлення / відрахування": [
        ("Як подати на переведення з іншого ЗВО, якщо я ще не отримав довідку про академрізницю?", "medium"),
        ("Чи зараховуються кредити після поновлення з академвідпустки?", "low"),
        ("Куди подавати оскарження наказу про відрахування у судовому порядку?", "high"),
        ("Доброго дня! Я не складав сесію 2 семестри, мене відрахували. Я виправив сімейні обставини і хочу поновитися. Який порядок поновлення з академзаборгованістю?", "high"),
        ("Вітаю! Я перевожусь з заочної на денну форму через зміну роботи. Які додаткові курси треба здати, і чи є можливість зарахувати кредити з заочної?", "medium"),
    ],
    "академічна мобільність": [
        ("Чи можна продовжити Erasmus на додатковий семестр?", "low"),
        ("Куди подавати learning agreement, якщо координатор кафедри у відпустці?", "high"),
        ("Доброго дня! Я повернулась з обміну, але мені відмовили у зарахуванні одного предмета. Аргумент — програма не співпадає. Як офіційно оскаржити це рішення?", "high"),
        ("Підкажіть, чи можна після Erasmus залишитися в приймаючому університеті на стажування за окремим грантом?", "low"),
    ],
    "соціальна / психологічна підтримка": [
        ("Чи допомагає університет знайти юридичну консультацію?", "low"),
        ("Куди йти, якщо я переживаю депресію через втрату родича?", "high"),
        ("Як долучитися до групи підтримки студентів-сиріт?", "medium"),
        ("Доброго дня! Я багатодітна мама-студентка, маю проблеми з суміщенням навчання та виховання дітей. Чи є в університеті відповідна підтримка для студентів-батьків?", "medium"),
        ("Вітаю! Я ВПО-студент із Маріуполя, потребую соціального супроводу. У мене немає документів про власність втраченого житла. Чи можу я отримати допомогу без них?", "high"),
    ],
    "мережа / пошта / інтернет": [
        ("Як змінити пароль до корпоративної пошти?", "low"),
        ("Куди писати, якщо мене заблокували в Moodle за невірний пароль?", "high"),
        ("Доброго дня! У моєму корпусі Wi-Fi доступний тільки в коридорах, в аудиторіях сигнал слабкий. Кому повідомити для покращення покриття?", "medium"),
        ("Підкажіть, як отримати службовий VPN для роботи з науковими базами з дому?", "medium"),
    ],
    "Електронний кампус": [
        ("Чи можна додати свій предмет у Електронний кампус?", "medium"),
        ("Куди писати, якщо в кампусі дублюються мої курси за минулий семестр?", "high"),
        ("Доброго дня! Я не можу побачити свою оцінку за курсову, хоча викладач каже, що вже виставив. Перевіряв через мобільний браузер і ноутбук. До кого звертатися?", "high"),
        ("Підкажіть, чи може куратор групи бачити проміжні оцінки студентів за модульні роботи?", "low"),
    ],
    "бібліотека": [
        ("Як замовити книгу з іншого ЗВО через міжбібліотечний абонемент?", "medium"),
        ("Куди звертатися, якщо книга, яку я повернув, продовжує бути в моєму абонементі?", "high"),
        ("Доброго дня! Я хочу опрацювати дисертації аспірантів КПІ за останні 5 років. Чи доступні вони у бібліотеці, чи мені треба звертатися до окремого архіву?", "medium"),
        ("Вітаю! Я викладач кафедри і хочу замовити підручник для викладання, якого ще немає в бібліотеці. Як ініціювати закупівлю книги?", "medium", "teacher"),
    ],
    "міжнародні студенти": [
        ("Як подати документи на стажування для іноземного студента?", "medium"),
        ("Куди звертатися щодо оформлення посвідки на проживання після зміни паспорта?", "high"),
        ("Доброго дня! Я іноземна студентка з Польщі, навчаюсь по обміну. У мене виникла проблема з продовженням реєстрації — українською мовою я не розумію форми ДМС. Чи допоможе КПІ?", "high"),
        ("Підкажіть, як легалізувати мій український диплом для роботи в Польщі після випуску?", "medium"),
    ],
    "безпека / перепустки": [
        ("Як замовити перепустку для зйомочної групи на захист дипломної?", "medium"),
        ("Куди телефонувати, якщо я бачу підозрілий пакет біля корпусу?", "high"),
        ("Доброго дня! Я викладач, у мене в лабораторії пропало дослідницьке обладнання. Я повідомив керівника, але офіційного запису немає. Куди звертатися щодо інциденту?", "high", "teacher"),
        ("Підкажіть, чи можу я отримати доступ до корпусу о 6 ранку для виконання експерименту?", "low"),
    ],
    "оплата навчання / фінанси": [
        ("Чи можна оплатити навчання криптовалютою через посередника?", "low"),
        ("Куди писати, якщо банк оплатив контракт, але рахунок не закрито?", "high"),
        ("Доброго дня! Я перевелася на бюджет з контрактника, але банк продовжує знімати оплату за автоплатежем. Як зупинити списання і повернути вже сплачені кошти?", "high"),
        ("Підкажіть, як змінити графік оплати, якщо я виявив матеріальні труднощі і не можу заплатити одразу всю суму контракту?", "medium"),
    ],
    "інше / первинна маршрутизація": [
        ("Чи можна замовити віртуальну екскурсію в КПІ для школярів?", "low"),
        ("Куди звертатися щодо оренди аудиторії для зовнішнього гуртка школярів?", "low"),
        ("Доброго дня! Я хочу запропонувати ідею для покращення навчальних просторів КПІ. Це не питання навчального процесу. До якого підрозділу подавати пропозицію?", "low"),
        ("Підкажіть, чи можу я отримати акредитаційну довідку про КПІ для подачі в посольство?", "medium"),
    ],
}


def generated_examples() -> list[dict]:
    examples = [
        {
            "difficulty": "simple",
            "role": "student",
            "text": text,
            "expected_category": category,
            "expected_priority": priority,
        }
        for text, category, priority in SIMPLE_QUESTIONS
    ]
    for category, category_examples in HARD_QUESTIONS_BY_CATEGORY.items():
        for example in category_examples:
            text, priority, *role = example
            examples.append(
                {
                    "difficulty": "hard",
                    "role": role[0] if role else "student",
                    "text": text,
                    "expected_category": category,
                    "expected_priority": priority,
                }
            )
    return examples


def accuracy(items: list[dict], expected_key: str, predicted_key: str) -> float:
    if not items:
        return 0.0
    return sum(item[expected_key] == item[predicted_key] for item in items) / len(items)


def validate_examples(examples: list[dict], category_names: list[str]) -> None:
    counts = Counter(item["difficulty"] for item in examples)
    if counts != {"simple": 30, "hard": 70}:
        raise ValueError(f"Expected 30 simple and 70 hard questions, got {counts}.")
    unknown = sorted({item["expected_category"] for item in examples} - set(category_names))
    if unknown:
        raise ValueError(f"Unknown expected categories: {unknown}")
    texts = [" ".join(item["text"].casefold().split()) for item in examples]
    if len(texts) != len(set(texts)):
        raise ValueError("Generated questions contain duplicate text.")


def classify_examples(
    examples: list[dict],
    config: dict,
    category_items: list[CatalogItem],
) -> tuple[list[dict], list[dict]]:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(config["base_model"], trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        config["base_model"],
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base_model, config["output_dir"])
    model.eval()

    results: list[dict] = []
    failures: list[dict] = []
    for index, example in enumerate(examples, start=1):
        messages = build_classifier_messages(
            role=example["role"],
            text=example["text"],
            categories=category_items,
        )
        prompt = apply_classifier_chat_template(tokenizer, messages, add_generation_prompt=True)
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            output = model.generate(
                **inputs,
                max_new_tokens=160,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        raw = tokenizer.decode(generated, skip_special_tokens=True)
        try:
            parsed = extract_json(raw)
            results.append(
                {
                    **example,
                    "index": index,
                    "predicted_category": parsed.get("category", ""),
                    "predicted_priority": parsed.get("priority", ""),
                    "raw_output": raw,
                }
            )
        except Exception as exc:
            failures.append({**example, "index": index, "raw_output": raw, "error": str(exc)})
        if index % 10 == 0 or index == len(examples):
            print(f"classified {index}/{len(examples)}", file=sys.stderr, flush=True)
    return results, failures


def build_summary(
    *,
    examples: list[dict],
    results: list[dict],
    failures: list[dict],
    category_names: list[str],
    questions_path: Path,
    results_path: Path,
) -> dict:
    by_difficulty: dict[str, list[dict]] = defaultdict(list)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for item in results:
        by_difficulty[item["difficulty"]].append(item)
        by_category[item["expected_category"]].append(item)

    category_mismatches = [
        item for item in results if item["expected_category"] != item["predicted_category"]
    ]
    priority_mismatches = [
        item for item in results if item["expected_priority"] != item["predicted_priority"]
    ]

    return {
        "input_file": str(questions_path),
        "results_file": str(results_path),
        "count": len(examples),
        "parsed": len(results),
        "parse_failures": len(failures),
        "category_accuracy": round(accuracy(results, "expected_category", "predicted_category"), 4),
        "priority_accuracy": round(accuracy(results, "expected_priority", "predicted_priority"), 4),
        "difficulty": {
            difficulty: {
                "count": len(items),
                "category_accuracy": round(
                    accuracy(items, "expected_category", "predicted_category"),
                    4,
                ),
                "priority_accuracy": round(
                    accuracy(items, "expected_priority", "predicted_priority"),
                    4,
                ),
            }
            for difficulty, items in sorted(by_difficulty.items())
        },
        "category_counts": dict(Counter(item["expected_category"] for item in examples).most_common()),
        "predicted_category_counts": dict(
            Counter(item["predicted_category"] for item in results).most_common()
        ),
        "category_accuracy_by_expected_category": {
            category: {
                "count": len(items),
                "accuracy": round(accuracy(items, "expected_category", "predicted_category"), 4),
                "errors": sum(
                    item["expected_category"] != item["predicted_category"] for item in items
                ),
            }
            for category, items in sorted(by_category.items())
        },
        "category_mismatches": [
            {
                "index": item["index"],
                "difficulty": item["difficulty"],
                "text": item["text"],
                "expected_category": item["expected_category"],
                "predicted_category": item["predicted_category"],
                "expected_priority": item["expected_priority"],
                "predicted_priority": item["predicted_priority"],
            }
            for item in category_mismatches
        ],
        "priority_mismatch_count": len(priority_mismatches),
        "unknown_categories": sorted(
            {item["predicted_category"] for item in results if item["predicted_category"] not in category_names}
        ),
        "raw_outputs_contain_confidence": any("confidence" in item["raw_output"] for item in results),
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("ml/configs/train_lora.yaml"))
    parser.add_argument("--questions-output", type=Path, default=Path("ml/outputs/generated_100_eval_questions.jsonl"))
    parser.add_argument("--results-output", type=Path, default=Path("ml/outputs/generated_100_eval_results.json"))
    parser.add_argument("--metrics-output", type=Path, default=Path("ml/outputs/generated_100_eval_metrics.json"))
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    catalog_path = Path(config["catalog_path"])
    category_items = read_catalog_items(catalog_path)
    category_names = [item.name for item in category_items]
    examples = generated_examples()
    validate_examples(examples, category_names)

    args.questions_output.parent.mkdir(parents=True, exist_ok=True)
    args.questions_output.write_text(
        "\n".join(json.dumps(example, ensure_ascii=False) for example in examples) + "\n",
        encoding="utf-8",
    )

    results, failures = classify_examples(examples, config, category_items)
    summary = build_summary(
        examples=examples,
        results=results,
        failures=failures,
        category_names=category_names,
        questions_path=args.questions_output,
        results_path=args.results_output,
    )
    args.results_output.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.metrics_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
