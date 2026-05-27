# Голосова довідкова КПІ

Дипломний проєкт: вебзастосунок і телефонна довідкова для автоматичної відповіді на питання студентів та викладачів КПІ.

Головний сценарій системи - голосова довідка. Користувач ставить питання з браузера, SIP-клієнта або телефону. Система записує аудіо, розпізнає мовлення, знаходить релевантну інформацію в локальній базі знань КПІ, формує відповідь мовною моделлю Qwen 4B і озвучує її українським TTS.

У проєкті також залишена суміжна підсистема заявок: користувач може створити звернення, а LoRA-класифікатор визначає категорію, пріоритет і відповідальний підрозділ.

## Архітектура

Повний телефонний шлях:

```text
Телефон або браузерний SIP
  -> Asterisk PBX
  -> запис питання у WAV
  -> FastAPI /api/v1/phone-assistant/ask-text
  -> faster-whisper STT
  -> пошук у локальній базі знань КПІ
  -> Qwen через llama-server / OpenAI-compatible API
  -> Edge TTS
  -> ffmpeg-конвертація в Asterisk WAV
  -> Asterisk програє відповідь
```

Для зменшення паузи перед відповіддю телефонний bridge працює в progressive TTS режимі: backend спочатку повертає текст відповіді, PBX-сценарій синтезує перший аудіофрагмент, одразу запускає його в дзвінок, а решту відповіді готує паралельно.

## Швидкий запуск

Потрібні:

- Docker Desktop;
- Python 3.11+;
- Node.js і npm;
- ffmpeg;
- `llama-server` з `llama.cpp` для генерації відповідей через локальну Qwen 4B модель.

Перший запуск після клонування:

```powershell
git clone https://github.com/PudchenkoAlexei/Dyplom.git
cd Dyplom
.\scripts\start.ps1
```

Скрипт `start.ps1`:

- створює `.env` з `.env.example`, якщо його ще немає;
- встановлює backend і frontend залежності;
- запускає PostgreSQL і Asterisk через Docker Compose;
- застосовує Alembic-міграції;
- заповнює базові категорії, підрозділи й тестових користувачів;
- запускає локальний `llama-server` на `8080`;
- запускає backend на `8000` і frontend на `3000`.

Адреси:

```text
Frontend: http://127.0.0.1:3000/login
Backend:  http://127.0.0.1:8000/health
PBX:      SIP 127.0.0.1:5060, WebRTC ws://127.0.0.1:8088/ws, номер довідкової 7000
LLM:      http://127.0.0.1:8080/v1
```

Корисні команди:

```powershell
.\scripts\start.ps1 -NoOpen
.\scripts\start.ps1 -SkipInstall
.\scripts\start.ps1 -SkipPbx
.\scripts\start.ps1 -SkipLlama
.\scripts\status.ps1
.\scripts\stop.ps1
```

Якщо PowerShell блокує запуск скриптів:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

## Запуск Моделі Для Довідки

`start.ps1` запускає `llama-server` автоматично. За замовчуванням використовується GGUF-модель Qwen 4B з alias, який очікує телефонна довідкова:

```powershell
.\scripts\start.ps1 -NoOpen
```

Якщо потрібно запустити вебзастосунок без локальної мовної моделі:

```powershell
.\scripts\start.ps1 -SkipLlama
```

Окремий запуск inference server потрібен тільки для ручного тестування моделі або нестандартної конфігурації.

Якщо використовується базова GGUF-модель з Hugging Face:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_llama_cpp.ps1 -Alias "Qwen3-4B-KPI-Assistant-Q4_K_M"
```

Якщо є локально підготовлена GGUF-модель довідки:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_llama_cpp.ps1 `
  -Model ".\ml\models\qwen3-kpi-assistant-gguf\Qwen3-4B-KPI-Assistant-Q4_K_M.gguf" `
  -Alias "Qwen3-4B-KPI-Assistant-Q4_K_M"
```

Сервер слухає:

```text
http://127.0.0.1:8080/v1
```

Зупинка:

```powershell
.\scripts\stop.ps1
```

## Тестові Користувачі

```text
student@kpi.ua   / StudentPassword123!
teacher@kpi.ua   / TeacherPassword123!
operator1@kpi.ua / OperatorPassword123!
operator2@kpi.ua / OperatorPassword123!
admin@kpi.ua     / AdminPassword123!
```

