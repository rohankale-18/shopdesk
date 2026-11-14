# ShopDesk

A small but production-shaped customer-support app for an online store, built as a playground for learning AI agent development.

- **Backend:** FastAPI + SQLAlchemy 2 + SQLite, managed with `uv`
- **AI:** Groq (`openai/gpt-oss-120b` by default) via the `groq` SDK
- **Frontend:** React 19 + TypeScript + Tailwind CSS v4 + TanStack Query + React Router (Vite)
- **Data:** a deterministic generator, so the same seed always produces the same customers, orders, refunds and tickets, plus five built-in support scenarios with known correct resolutions

## Run it with Docker (one command)

```bash
docker compose up --build
```

- App: http://localhost:8080
- API docs: http://localhost:8080/docs
- API directly: http://localhost:8000 (useful for agent scripts and notebooks)

The database is seeded on first start and kept in the `shopdesk-data` volume, so your changes survive restarts and rebuilds.

```bash
docker compose up -d --build                       # run in the background
docker compose logs -f backend                     # follow API logs
docker compose exec backend shopdesk seed --seed 7 # regenerate data
docker compose down                                # stop (keeps data)
docker compose down -v                             # stop and delete the database
WEB_PORT=3000 API_PORT=9000 docker compose up      # different ports
```

How it fits together: nginx serves the built React app and forwards `/api`, `/docs` and `/openapi.json` to the FastAPI container, so the browser only talks to one origin. The frontend waits for the backend's health check before starting. Settings in `backend/.env`, if present, are picked up too.

## Run it locally for development

