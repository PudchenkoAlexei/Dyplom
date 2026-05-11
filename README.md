# Система обробки голосових звернень на основі мовних моделей

Дипломний проект: веб-система для приймання, розпізнавання, класифікації та операторської обробки голосових звернень до університетської довідкової служби.

Користувач студент або викладач створює звернення голосом, аудіофайлом або текстом. Система зберігає аудіозапис, формує текст звернення, класифікує його до категорії, визначає пріоритет і передає в операторську чергу. Оператор бачить автора, групу студента, текст, аудіо, категорію, підрозділ, може взяти заявку в роботу, виправити класифікацію, відповісти користувачу, закрити або видалити заявку.

## Швидкий запуск

Перед запуском потрібні Docker Desktop, Python 3.11+ та Node.js.

## Перший запуск після git clone

Після клонування репозиторію залежності не зберігаються всередині проекту. Це нормально: `node_modules`, `.venv`, `.next`, `.env`, модельні артефакти, логи й кеші не додаються в GitHub.

Типовий перший запуск:

```powershell
git clone https://github.com/<your-username>/<repo-name>.git
cd <repo-name>
.\scripts\start.ps1
```

Під час першого запуску скрипт сам:

- створить `.env` з `.env.example`;
- створить `backend\.venv`, якщо backend-залежності ще не встановлені;
- виконає `pip install -e ".[dev]"`;
- виконає `npm install`, якщо немає `frontend\node_modules`;
- запустить PostgreSQL;
- застосує міграції;
- заповнить базові категорії, підрозділи і тестових користувачів;
- запустить backend і frontend.

Готовий LoRA-адаптер не зберігається в GitHub. Щоб класифікація працювала після клонування, потрібно або навчити модель:

```powershell
python ml\training\train_lora.py --config ml\configs\train_lora.yaml
```

або покласти вже навчений адаптер у:

```text
ml/models/qwen3-kpi-lora
```

Запуск усього проекту:

```powershell
.\scripts\start.ps1
```

Скрипт автоматично:

- створює `.env` з `.env.example`, якщо його ще немає;
- запускає Docker Desktop, якщо Docker ще не готовий;
- запускає PostgreSQL через Docker Compose;
- чекає, поки база даних стане `healthy`;
- застосовує Alembic-міграції;
- оновлює seed-дані: категорії, підрозділи і тестових користувачів;
- запускає backend на `127.0.0.1:8000`;
- запускає frontend на `127.0.0.1:3000`;
- відкриває сторінку входу в браузері.

Якщо PowerShell блокує запуск скриптів:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Відкрити сайт вручну:

```text
http://127.0.0.1:3000/login
```

API health check:

```text
http://127.0.0.1:8000/health
```

Зупинка проекту:

```powershell
.\scripts\stop.ps1
```

Перевірка поточного стану:

```powershell
.\scripts\status.ps1
```

Корисні параметри запуску:

```powershell
.\scripts\start.ps1 -NoOpen
.\scripts\start.ps1 -SkipInstall
```

`-NoOpen` не відкриває браузер автоматично.  
`-SkipInstall` пропускає перевірку і встановлення залежностей.

Логи локального запуску зберігаються в `.run/`.

Важливо для GitHub: `.env`, `.run/`, `node_modules/`, `.next/`, `ml/models/`, `ml/outputs/` і завантажені аудіофайли не додаються в репозиторій. Після клонування проекту LoRA-адаптер потрібно або навчити командою з розділу ML, або окремо покласти в шлях `ml/models/qwen3-kpi-lora`.

## Тестові користувачі

```text
student@kpi.ua / StudentPassword123!
teacher@kpi.ua / TeacherPassword123!
operator1@kpi.ua / OperatorPassword123!
operator2@kpi.ua / OperatorPassword123!
admin@kpi.ua / AdminPassword123!
```

Адміністративної сторінки в інтерфейсі немає, але роль `admin` має доступ до операторської черги та адміністративних API.

## Архітектура

Проект поділений на чотири основні частини:

```text
frontend  -> Next.js інтерфейс користувача та оператора
backend   -> FastAPI API, авторизація, заявки, аудіо, ML-інтеграція
ml        -> датасет, конфіги, навчання LoRA, оцінювання моделі
postgres  -> основна база даних
```

Основний потік обробки заявки:

```text
Студент / викладач
  -> записує голосове звернення або вводить текст
  -> frontend передає аудіо та/або текст у backend
  -> backend створює чернетку заявки
  -> faster-whisper розпізнає аудіо, якщо текст не був отриманий у браузері
  -> користувач надсилає заявку
  -> Qwen3 + LoRA класифікує категорію та пріоритет
  -> backend визначає підрозділ за каталогом категорій
  -> заявка потрапляє в операторську чергу
  -> оператор бере заявку в роботу атомарним SQL-оновленням
  -> оператор відповідає, змінює класифікацію або закриває заявку
```

