# Gevondr — Documentatie

> *"Ik wil niet zoeken, ik wil vinden."*

Gevondr is een platform waar de Data Rechthebbende ongestructureerde data uploadt en de Data Service Consumer het veilig ontvangt — gebouwd op het DSGO.

---

Hackathon-build — het Vondr-platform zelf is niet opgenomen. Zie [scope](reference/product/hackathon-scope.md).

---

## Leesroutes

| Je bent... | Begin hier |
|---|---|
| Hackathon jury / beoordelaar | [Hackathon scope](reference/product/hackathon-scope.md) → [ADR's](reference/decisions/architecture-decisions.md) → [System overview](reference/architecture/system-overview.md) |
| DSGO / iSHARE specialist | [ADR's](reference/decisions/architecture-decisions.md) → [API reference](api-reference.md) → [System overview](reference/architecture/system-overview.md) |
| Developer (backend) | [System overview](reference/architecture/system-overview.md) → [Database schema](reference/database/schema.md) → [API reference](api-reference.md) |
| Developer (frontend) | [System overview](reference/architecture/system-overview.md) → [API reference](api-reference.md) |
| Nieuw teamlid / stakeholder | Deze README → [Hackathon scope](reference/product/hackathon-scope.md) → [ADR's](reference/decisions/architecture-decisions.md) |

---

## Documentatie-index

| Document | Beschrijving |
|---|---|
| [API Reference](api-reference.md) | Volledige backend API-documentatie — endpoints, auth, flows |
| **Architecture** | |
| [System Overview](reference/architecture/system-overview.md) | Componenten, data flow, deployment, tech stack |
| **Database** | |
| [Schema Quick Reference](reference/database/schema.md) | Kerntabellen, relaties, installatie |
| **Decisions** | |
| [Architecture Decisions](reference/decisions/architecture-decisions.md) | 5 ADR's — de fundamentele keuzes achter Gevondr |
| **Product** | |
| [Hackathon Scope](reference/product/hackathon-scope.md) | Wat is gebouwd, wat is weggelaten, en waarom |

---

## Quick start

Zie de [root README](../README.md) voor installatie en het starten van de applicatie.

---

## Repo-structuur

```
├── README.md                  ← Projectbeschrijving + quick start
├── docker-compose.yml         ← Full-stack orchestratie
├── be/                        ← Backend (FastAPI + Python 3.12)
│   ├── src/
│   │   ├── api/               ← REST endpoints + middleware
│   │   ├── database/          ← Postgres, Weaviate, KeyDB
│   │   ├── services/          ← Business logic + document pipeline
│   │   └── worker/            ← Async task queue (arq)
│   ├── tests/
│   └── scripts/
├── fe/                        ← Frontend (Vue 3 + TypeScript + Vite)
│   └── src/
│       ├── api/               ← Axios API client
│       ├── components/        ← Vue componenten
│       ├── stores/            ← Pinia state management
│       ├── views/             ← Pagina's (setup wizard + consumer)
│       └── router/            ← Vue Router
└── docs/                      ← Deze documentatie
```