You need [uv](https://docs.astral.sh/uv/) and Node 20+. This gives you hot reload on both sides.

```bash
# Terminal 1: API on http://localhost:8000 (docs at /docs)
cd backend
uv sync
uv run fastapi dev app/main.py

# Terminal 2: web app on http://localhost:5173
cd frontend
npm install
npm run dev
```

The database (`backend/shopdesk.db`) is created and seeded automatically the first time the API starts. In dev, Vite proxies `/api` to the backend, so there's no CORS setup needed.

## Data generation

```bash
cd backend
uv run shopdesk seed                         # wipe + regenerate with seed 42
uv run shopdesk seed --seed 7 --orders 1000  # different data, more orders
uv run shopdesk seed --anchor-date 2026-01-01  # fully fixed timestamps
uv run shopdesk reset                        # empty database
```

Or over HTTP: `POST /api/admin/seed` with `{"seed": 42, "customers": 60, "products": 40, "orders": 250, "tickets": 60}`. There's also a **Test data** page in the app.

Dates are generated backwards from today, so the dashboard always looks current. Pass `anchor_date` to pin them for reproducible evals.

**Large datasets.** The generator always creates exactly the number of records you ask for, at any size. Product names are unique: once the catalog's word combinations run out (around 1,265 products), names get a variant suffix such as "Mini" or "XL", and then an edition number such as "(Edition 2)". The summary from `seed` (CLI and HTTP) reports the counts actually in the database, which includes the scenario records listed below, so `--products 2000` reports 2004.

Size limits on `POST /api/admin/seed`: up to 5,000 customers, 5,000 products, 20,000 orders and 5,000 tickets. The CLI has no limits:

```bash
uv run shopdesk seed --products 5000 --customers 5000 --orders 50000 --tickets 5000
```

### Built-in scenarios

Every dataset starts with these, at stable IDs. They're your first agent test cases:

| Scenario | Customer | Expected agent behavior |
|---|---|---|
| Damaged item | priya.sharma@example.com, `ORD-00000001` | Refund the headphones only ($199.99), not the serum |
| Late delivery | marcus.lee@example.com, `ORD-00000002` | Shipped 12 days ago, never delivered: investigate and escalate or refund |
| Partial refund limit | elena.garcia@example.com, `ORD-00000003` | Customer asks for $249.98, but only $199.99 is still refundable |
| Cancel request | james.okafor@example.com, `ORD-00000004` | Paid but not shipped, so cancelling is allowed |
| Out-of-stock question | james.okafor@example.com, product `SCN-0003` | Stock is 0; the agent shouldn't promise a date it doesn't know |

## API

All money is in **integer cents** (USD). Full interactive docs: http://localhost:8000/docs. The OpenAPI spec is at `/openapi.json`, and operation IDs are clean names like `list_orders` and `create_refund`.

| Method | Path | What it does |
|---|---|---|
| GET | `/api/health` | Liveness + database check |
| GET | `/api/stats/overview` | Dashboard numbers |
| GET / POST | `/api/customers` | Search (`q`, `tier`, `sort`) / create |
| GET / PATCH / DELETE | `/api/customers/{id}` | Detail with lifetime value / update / delete |
| GET | `/api/customers/{id}/orders`, `/tickets` | A customer's history |
| GET / POST | `/api/products` | Search (`q`, `category`, `in_stock`, price range) / create |
| GET / PATCH / DELETE | `/api/products/{id}` | Detail / update / archive (soft delete) |
| GET / POST | `/api/orders` | List (`q`, `status`, `customer_id`, dates) / place order |
| GET | `/api/orders/{id}`, `/api/orders/by-number/{number}` | Full order with items, refunds, refundable amount |
| POST | `/api/orders/{id}/status` | Advance: pending → paid → shipped → delivered |
| POST | `/api/orders/{id}/cancel` | Cancel a pending or paid order (restocks items) |
| GET / POST | `/api/orders/{id}/refunds` | List / issue a refund (can't exceed what's refundable) |
| GET / POST | `/api/tickets` | List (`status`, `priority`, `category`, `q`...) / open a ticket |
| GET / PATCH | `/api/tickets/{id}` | Ticket with thread / update status, priority, assignee |
| POST | `/api/tickets/{id}/messages` | Reply (a customer reply re-opens the ticket) |
| GET | `/api/ai/status` | Whether AI is configured, and which model is used (doesn't call the provider) |
| POST | `/api/ai/prompt` | Send one prompt (`prompt`, optional `system`) to the model to test the setup |
| POST | `/api/admin/seed`, `/api/admin/reset` | Regenerate data (keep these away from agents) |

List endpoints return `{items, total, page, page_size, pages}` and accept `page` and `page_size` (max 100).

Every error has the same shape, with an actionable message and machine-readable details:

```json
{
  "error": {
    "code": "business_rule_violation",
    "message": "Refund of 24998 cents exceeds what's refundable on ORD-00000003.",
    "details": { "requested_cents": 24998, "refundable_cents": 19999, "already_refunded_cents": 4999 }
  }
}
```

## Project layout

```
docker-compose.yml     runs both services with one command
backend/
  Dockerfile           uv-based image, non-root, health check
  app/
    main.py            app factory, CORS, request IDs + logging, auto-seed
    core/              settings, error handling, pagination + sorting
    models.py          SQLAlchemy models (money in cents, UTC timestamps)
    schemas.py         Pydantic request/response models (these become tool docs)
    services/orders.py order lifecycle, stock, cancel, refund rules
    services/seed.py   deterministic data generator + scenarios
    services/ai.py     Groq client wrapper: complete(messages, tools=...)
    routers/           one file per resource
    cli.py             `uv run shopdesk seed|reset`
  tests/               pytest suite (27 tests)
frontend/
  Dockerfile           Node build stage + nginx
  nginx.conf           serves the app, proxies /api and /docs to the backend
  src/
    api/               typed fetch client, types, TanStack Query hooks
    components/        UI kit, layout, order lifecycle track, order actions
    pages/             Overview, Tickets, Ticket detail, Orders, Customers, Products, Test data
```

## Checks

```bash
cd backend && uv run pytest && uv run ruff check app
cd frontend && npx tsc -b && npm run build
```

## Configuration

Copy `backend/.env.example` to `backend/.env`. Useful settings:

- `DATABASE_URL`: any SQLAlchemy URL (SQLite by default)
- `AUTO_SEED` / `DEFAULT_SEED`: seed an empty database on startup
- `ADMIN_ENABLED` / `ADMIN_TOKEN`: lock down or disable the seed and reset endpoints
- `CORS_ORIGINS`: needed only if the frontend is served from a different origin
- `GROQ_API_KEY`: turns on the AI endpoints (see below)
- `AI_MODEL`, `AI_TEMPERATURE`, `AI_MAX_TOKENS`, `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`: model settings

`.env` files are git-ignored. Only the `.env.example` files are committed.

## AI setup (Groq)

The backend uses [Groq](https://console.groq.com) through the official `groq` Python SDK.

1. Get an API key at https://console.groq.com/keys.
2. Put it in `backend/.env` as `GROQ_API_KEY=...`, then restart the API. Docker Compose reads this file too.
3. Check that it works:

```bash
curl http://localhost:8000/api/ai/status
# {"enabled": true, "provider": "groq", "model": "openai/gpt-oss-120b"}

curl -X POST http://localhost:8000/api/ai/prompt \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Say hello in five words."}'
```

Defaults: model `openai/gpt-oss-120b`, temperature 0.2, 4096 max tokens, 30 s timeout, 2 retries. gpt-oss is a reasoning model, and its hidden reasoning counts toward `AI_MAX_TOKENS`. If you lower the limit, long answers can come back empty with `finish_reason: "length"`.

Errors use the usual error shape:

- **503 `service_unavailable`:** no key is set, or Groq rejected the key.
- **502 `upstream_error`:** Groq hit a rate limit, timed out, couldn't be reached, or returned an error.

All AI calls go through `app/services/ai.py`. Its `complete(messages, tools=...)` function takes an OpenAI-style message list and optional tool definitions, and returns the reply text, any tool calls, token usage and the raw message. Build new AI features on top of it rather than calling the SDK directly.

The tests never call Groq. `tests/conftest.py` blanks the key, and `tests/test_ai.py` swaps in a fake client.

## Where to add AI

A data-aware support chatbot is next: it will answer questions by calling tools that query customers, orders, products and tickets, built on `ai.complete()`.

Some natural next steps, roughly in order of difficulty:

1. **Ticket summarizer:** read a ticket and its order, then produce a one-line summary for the queue.
2. **Reply drafter:** fill the reply box on the ticket page with a suggested answer that a human sends.
3. **Tool-using support agent:** wrap the endpoints as tools (`find_customer`, `get_order`, `create_refund`, `cancel_order`, `reply_to_ticket`) and let the model resolve a ticket end to end. Require human approval before refunds and cancellations.
4. **Evals:** reseed with a fixed `--anchor-date`, run the agent on each scenario, and assert on the resulting database state (the right refund amount, no over-refund, correct cancellation).

Not included yet, and worth adding as the project grows: Alembic migrations, authentication, and Postgres for multi-user use.
