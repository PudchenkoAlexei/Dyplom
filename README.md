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
```

Корисні команди:

```powershell
.\scripts\start.ps1 -NoOpen
.\scripts\start.ps1 -SkipInstall
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

## Структура проєкту

```text
frontend/          Next.js frontend
backend/           FastAPI backend
ml/                датасет, конфіги, навчання LoRA-моделі
scripts/           PowerShell-скрипти запуску та зупинки
docker-compose.yml PostgreSQL для локального запуску
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

Навчальні файли:

```text
ml/data/curated/tickets_curated.jsonl
ml/configs/train_lora.yaml
ml/training/train_lora.py
```

LoRA-адаптер не варто комітити в репозиторій, якщо він великий. Для повного локального запуску класифікації модель має бути доступна за шляхом з `LORA_ADAPTER_PATH`.