Backend не використовує keyword-based виправлення категорій. Категорію визначає мовна модель, а підрозділ береться з каталогу після вибору категорії. Це потрібно, щоб модель не вигадувала неіснуючі підрозділи.

## База даних

Використовується PostgreSQL та Alembic migrations.

Основні таблиці:

- `users` - користувачі, ролі, hash паролів, ПІБ, група студента;
- `refresh_tokens` - refresh-токени у вигляді hash;
- `tickets` - заявки, статус, автор, оператор, категорія, підрозділ, пріоритет;
- `ticket_audio` - шлях до аудіофайлу, MIME type, розмір, тривалість;
- `ticket_transcripts` - сирий і відредагований текст звернення;
- `ticket_messages` - відповіді оператора і повідомлення користувача;
- `ticket_events` - журнал подій заявки;
- `categories` - категорії звернень;
- `departments` - підрозділи маршрутизації;
- `model_versions` і `model_predictions` - інформація про ML-модель і результати класифікації.

Захоплення заявки оператором зроблено атомарно: якщо два оператори одночасно натиснуть "взяти в роботу", заявку отримає тільки один.

## ML-компонент

Модель класифікує звернення у структурований JSON:

```json
{
  "category": "стипендія",
  "priority": "medium"
}
```

Підрозділ не генерується моделлю. Backend бере його з каталогу `ml/configs/catalog.yaml`.

Поточна ML-схема:

- базова модель: `Qwen/Qwen3-1.7B`;
- метод донавчання: LoRA;
- адаптер: `ml/models/qwen3-kpi-lora`;
- датасет: `ml/data/curated/tickets_curated.jsonl`;
- 16 категорій;
- 60 прикладів на категорію;
- 960 прикладів загалом;
- split: 800 train, 80 validation, 80 test;
- пріоритети: `low`, `medium`, `high`.

Поточні метрики адаптера:

```text
test split:
category accuracy = 0.875
priority accuracy = 0.75

100 generated questions:
category accuracy = 0.91
priority accuracy = 0.78
```

Навчання та оцінювання:

```powershell
python ml\scripts\build_curated_dataset.py
python ml\scripts\validate_dataset.py
python ml\training\train_lora.py --config ml\configs\train_lora.yaml
python ml\training\evaluate_classifier.py --config ml\configs\train_lora.yaml --split test --output ml\outputs\evaluation_metrics.json
```

## Використані інструменти

Backend:

- Python;
- FastAPI;
- SQLAlchemy Async;
- Alembic;
- PostgreSQL;
- PyJWT;
- pwdlib / Argon2 для hash паролів;
- faster-whisper для server-side speech-to-text;
- aiofiles для збереження аудіофайлів;
- pytest і ruff для перевірки.

Frontend:

- Next.js;
- React;
- TypeScript;
- lucide-react;
- Web Speech API для live-транскрипції у браузері;
- MediaRecorder API для запису аудіо;
- ESLint і TypeScript typecheck.

ML:

- PyTorch;
- Transformers;
- PEFT;
- LoRA;
- Qwen3;
- datasets;
- scikit-learn для оцінювання метрик.

Інфраструктура:

- Docker Desktop;
- Docker Compose;
- PostgreSQL container;
- PowerShell scripts для локального запуску;
- локальні `.env` конфіги.

## Структура проекту

```text
backend/
  alembic/                 міграції БД
  app/
    api/v1/                API endpoints
    core/                  конфігурація та довідник груп
    db/                    сесія БД та seed-дані
    models/                SQLAlchemy models
    schemas/               Pydantic schemas
    security/              паролі, токени, role dependencies
    services/              STT, classifier, audio storage, events
    tests/                 backend-тести
  storage/audio/           локальне сховище аудіо

frontend/
  src/app/                 сторінки Next.js
  src/components/          UI-компоненти
  src/lib/                 API client, auth, labels, profile helpers
  src/types/               TypeScript domain types

ml/
  configs/                 каталог категорій і конфіг навчання
  data/curated/            фінальний curated dataset
  models/                  LoRA adapter
  outputs/                 метрики, результати оцінювання, логи навчання
  scripts/                 генерація і валідація датасету
  training/                навчання та оцінювання моделі

scripts/
  start.ps1                запуск Docker, БД, backend і frontend
  stop.ps1                 зупинка локального проекту
  status.ps1               перевірка поточного стану
```

## Перевірка

Backend tests:

```powershell
cd backend
python -m pytest
```

Frontend:

```powershell
cd frontend
npm run lint
npm run typecheck
npm run build
```

ML dataset:

```powershell
python ml\scripts\validate_dataset.py
```
