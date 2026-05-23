# Система обробки голосових звернень

Дипломний проєкт: веб-застосунок для створення, розпізнавання, класифікації та операторської обробки звернень.

Користувач може подати звернення голосом, аудіофайлом або текстом. Система формує текст звернення, класифікує його мовною моделлю `Qwen/Qwen3-1.7B` з LoRA-адаптером, визначає категорію та пріоритет, після чого передає заявку в операторську чергу.

## Швидкий запуск

Потрібні:

- Docker Desktop;
- Python 3.11+;
- Node.js і npm.

Перший запуск після клонування:

```powershell
git clone https://github.com/PudchenkoAlexei/Dyplom.git
cd Dyplom
.\scripts\start.ps1
```

Скрипт автоматично:

- створює `.env` з `.env.example`, якщо його ще немає;
- встановлює backend і frontend залежності;
- запускає PostgreSQL через Docker Compose;
- застосовує Alembic-міграції;
- заповнює базові категорії, підрозділи й тестових користувачів;
- запускає backend і frontend.

Адреси:

```text
Frontend: http://127.0.0.1:3000/login
Backend:  http://127.0.0.1:8000/health
PBX:      SIP 127.0.0.1:5060, WebRTC ws://127.0.0.1:8088/ws, номер довідкової 7000
```

Корисні команди:

```powershell
.\scripts\start.ps1 -NoOpen
.\scripts\start.ps1 -SkipInstall
.\scripts\start.ps1 -SkipPbx
.\scripts\status.ps1
.\scripts\stop.ps1
```

Якщо PowerShell блокує запуск скриптів:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

## Тестові користувачі

```text
student@kpi.ua   / StudentPassword123!
teacher@kpi.ua   / TeacherPassword123!
operator1@kpi.ua / OperatorPassword123!
operator2@kpi.ua / OperatorPassword123!
admin@kpi.ua     / AdminPassword123!
```

## Телефонна довідкова через PBX

Голосова довідкова може працювати не тільки зі сторінки `/assistant`, а й через
телефонний дзвінок на PBX-сервер Asterisk.

Локальний сценарій:

1. Запустіть проєкт:

```powershell
.\scripts\start.ps1 -NoOpen
```

2. Найпростіший варіант для користувача: зайдіть у вебзастосунок, відкрийте
   розділ `Довідкова` і натисніть `Подзвонити з додатку`.

Браузер реєструється в Asterisk як WebRTC SIP-клієнт `7002`, дзвонить на
номер `7000`, а PBX обробляє дзвінок так само, як звичайну телефонну лінію.

3. Альтернативно можна підключитися через SIP softphone (MicroSIP, Zoiper,
   Linphone):

```text
SIP server: 127.0.0.1
Port:       5060
Login:      7001
Password:   KpiPhone7001!
Transport:  UDP
```

4. Зателефонуйте на номер `7000`.

Asterisk відповідає на дзвінок, подає сигнал, записує питання у WAV, передає
його в backend endpoint `/api/v1/phone-assistant/ask`, backend розпізнає аудіо,
формує відповідь через базу знань довідкової, генерує TTS і повертає аудіо для
програвання у телефон.

Змінна `PBX_INTERNAL_TOKEN` у `.env` має збігатися з токеном, який контейнер
Asterisk передає в backend. У development використовується значення за
замовчуванням, але для production його потрібно змінити.

Для дзвінка з браузера frontend використовує змінні:

```text
NEXT_PUBLIC_PBX_WS_URL=ws://127.0.0.1:8088/ws
NEXT_PUBLIC_PBX_SIP_DOMAIN=127.0.0.1
NEXT_PUBLIC_PBX_WEBRTC_EXTENSION=7002
NEXT_PUBLIC_PBX_WEBRTC_PASSWORD=KpiWebPhone7002!
NEXT_PUBLIC_PBX_ASSISTANT_NUMBER=7000
```

## Структура проєкту

