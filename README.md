# call-results-service

Сервис получает результаты звонков из очереди RabbitMQ, сохраняет их в MongoDB
(коллекции `campaigns` и `calls`) и отдаёт через REST API. Консьюмер работает
внутри FastAPI-приложения.

Стек: Python 3.12 (совместим с 3.10+), FastAPI, PyMongo async, aio-pika,
MongoDB 7.0, RabbitMQ 4.1, Docker Compose.

Подробности: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - компоненты, схема БД,
конечные автоматы, конкурентность; [docs/DECISIONS.md](docs/DECISIONS.md) - принятые
решения (ADR).

## Быстрый старт

Работает одинаково на Linux, macOS и Windows: сервис и базы живут в Linux-контейнерах
(на Windows/macOS - Docker Desktop), с хоста нужен только Python 3.10+ для продюсера.
Ниже команды для bash и для PowerShell.

### 1. Запустить окружение

```bash
docker compose up --build
```

Поднимаются `mongodb`, `rabbitmq` и `app`. Сервис готов, когда `docker compose ps`
показывает `app` в состоянии `healthy`. Порты на хосте: `8000` - API (Swagger:
http://localhost:8000/docs), `5672` - AMQP, `15672` - веб-интерфейс RabbitMQ
(guest/guest).

### 2. Запустить продюсер

Нужен Python 3.10+ и одна зависимость. Linux/macOS:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-producer.txt
python producer.py
```

Windows (PowerShell):

```powershell
py -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements-producer.txt
python producer.py
```

```
published call_0001 -> camp_001
published call_0002 -> camp_001
published call_0003 -> camp_002
published call_0004 -> camp_002
done: 4 messages confirmed by RabbitMQ
```

Продюсер публикует 4 сообщения - по 2 на кампании `camp_001` и `camp_002` - с
подтверждением от брокера. Адрес брокера меняется переменной `RABBITMQ_URL`
(по умолчанию `amqp://guest:guest@localhost:5672/`). Повторный запуск безопасен:
идентификаторы звонков фиксированные, дубли не создаются.

Без Python на хосте: `docker compose run --rm producer`.

### 3. Проверить результат

```bash
curl http://localhost:8000/campaigns/camp_001/calls
```

```powershell
Invoke-RestMethod http://localhost:8000/campaigns/camp_001/calls | ConvertTo-Json -Depth 5
# или curl.exe (в Windows PowerShell 5.1 `curl` - псевдоним Invoke-WebRequest)
```

```json
{
  "campaign_id": "camp_001",
  "total": 2,
  "limit": 100,
  "offset": 0,
  "calls": [
    {"call_id": "call_0001", "campaign_id": "camp_001", "phone": "79001234567", "status": "success", "created_at": "2026-10-20T10:06:00Z"},
    {"call_id": "call_0002", "campaign_id": "camp_001", "phone": "79001234568", "status": "no_answer", "created_at": "2026-10-20T10:07:30Z"}
  ]
}
```

Несуществующая кампания → `200 {"detail":"Кампания не найдена"}`.

### Всё одной командой

Сценарий проверяющего целиком - поднять стек, дождаться готовности, запустить
`producer.py` (дважды), проверить ответы API:

```bash
make smoke            # Linux/macOS
```

```powershell
.\tasks.ps1 smoke     # Windows
```

Проверка написана один раз на Python (`scripts/smoke_check.py`, только стандартная
библиотека + `producer.py`), Makefile и `tasks.ps1` лишь вызывают её. Код выхода
`0` - сценарий прошёл.

## API

| метод и путь | ответ |
|---|---|
| `GET /campaigns/{campaign_id}/calls?limit=100&offset=0` | `200` `CampaignCallsResponse` или `200` `CampaignNotFoundResponse` (для любого неизвестного `campaign_id`); `422` при некорректных параметрах; `503`, если MongoDB недоступна |
| `GET /health` | `200`/`503` `HealthResponse` - MongoDB и консьюмер |
| `GET /docs`, `GET /openapi.json` | Swagger UI и схема |

Звонки отсортированы по `created_at`, затем `call_id`. `limit` - 1…1000,
`offset` - 0…1 000 000, `campaign_id` - до 256 символов.

## Формат сообщения

Exchange `calls` (direct), routing key `call.result`, очередь `calls.results`
(quorum). JSON в UTF-8:

```json
{
  "call_id": "call_0001",
  "campaign_id": "camp_001",
  "campaign_name": "Напоминание о платеже",
  "campaign_created_at": "2026-10-20T10:00:00Z",
  "phone": "79001234567",
  "status": "success",
  "created_at": "2026-10-20T10:06:00Z"
}
```

Обязательны только пять полей звонка из задания; сообщение ровно в таком формате
тоже принимается:

```json
{"call_id": "call_0101", "campaign_id": "camp_003", "phone": "79001234567",
 "status": "success", "created_at": "2026-10-20T10:06:00Z"}
```

| поле | правило |
|---|---|
| `call_id`, `campaign_id` | латиница, цифры, `_ . : -`, до 64 символов |
| `phone` | только цифры, 10-15 знаков, без `+`, пробелов и дефисов: `79001234567`. `+7 900 123-45-67` уходит в `calls.results.dead` |
| `status` | `[a-z][a-z0-9_]*`, до 32 символов: `success`, `no_answer`, `busy` |
| `created_at`, `campaign_created_at` | ISO 8601 с часовым поясом: `2026-10-20T10:06:00Z` |
| `campaign_name` | необязательно; по умолчанию название кампании равно `campaign_id` |
| `campaign_created_at` | необязательно; по умолчанию время первого звонка кампании |

Название и дата создания кампании берутся из первого сообщения по ней. Неизвестные
поля игнорируются. Подробнее: ADR-008 и ADR-009 в `docs/DECISIONS.md`.

Что происходит с сообщением:

| ситуация | действие |
|---|---|
| записано в MongoDB / точный дубликат | `ack` |
| не JSON, не прошло валидацию, конфликт по `call_id` | лог `WARNING`/`ERROR`, `reject` → очередь `calls.results.dead` |
| MongoDB временно недоступна | повтор на месте с паузой до 30 с, без `ack` |
| непредвиденная ошибка | лог с трассировкой, `nack` с возвратом; после 5 повторных доставок → `calls.results.dead` |

## Конфигурация

Все настройки с описанием и значениями по умолчанию: [`.env.example`](.env.example).
Чтобы поменять их, скопируйте файл в `.env` (`cp .env.example .env`, в PowerShell
`Copy-Item .env.example .env`). Приложение читает `.env` при запуске на хосте, docker
compose подхватывает его для контейнера `app`; адреса MongoDB и RabbitMQ в compose
всегда указывают на контейнеры. Переменные окружения (см. `app/config.py`):

| переменная | по умолчанию |
|---|---|
| `MONGODB_URL` | `mongodb://localhost:27017` |
| `MONGODB_DB` | `call_results` |
| `MONGODB_TIMEOUT_MS` | `5000` |
| `RABBITMQ_URL` | `amqp://guest:guest@localhost:5672/` |
| `PREFETCH_COUNT` | `10` |
| `RETRY_DELAY_SECONDS` | `1.0` |
| `STORAGE_RETRY_MAX_DELAY_SECONDS` | `30.0` |
| `RECONNECT_INITIAL_DELAY_SECONDS` / `RECONNECT_MAX_DELAY_SECONDS` | `1.0` / `30.0` |
| `LOG_LEVEL` | `INFO` |

Логи - JSON, по объекту на строку, в stdout.

## Разработка

Одни и те же задачи на обеих платформах:

| задача | Linux/macOS | Windows (PowerShell) |
|---|---|---|
| создать окружение | `make venv` → `source .venv/bin/activate` | `.\tasks.ps1 venv` → `.\.venv\Scripts\Activate.ps1` |
| зависимости | `make install` | `.\tasks.ps1 install` |
| линтер, формат | `make lint` / `make fmt` | `.\tasks.ps1 lint` / `fmt` |
| типы (`mypy --strict`) | `make typecheck` | `.\tasks.ps1 typecheck` |
| тесты | `make test` | `.\tasks.ps1 test` |
| всё, что гоняет CI | `make check` | `.\tasks.ps1 check` |
| стек / логи / стоп | `make up` / `logs` / `down` | `.\tasks.ps1 up` / `logs` / `down` |
| сценарий проверки | `make smoke` | `.\tasks.ps1 smoke` |

`make help` / `.\tasks.ps1 help` - список задач. Если PowerShell блокирует скрипты:
`Set-ExecutionPolicy -Scope Process Bypass`. Зависимости разработки -
`requirements-dev.txt` (lock `requirements.txt` + инструменты); lock кроссплатформенный
(`uv pip compile --universal`), платформенные пакеты (`uvloop`) помечены маркерами.

Интеграционные и e2e-тесты используют настоящие MongoDB и RabbitMQ по адресам
`MONGODB_URL` / `RABBITMQ_URL` (по умолчанию localhost). Поднять их из compose
(оверлей `docker-compose.dev.yml` публикует порт MongoDB на хост):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --wait mongodb rabbitmq
```

Если сервис недоступен, зависящие от него тесты пропускаются с указанием причины.
Тесты используют отдельные базы `test_calls_*` и удаляют их, но очищают очереди
`calls.results*` - не запускайте их против брокера с нужными данными.

Покрыто тестами: валидация сообщений, решения ack/reject/nack, идемпотентность и
гонки upsert'ов на реальной MongoDB, перенос невалидных сообщений в DLQ,
удержание сообщения при недоступной БД, DLQ после лимита доставок, переподключение
к RabbitMQ, корректная остановка, вывод в консоль с устаревшей кодировкой
(cp1251), API и сценарий проверяющего целиком.

### CI

`.github/workflows/ci.yml` на каждый push и pull request:

| job | что делает |
|---|---|
| Lint & types | `ruff`, `mypy --strict` |
| Tests · Linux · 3.10 / 3.12 | все тесты против MongoDB и RabbitMQ в service-контейнерах; пропуск хотя бы одного теста - ошибка |
| Tests · Windows · 3.10 / 3.12 | `tasks.ps1` в Windows PowerShell 5.1 и PowerShell 7, `.\tasks.ps1 check`, поведение `producer.py` без брокера. Интеграционные тесты здесь пропускаются: Windows-раннеры GitHub не запускают Linux-контейнеры |
| docker compose up + reviewer scenario | `docker compose up --build --wait`, затем `scripts/smoke_check.py` |

## Как проверялось

- `ruff`, `mypy --strict` (включая тесты) и 104 теста - зелёные на Python 3.10, 3.12 и 3.13,
  против настоящих MongoDB (7.0 в CI, 8.3 локально) и RabbitMQ (4.1 в CI, 3.12
  локально);
- сценарий проверяющего: приложение запущено командой из `Dockerfile`
  (`uvicorn app.main:build_default_app --factory`) на Python 3.12 из чистого
  окружения с `requirements.txt`; `scripts/smoke_check.py` из отдельного окружения
  с одним `requirements-producer.txt` - все шаги `ok`; при остановленном сервисе -
  `FAIL` и код выхода 1;
- `requirements.txt` ставится на Python 3.10 и 3.12 и разрешается для Windows;
  в PyCharm на Windows ошибка установки `uvloop` воспроизведена и исправлена;
- отказы: остановка MongoDB на 12 с во время обработки (сообщение дождалось БД и
  записалось, в DLQ не попало), перезапуск RabbitMQ (консьюмер переподключился),
  `SIGTERM` (корректная остановка);
- `ci.yml` проверен `actionlint`;
- GitHub Actions: все 6 джоб зелёные, в том числе `docker compose up --build --wait`
  со сценарием проверяющего и тесты на Windows через `tasks.ps1` (PowerShell 5.1 и 7).

## Ограничения

- Точное число попыток до DLQ отличается на 1 между RabbitMQ 3.x и 4.x
  (семантика `x-delivery-limit`); тест принимает оба варианта.
- Интеграционные тесты на Windows не запускаются в CI: Windows-раннеры GitHub не
  поддерживают Linux-контейнеры. Код под Windows проверяют юнит-тесты, линтер и
  типы; сервис в любом случае работает в Linux-контейнере.
- Учётные данные `guest/guest` и MongoDB без аутентификации - только для
  локального запуска. Для продакшена - секреты через окружение и TLS.
- Внутри одной реплики сообщения обрабатываются последовательно; масштабирование -
  репликами `app`.
- Нет метрик (Prometheus) и трассировки.
- Сообщения из `calls.results.dead` автоматически не переобрабатываются - их
  разбирают вручную (веб-интерфейс RabbitMQ, shovel).
