# call-results-service

Сервис получает результаты звонков из очереди RabbitMQ, сохраняет их в MongoDB
(коллекции `campaigns` и `calls`) и отдаёт через REST API. Консьюмер работает
внутри FastAPI-приложения.

Стек: Python 3.12 (совместим с 3.10+), FastAPI, PyMongo async, aio-pika,
MongoDB 8.0, RabbitMQ 4.1, Docker Compose.

Подробности: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - компоненты, схема БД,
конечные автоматы, конкурентность; [docs/DECISIONS.md](docs/DECISIONS.md) - принятые
решения (ADR).

## Быстрый старт

### 1. Запустить окружение

```bash
docker compose up --build
```

Поднимаются `mongodb`, `rabbitmq` и `app`. Сервис готов, когда
`docker compose ps` показывает `app` в состоянии `healthy`, или:

```bash
curl http://localhost:8000/health
# {"status":"ok","mongodb":{"ok":true,"state":"up"},"consumer":{"ok":true,"state":"consuming"}}
```

Порты на хосте: `8000` - API (Swagger: http://localhost:8000/docs),
`5672` - AMQP, `15672` - веб-интерфейс RabbitMQ (guest/guest).

### 2. Запустить продюсер

С хоста (нужен Python 3.10+ и одна зависимость):

```bash
pip install -r requirements-producer.txt
python producer.py
```

```
published call_0001 → camp_001
published call_0002 → camp_001
published call_0003 → camp_002
published call_0004 → camp_002
done: 4 messages confirmed by RabbitMQ
```

Продюсер публикует 4 сообщения - по 2 на кампании `camp_001` и `camp_002` - с
подтверждением от брокера. Адрес брокера меняется переменной `RABBITMQ_URL`
(по умолчанию `amqp://guest:guest@localhost:5672/`). Повторный запуск безопасен:
идентификаторы звонков фиксированные, дубли не создаются.

Без установки пакетов на хост:

```bash
docker compose run --rm producer
```

### 3. Проверить результат

```bash
curl http://localhost:8000/campaigns/camp_001/calls
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

Несуществующая кампания:

```bash
curl http://localhost:8000/campaigns/camp_999/calls
# 200 {"detail":"Кампания не найдена"}
```

## API

| метод и путь | ответ |
|---|---|
| `GET /campaigns/{campaign_id}/calls?limit=100&offset=0` | `200` `CampaignCallsResponse` или `200` `CampaignNotFoundResponse`; `422` при некорректных параметрах |
| `GET /health` | `200`/`503` `HealthResponse` - MongoDB и консьюмер |
| `GET /docs`, `GET /openapi.json` | Swagger UI и схема |

Звонки отсортированы по `created_at`, затем `call_id`. `limit` - 1…1000.

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

`campaign_created_at` необязательно (по умолчанию - время первого звонка кампании).
Даты обязаны содержать часовой пояс. Правила валидации - ADR-009.

Что происходит с сообщением:

| ситуация | действие |
|---|---|
| записано в MongoDB / точный дубликат | `ack` |
| не JSON, не прошло валидацию, конфликт по `call_id` | лог `WARNING`/`ERROR`, `reject` → очередь `calls.results.dead` |
| MongoDB временно недоступна | повтор на месте с паузой до 30 с, без `ack` |
| непредвиденная ошибка | лог с трассировкой, `nack` с возвратом; после 5 повторных доставок → `calls.results.dead` |

## Конфигурация

Переменные окружения (см. `app/config.py`):

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

```bash
uv venv && uv pip install -e . ruff mypy pytest pytest-asyncio httpx
# или: python -m venv .venv && .venv/bin/pip install -e . ruff mypy pytest pytest-asyncio httpx

ruff format --check . && ruff check .
mypy                     # strict
pytest                   # unit + integration + e2e
```

Интеграционные и e2e-тесты используют настоящие MongoDB и RabbitMQ по адресам
`MONGODB_URL` / `RABBITMQ_URL` (по умолчанию localhost). Поднять их из compose
(оверлей `docker-compose.dev.yml` публикует порт MongoDB на хост):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --wait mongodb rabbitmq
pytest -rs
```

Если сервис недоступен, зависящие от него тесты пропускаются с указанием причины. Тесты используют отдельные
базы `test_calls_*` и удаляют их, но очищают очереди `calls.results*` - не
запускайте их против брокера с нужными данными.

Покрыто тестами: валидация сообщений, решения ack/reject/nack, идемпотентность и
гонки upsert'ов на реальной MongoDB, перенос невалидных сообщений в DLQ,
удержание сообщения при недоступной БД, DLQ после лимита доставок, переподключение
к RabbitMQ, корректная остановка, API и сценарий проверяющего целиком.

## Как проверялось

- `ruff`, `mypy --strict` и 77 тестов - зелёные на Python 3.13 и на Python 3.10
  (с aio-pika 9.x, которую pip выбирает для 3.10);
- против настоящих MongoDB 8.3 и RabbitMQ 3.12;
- сценарий проверяющего вручную: приложение запущено командой из `Dockerfile`
  (`uvicorn app.main:build_default_app --factory`) на Python 3.12 из чистого
  окружения с закреплёнными `requirements.txt`, затем `python producer.py` из отдельного окружения с
  `requirements-producer.txt`, затем `GET /campaigns/camp_001/calls` → ровно 2
  звонка; повторный запуск продюсера - по-прежнему 2;
- отказы: остановка MongoDB на 12 с во время обработки (сообщение дождалось БД и
  записалось, в DLQ не попало), перезапуск RabbitMQ (консьюмер переподключился),
  `SIGTERM` (корректная остановка).

## Ограничения

- **`docker compose up --build` в среде разработки не запускался**: Docker Hub
  был недоступен по сетевой политике, базовые образы скачать не удалось.
  `docker-compose.yml` проверен `docker compose config`, всё остальное - как
  описано в разделе выше, но без контейнеров. Сборку образа и healthcheck'и
  контейнеров стоит прогнать при первом запуске.
- Локальные версии отличаются от образов: MongoDB 8.3 вместо 8.0 и RabbitMQ 3.12
  вместо 4.1. Используемые возможности (quorum queues, `x-delivery-limit`, DLX,
  `$facet`) есть в обеих; точное число попыток до DLQ может отличаться на 1 -
  тест это учитывает.
- Учётные данные `guest/guest` и MongoDB без аутентификации - только для
  локального запуска. Для продакшена - секреты через окружение и TLS.
- Внутри одной реплики сообщения обрабатываются последовательно; масштабирование -
  репликами `app`.
- Нет CI-конфигурации, метрик (Prometheus) и трассировки.
- Сообщения из `calls.results.dead` автоматически не переобрабатываются - их
  разбирают вручную (веб-интерфейс RabbitMQ, shovel).