## Телефонна Довідкова

Найпростіший спосіб перевірки:

1. Запустити застосунок:

```powershell
.\scripts\start.ps1 -NoOpen
```

2. Відкрити вебзастосунок, увійти як студент або викладач, перейти в розділ `Довідкова` і натиснути `Подзвонити з додатку`.

Браузер реєструється в Asterisk як WebRTC SIP-клієнт `7002`, дзвонить на номер `7000`, а PBX обробляє дзвінок як звичайну телефонну лінію.

Альтернативно можна підключитися через SIP softphone:

```text
SIP server: 127.0.0.1
Port:       5060
Login:      7001
Password:   KpiPhone7001!
Transport:  UDP
Number:     7000
```

Для дзвінка з реального телефону в локальній мережі треба виставити у `.env` IP комп'ютера з Asterisk:

```text
KPI_PBX_PUBLIC_IP=192.168.x.x
```

Для production обов'язково змініть `PBX_INTERNAL_TOKEN`, SIP/WebRTC паролі та публічні адреси.

## Основні Налаштування

STT:

```text
WHISPER_MODEL_SIZE=medium
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
WHISPER_BEAM_SIZE=3
WHISPER_DOMAIN_HINTS_ENABLED=true
WHISPER_TRANSCRIPTION_CORRECTIONS_ENABLED=true
```

Класифікатор заявок:

```text
LLM_BASE_MODEL=Qwen/Qwen3-4B-Instruct-2507
LORA_ADAPTER_PATH=ml/models/qwen3-kpi-lora-4b
CLASSIFIER_QUANTIZATION=4bit
```

Вебдовідка:

```text
VOICE_ASSISTANT_USE_LLM=true
VOICE_ASSISTANT_INFERENCE_ENGINE=transformers
VOICE_ASSISTANT_MODEL=Qwen/Qwen3-4B-Instruct-2507
VOICE_ASSISTANT_AI_GUIDED_RETRIEVAL=true
VOICE_ASSISTANT_MAX_NEW_TOKENS=900
```

Телефонна довідка:

```text
VOICE_ASSISTANT_PHONE_USE_LLM=true
VOICE_ASSISTANT_PHONE_INFERENCE_ENGINE=openai_compatible
VOICE_ASSISTANT_PHONE_MODEL=Qwen3-4B-KPI-Assistant-Q4_K_M
VOICE_ASSISTANT_PHONE_OPENAI_BASE_URL=http://127.0.0.1:8080/v1
VOICE_ASSISTANT_PHONE_MAX_NEW_TOKENS=0
VOICE_ASSISTANT_PHONE_AI_GUIDED_RETRIEVAL=false
VOICE_ASSISTANT_PHONE_MAX_CONTEXT_ITEMS=1
```

TTS:

```text
VOICE_ASSISTANT_TTS_ENABLED=true
VOICE_ASSISTANT_TTS_VOICE=uk-UA-PolinaNeural
VOICE_ASSISTANT_TTS_RATE=+0%
VOICE_ASSISTANT_TTS_MAX_CHARS=0
```

`VOICE_ASSISTANT_TTS_MAX_CHARS=0` означає, що текст перед озвученням не обрізається.

## База Знань

Основна база знань:

```text
backend/app/data/kpi_faq_knowledge_base.json
```

Вона містить структуровані записи з полями:

```text
id
title
question
answer
source_url
tags
```

Пошук у базі знань виконується backend-ом. Він враховує токени, основи слів, n-grams, збіг фраз і складені назви тем, наприклад `академ різниця` -> `Академрізниця`.

AI-guided retrieval режим дозволяє моделі сформувати пошукові запити для локального інструмента `search_kpi_faq`, але сама модель не шукає інформацію в інтернеті й не змінює базу знань.

Оновлення бази знань із сайту КПІ:

```powershell
python scripts/build_kpi_faq_knowledge_base.py
```

## Структура Проєкту

```text
backend/           FastAPI API, БД, STT, TTS, RAG, класифікатор
frontend/          Next.js інтерфейс користувача й браузерний SIP-клієнт
ml/                дані, конфіги, навчання й оцінювання моделей
pbx/               Asterisk PBX, SIP/WebRTC конфіги, bridge-скрипти
scripts/           PowerShell-скрипти запуску, статусу й зупинки
tools/             локальні бінарні інструменти, наприклад llama.cpp
docker-compose.yml PostgreSQL та Asterisk для локального запуску
.env.example       приклад змінних середовища
```

