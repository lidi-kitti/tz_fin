# Payment Service

Асинхронный микросервис процессинга платежей по тестовому заданию.

Сервис принимает платёж по HTTP, сразу отвечает `202 Accepted` и обрабатывает его в фоне: запись в PostgreSQL, гарантированная публикация события в RabbitMQ через **Transactional Outbox**, эмуляция платёжного шлюза, webhook клиенту, повторные попытки и **Dead Letter Queue**.

## Архитектура

```
Клиент
  │  POST /api/v1/payments + X-API-Key + Idempotency-Key
  ▼
FastAPI
  │  одна транзакция PostgreSQL
  ├─ payments (status=pending)
  └─ outbox   (payment.created)
        │
        ▼
Outbox worker (в процессе API)
  │  FOR UPDATE SKIP LOCKED → publish + publisher confirm
  ▼
Exchange `payments`  ──► очередь `payments.new`
        │
        ▼
FastStream consumer (один обработчик)
  │  эмуляция шлюза 2–5 с, 90% success / 10% fail
  │  обновление статуса в БД
  │  POST webhook (до 3 попыток, backoff 1s / 2s / 4s)
  │
  ├─ ошибка обработки, попытка 1–3 ──► TTL-очереди `payments.retry.*` ──► снова `payments.new`
  └─ после 3 попыток / неизвестный платёж ──► `payments.dlq`
```

Гарантии:

- Платёж и outbox-событие пишутся атомарно. Если RabbitMQ недоступен, API всё равно принимает платёж, worker догонит позже.
- Повтор `POST` с тем же `Idempotency-Key` возвращает тот же платёж (уникальный индекс + обработка гонки).
- Consumer идемпотентен: повторная доставка после `succeeded`/`failed` не вызывает шлюз повторно, только webhook.
- Сообщения, не обработанные после трёх попыток, попадают в DLQ `payments.dlq`.

## Стек

- Python 3.12+, FastAPI, Pydantic v2
- SQLAlchemy 2.0 (async) + PostgreSQL + Alembic
- RabbitMQ + FastStream
- Docker Compose

## Запуск через Docker

```bash
cp .env.example .env
docker compose up --build
```

После старта:

| Сервис | URL |
|--------|-----|
| API | http://localhost:8000 |
| Swagger | http://localhost:8000/docs |
| RabbitMQ UI | http://localhost:15672 (guest / guest) |

В Compose поднимаются `postgres`, `rabbitmq`, `api` и `consumer`. Миграции Alembic выполняются при старте `api`.

## Примеры запросов

Создать платёж:

```bash
curl -i http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key-change-me" \
  -H "Idempotency-Key: order-42" \
  -d '{
    "amount": "100.50",
    "currency": "RUB",
    "description": "Заказ #42",
    "metadata": {"order_id": "42"},
    "webhook_url": "https://webhook.site/your-uuid"
  }'
```

Ответ `202 Accepted`:

```json
{
  "payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "pending",
  "created_at": "2026-10-09T07:00:00+00:00"
}
```

Повтор с тем же `Idempotency-Key` вернёт тот же `payment_id` и `created_at`.

Статус платежа (через 2–5 секунд будет `succeeded` или `failed`):

```bash
curl http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: dev-api-key-change-me"
```

Тело webhook:

```json
{
  "payment_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "succeeded",
  "processed_at": "2026-10-09T07:00:04+00:00"
}
```

## Локальный запуск без Docker-приложения

Нужны PostgreSQL и RabbitMQ (можно только их: `docker compose up -d postgres rabbitmq`).

```bash
uv sync --group dev
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

Consumer в отдельном терминале:

```bash
python -m app.worker
```

## Переменные окружения

| Переменная | Назначение |
|------------|------------|
| `DATABASE_URL` | Async SQLAlchemy URL |
| `RABBITMQ_URL` | AMQP URL |
| `API_KEY` | Значение заголовка `X-API-Key` |
| `PAYMENT_SUCCESS_RATE` | Вероятность успеха эмуляции шлюза (по умолчанию `0.9`) |
| `GATEWAY_DELAY_MIN` / `GATEWAY_DELAY_MAX` | Задержка эмуляции, сек |
| `MAX_ATTEMPTS` | Попытки обработки / webhook до DLQ (по умолчанию `3`) |
| `ENABLE_OUTBOX_WORKER` | Фоновая публикация outbox в процессе API |

## Тесты

```bash
uv sync --group dev
uv run pytest -v
```

Тесты ходят в SQLite in-memory, RabbitMQ и PostgreSQL не нужны.

## Структура

```
app/
  main.py            FastAPI + outbox worker
  worker.py          FastStream consumer
  broker.py          Exchange, payments.new, retry TTL-очереди, DLQ
  consumer.py        Один обработчик платежа
  api/               HTTP API и проверка X-API-Key
  models/            Payment, Outbox
  services/          Создание платежа, шлюз, webhook, outbox
  schemas/           Pydantic v2
alembic/             Миграции payments и outbox
docker-compose.yml   postgres, rabbitmq, api, consumer
```
