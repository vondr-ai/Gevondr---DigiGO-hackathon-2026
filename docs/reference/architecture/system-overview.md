# System Overview — Gevondr

## Architectuur

```
┌─────────────────────────────────────────────────────────┐
│                        Browser                          │
│              Vue 3 + TypeScript + Vite                   │
│         Tailwind CSS · Pinia · Vue Router               │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP (Axios)
                         │ /api/v1 proxy
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Backend                        │
│              Python 3.12 · uvicorn                       │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │  Auth    │  │ Projects │  │ Consumer │  │ Audit  │ │
│  │  Router  │  │  Router  │  │  Router  │  │ Router │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘ │
│       │              │              │             │      │
│  ┌────▼──────────────▼──────────────▼─────────────▼───┐ │
│  │                  Services                          │ │
│  │  Indexing · Search · Chat · Staging · DSGO Auth    │ │
│  └───────┬────────────┬──────────────┬────────────────┘ │
└──────────┼────────────┼──────────────┼──────────────────┘
           │            │              │
     ┌─────▼─────┐ ┌───▼────┐  ┌──────▼──────┐
     │ PostgreSQL │ │Weaviate│  │   KeyDB     │
     │    16      │ │ 1.31   │  │  (Redis)    │
     │            │ │        │  │             │
     │ Projecten  │ │ Vector │  │ Sessie-     │
     │ Documents  │ │ Search │  │ cache       │
     │ Access     │ │ Chunks │  │ Job queue   │
     │ Audit logs │ │        │  │ (arq)       │
     └────────────┘ └────────┘  └─────────────┘
```

## Componenten

### Frontend (Vue 3)

| Component | Doel |
|---|---|
| Setup Wizard (6 stappen) | Provider configureert project: datasource → documenten → AI → normen → delegaties → overzicht |
| Consumer Chat | DSU zoekt in projecten via natuurlijke taal (RAG met SSE streaming) |
| Consumer Search | Zoeken met rolgebaseerde filtering — geblokkeerde docs tonen alleen metadata |
| Auth flow | Provider login + consumer simulatie |

**Tech stack:** Vue 3.5, TypeScript 5.9, Vite 8, Tailwind CSS 4, Pinia 3, Vue Router 4, Axios, Markdown-it

### Backend (FastAPI)

| Service | Doel |
|---|---|
| `api/routers/` | REST endpoints (auth, projects, consumer, chat, audit, catalogs) |
| `services/indexing_service.py` | Orchestreert document indexering |
| `services/search_service.py` | Zoeken met access control |
| `services/project_chat/` | RAG-agent met PydanticAI + SSE streaming |
| `services/staging_service.py` | Document upload en staging |
| `services/dsgo/` | iSHARE authenticatie (JWT + OAuth2) |
| `services/document_database/` | Document processing pipeline (OCR, chunking, embedding) |
| `services/llm_services/` | LLM providers (Gemini, Jina embeddings) |
| `worker/tasks.py` | Async taken: indexing, discover, sync, audit cleanup |

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy 2, PydanticAI, arq, PyJWT, google-genai

### Databases

| Database | Rol | Poort |
|---|---|---|
| **PostgreSQL 16** | Primaire opslag: projecten, documenten, access matrix, delegaties, audit logs | 5432 |
| **Weaviate 1.31** | Vector store: semantic search over document chunks met embeddings | 8080 / 50051 |
| **KeyDB** | Sessie-cache, job queue (arq), general caching | 6379 |

## DSGO / iSHARE integratie

```
┌──────────┐    JWT + OAuth2    ┌──────────────────┐
│  Gevondr │ ◄───────────────► │ iSHARE Satellite │
│  Backend │    Certificaat     │  (acceptance)     │
└────┬─────┘                    └──────────────────┘
     │
     │  Participant lookup
     ▼
┌────────────────────────┐
│ DSGO Registry          │
│ api.acceptance.digigo.nu│
└────────────────────────┘
```

- **Client ID:** `did:ishare:EU.NL.NTRNL-98499327`
- **Registry Party ID:** `did:ishare:EU.NL.NTRNL-63202158`
- Authenticatie via iSHARE-certificaat + private key (zie `be/credentials/`)
- Provider-login is in de hackathon gemockt (`certificateStatus: "mocked-valid"`)

## Document processing pipeline

```
Upload → Staging → OCR/Text extractie → Chunking → Embedding → Weaviate
                                            │
                                    AI Indexering (Gemini)
                                            │
                                    Norm-classificatie
                                    Documenttype detectie
                                    Value stream toewijzing
                                    Samenvatting generatie
                                            │
                                    PostgreSQL (indexed_documents)
```

**Ondersteunde formaten:** PDF, DOCX, XLSX, PPTX, HTML, EML, TXT, afbeeldingen (via OCR)

## Deployment

### Docker Compose

```bash
docker compose up -d
```

Start 5 services: `api`, `worker`, `postgres`, `keydb`, `weaviate`

### Environment variabelen

| Variabele | Doel |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `KEYDB_HOST` / `KEYDB_PORT` | KeyDB/Redis verbinding |
| `WEAVIATE_HOSTNAME` / `WEAVIATE_HTTP_PORT` | Weaviate verbinding |
| `GEMINI_API_KEY` | Google Gemini API key |
| `GEMINI_MODEL` | Model (default: `gemini-2.5-flash`) |
| `DSGO_CLIENT_ID` | iSHARE client identifier |
| `DSGO_PRIVATE_KEY_PATH` | Pad naar private key |
| `DSGO_CERTIFICATE_PATH` | Pad naar iSHARE certificaat |
| `DSGO_REGISTRY_URL` | DSGO registry endpoint |
| `JWT_SECRET` | Secret voor sessie-JWT's |
| `STORAGE_ROOT` | Opslagpad voor bestanden |

### Lokaal ontwikkelen

```bash
# Backend
cd be
uv sync
cp .env.example .env  # Vul certificaat-paden en API keys in
uv run python main.py

# Frontend
cd fe
npm install
npm run dev           # → http://localhost:5173
```

De Vite dev server proxied `/api/v1` naar `http://localhost:8000`.