Ключові backend-модулі:

```text
backend/app/api/v1/phone_assistant.py   API для телефонної довідки
backend/app/api/v1/voice_assistant.py   API для вебдовідки
backend/app/services/voice_assistant.py RAG, prompts, Qwen inference, fallback
backend/app/services/stt.py             faster-whisper і domain hints
backend/app/services/tts.py             Edge TTS і підготовка тексту до озвучення
backend/app/services/classifier.py      LoRA-класифікатор заявок
backend/app/models/phone.py             журнал телефонних дзвінків
backend/app/models/ticket.py            заявки, аудіо, транскрипти, події
```

Ключові frontend-модулі:

```text
frontend/src/app/assistant/page.tsx          сторінка голосової довідки
frontend/src/components/PbxCallButton.tsx    браузерний SIP/WebRTC дзвінок
frontend/src/components/AudioRecorder.tsx    запис голосу й browser speech transcript
frontend/src/lib/ticketsApi.ts               API-клієнт заявок і довідки
frontend/src/types/domain.ts                 TypeScript доменні типи
```

Ключові PBX-модулі:

```text
pbx/asterisk/extensions.conf        dialplan дзвінка на 7000
pbx/asterisk/pjsip.conf             SIP/WebRTC endpoints 7001 і 7002
pbx/scripts/kpi_record_question.py  EAGI-запис питання з тишею на кінці
pbx/scripts/kpi_phone_assistant.py  bridge між Asterisk і backend
pbx/scripts/kpi_wait_for_file.py    очікування другого TTS-фрагмента
```

## Навчання Моделей

Класифікатор заявок:

```text
ml/data/curated/tickets_curated.jsonl
ml/configs/catalog.yaml
ml/configs/train_lora.yaml
ml/training/train_lora.py
```

Запуск:

```powershell
python ml/training/train_lora.py --config ml/configs/train_lora.yaml
```

Підготовка корпусу для довідки:

```powershell
python ml/scripts/build_assistant_dapt_corpus.py
python ml/scripts/validate_assistant_dapt_corpus.py
```

Full domain-adaptive continued pretraining:

```powershell
python ml/training/train_assistant_dapt.py --config ml/configs/train_assistant_dapt.yaml
```

Цей режим навчає всі параметри моделі й потребує значно більше GPU-пам'яті, тому він більше підходить для серверу кафедри, ніж для слабкого локального ПК.

Локальне QLoRA-доадаптування довідки:

```powershell
python ml/training/train_assistant_qlora.py --config ml/configs/train_assistant_qlora.yaml
```

Злиття QLoRA-адаптера з базовою HF-моделлю:

```powershell
python ml/scripts/merge_assistant_qlora.py
```

Директорії `ml/models/` і `ml/outputs/` не комітяться в git, бо містять великі локальні моделі, checkpoints, GGUF-файли та логи експериментів.

## Перевірки

Backend:

```powershell
cd backend
python -m pytest app/tests
```

Frontend:

```powershell
cd frontend
npm run typecheck
npm run lint
```

ML-дані:

```powershell
python ml/scripts/validate_dataset.py
python ml/scripts/validate_assistant_dapt_corpus.py
```

Dry-run підготовки навчання без завантаження моделі:

```powershell
python ml/training/train_assistant_dapt.py --dry-run
python ml/training/train_assistant_qlora.py --dry-run
```

## Дані Та Безпека

- `.env` не комітиться в git.
- Аудіозаписи зберігаються в `backend/storage/audio/`.
- Журнал телефонних звернень зберігається в таблиці `phone_assistant_calls`.
- Для production треба змінити JWT secret, PBX token, SIP/WebRTC паролі, CORS/hosts і cookie security.
- Для кафедрального серверу бажано додати політику очищення старих аудіо та логів.

## Поточні Обмеження

- База знань зберігається як JSON-файл, а не редагується через адмін-панель.
- Edge TTS залежить від зовнішнього сервісу Microsoft.
- Телефонна відповідь залежить від доступності `llama-server`, якщо ввімкнений OpenAI-compatible inference.
- У режимі phone context навмисно стискається до найрелевантніших джерел, щоб скоротити паузу перед відповіддю.