```text
frontend/          Next.js frontend
backend/           FastAPI backend
ml/                датасет, конфіги, навчання LoRA-моделі
pbx/               Asterisk PBX, SIP-конфіги та bridge-скрипт телефонної довідкової
scripts/           PowerShell-скрипти запуску та зупинки
docker-compose.yml PostgreSQL та Asterisk для локального запуску
.env.example       приклад змінних середовища
```

Основні backend-модулі:

```text
backend/app/api/v1/       API endpoints
backend/app/models/       SQLAlchemy models
backend/app/schemas/      Pydantic schemas
backend/app/services/     STT, classifier, storage, events
backend/app/security/     auth, tokens, passwords, rate limiting
backend/alembic/          міграції бази даних
```

Основні frontend-модулі:

```text
frontend/src/app/          сторінки Next.js
frontend/src/components/   UI-компоненти
frontend/src/lib/          API client, auth, TanStack Query
frontend/src/types/        TypeScript типи
```

## Модель

Параметри ML-компонента задаються в `.env`:

```text
LLM_BASE_MODEL=Qwen/Qwen3-1.7B
LORA_ADAPTER_PATH=ml/models/qwen3-kpi-lora
```

Голосова довідкова може працювати в AI-guided retrieval режимі: модель спершу формує
пошукові запити для інструмента `search_kpi_faq`, backend виконує пошук у локальній
FAQ-базі, після чого модель формує відповідь на основі знайдених джерел.
Для генерації відповідей вона може використовувати окрему сильнішу instruct-модель,
не змінюючи базову модель LoRA-класифікатора.

```text
VOICE_ASSISTANT_MODEL=Qwen/Qwen3-4B-Instruct-2507
VOICE_ASSISTANT_INFERENCE_ENGINE=transformers
VOICE_ASSISTANT_REUSE_CLASSIFIER_MODEL=false
VOICE_ASSISTANT_AI_GUIDED_RETRIEVAL=true
VOICE_ASSISTANT_SEARCH_QUERY_COUNT=3
VOICE_ASSISTANT_SEARCH_CANDIDATES=8
VOICE_ASSISTANT_MIN_CONFIDENCE=0.5
VOICE_ASSISTANT_SOFT_MIN_CONFIDENCE=0.32
VOICE_ASSISTANT_MAX_CONTEXT_ITEMS=5
VOICE_ASSISTANT_CONTEXT_SCORE_RATIO=0.65
VOICE_ASSISTANT_MAX_NEW_TOKENS=900
VOICE_ASSISTANT_TTS_MAX_CHARS=0
```

`VOICE_ASSISTANT_TTS_MAX_CHARS=0` вимикає обрізання тексту перед озвученням.

Для телефонної довідки можна винести генерацію з backend-процесу в окремий
OpenAI-compatible inference server, наприклад `llama-server` з `llama.cpp`:

```text
VOICE_ASSISTANT_PHONE_INFERENCE_ENGINE=openai_compatible
VOICE_ASSISTANT_PHONE_MODEL=Qwen/Qwen3-4B-GGUF:Q4_K_M
VOICE_ASSISTANT_PHONE_OPENAI_BASE_URL=http://127.0.0.1:8080/v1
VOICE_ASSISTANT_PHONE_OPENAI_API_KEY=local
VOICE_ASSISTANT_PHONE_WARMUP_ON_STARTUP=false
```

Після встановлення `llama.cpp` і появи `llama-server` у `PATH` можна запустити
локальний сервер моделі:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_llama_cpp.ps1
```

Скрипт за замовчуванням стартує `Qwen/Qwen3-4B-GGUF:Q4_K_M` на
`http://127.0.0.1:8080/v1`. Зупинка:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop_llama_cpp.ps1
```

Навчальні файли:

```text
ml/data/curated/tickets_curated.jsonl
ml/configs/train_lora.yaml
ml/training/train_lora.py
```

LoRA-адаптер не варто комітити в репозиторій, якщо він великий. Для повного локального запуску класифікації модель має бути доступна за шляхом з `LORA_ADAPTER_PATH`.
