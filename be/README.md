# Gevondr — Backend

FastAPI backend voor het Gevondr platform. Beheert projecten, documenten, indexering, zoeken, chat en DSGO/iSHARE authenticatie.

## Tech stack

| Tool | Versie | Doel |
|---|---|---|
| Python | 3.12 | Runtime |
| FastAPI | 0.116+ | Web framework |
| SQLAlchemy | 2.0 | ORM (PostgreSQL) |
| Weaviate | 4.20+ client | Vector search |
| KeyDB/Redis | 5.x client | Sessie-cache + job queue |
| arq | 0.26 | Async task queue |
| PydanticAI | 1.73+ | AI agent framework |
| google-genai | 1.39+ | Gemini LLM |
| PyJWT | 2.12 | JWT authenticatie |
| uv | - | Package manager |

## Starten

```bash
uv sync
cp .env.example .env
# Vul in: iSHARE certificaat, private key, API keys
uv run python main.py
```

Draait op **http://localhost:8000**. API docs beschikbaar op `/docs` (Swagger) en `/redoc`.

### Vereisten

- PostgreSQL 16, Weaviate 1.31, KeyDB — of start alles via `docker compose up -d` vanuit de root.

## Structuur

```
be/
├── main.py                    ← Entry point (uvicorn)
├── src/
│   ├── app.py                 ← FastAPI app factory + lifespan
│   ├── settings.py            ← Pydantic configuratie
│   ├── monitoring.py          ← Logging
│   ├── api/
│   │   ├── routers/
│   │   │   ├── auth.py        ← Login, sessie, consumer simulatie
│   │   │   ├── projects.py    ← Project CRUD, datasources, uploads, indexing
│   │   │   ├── consumer.py    ← Consumer search, document access
│   │   │   ├── project_chat.py← Chat streaming (SSE)
│   │   │   ├── audit.py       ← Audit log queries
│   │   │   └── catalogs.py    ← Normen, rollen, documenttypen
│   │   ├── middleware/
│   │   │   └── identity.py    ← JWT identity extraction
│   │   ├── deps.py            ← Dependency injection (auth, permissions)
│   │   └── schemas/           ← Pydantic request/response models
│   ├── database/
│   │   ├── models.py          ← SQLAlchemy ORM modellen (12 tabellen)
│   │   ├── postgres/          ← Connectie, repos, migrations
│   │   ├── weaviate/          ← Vector store connectie + repos
│   │   └── keydb/             ← Cache + arq configuratie
│   ├── services/
│   │   ├── dsgo/              ← iSHARE auth (JWT + OAuth2) + registry
│   │   ├── document_database/ ← Document processing pipeline
│   │   │   ├── ocr/           ← OCR + tekst extractie per formaat
│   │   │   ├── pipeline/      ← Index + search pipelines
│   │   │   └── prompts/       ← LLM prompts voor indexering
│   │   ├── llm_services/      ← LLM providers (Gemini, Jina)
│   │   ├── project_chat/      ← RAG agent + SSE streaming
│   │   ├── key_vault/         ← Infisical secret management
│   │   ├── indexing_service.py
│   │   ├── search_service.py
│   │   ├── staging_service.py
│   │   ├── audit_service.py
│   │   └── storage.py
│   └── worker/
│       └── tasks.py           ← Async taken: indexing, discover, sync, cleanup
├── tests/                     ← Pytest test suite
├── scripts/
│   └── seed_local_demo.py     ← Demo data seeder
├── credentials/               ← iSHARE certificaten (gitignored)
├── demo-projecten/            ← Sample projectdata
├── Dockerfile
├── pyproject.toml
└── .env.example
```

## Environment variabelen

Zie `.env.example` voor alle vereiste variabelen. De belangrijkste:

| Variabele | Doel |
|---|---|
| `DSGO_CLIENT_ID` | iSHARE party identifier |
| `DSGO_PRIVATE_KEY_PATH` | Pad naar private key |
| `DSGO_CERTIFICATE_PATH` | Pad naar iSHARE certificaat |
| `GEMINI_API_KEY` | Google Gemini API key |
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET` | Secret voor sessie-tokens |

## API documentatie

Volledige API reference: [docs/api-reference.md](../docs/api-reference.md)

## Tests

```bash
uv run pytest
```
