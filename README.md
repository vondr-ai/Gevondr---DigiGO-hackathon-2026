# Gevondr

**AI indexeert ongestructureerde documenten, DSGO verbindt de keten.**

> *"Ik wil niet zoeken, ik wil vinden."*

Gevondr is een platform waar de Data Rechthebbende ongestructureerde data uploadt en de Data Service Consumer het veilig ontvangt — gebouwd op het DSGO.

---

Deze repo is de hackathon-build. Het Vondr-platform zelf is niet opgenomen — zie [Hackathon Scope](docs/reference/product/hackathon-scope.md).

---

## Wat doet het?

| Je wilt... | Gevondr doet... |
|---|---|
| Documenten doorzoekbaar maken | AI indexeert automatisch, volgens de norm die je kiest |
| Data veilig delen | Via IAA (iSHARE), rolgebaseerd conform GEBORA |
| Snel het juiste document vinden | Vraag in natuurlijke taal, antwoord in 10 seconden |

Werkt met elk DMS, elke projectmap, begroting of planning. Bring your own model — jouw data blijft bij jou.

---

## DSGO Rollen

| Rol | Wie | Wat |
|---|---|---|
| **Data Rechthebbende (DRH)** | Elk DigiGO-lid | Uploadt data, kiest normen, wijst organisaties toe |
| **Data Service Consumer (DSC)** | Aannemer / Adviseur | Ontvangt data, geeft DSU's projecttoegang |
| **Data Service Utilisator (DSU)** | Monteur / Projectleider | Zoekt via browser of app. No-code. |

Beveiligd via DSGO · IAA · iSHARE · GEBORA — van ontwikkeling tot sloop & oogst.

---

## Quick start

```bash
# Backend
cd be
uv sync
cp .env.example .env
# Vul je iSHARE certificaat en private key pad in
uv run python main.py

# Frontend (apart terminal)
cd fe
npm install
npm run dev
```

Of met Docker:

```bash
docker compose up -d
```

---

## Documentatie

| Document | Beschrijving |
|---|---|
| [Documentatie index](docs/README.md) | Hoofdindex met leesroutes per rol |
| [System Overview](docs/reference/architecture/system-overview.md) | Architectuur, componenten, deployment |
| [API Reference](docs/api-reference.md) | Volledige backend API-documentatie |
| [Database Schema](docs/reference/database/schema.md) | Kerntabellen en relaties |
| [Architecture Decisions](docs/reference/decisions/architecture-decisions.md) | 5 ADR's — fundamentele keuzes |
| [Hackathon Scope](docs/reference/product/hackathon-scope.md) | Wat is gebouwd, wat is weggelaten |

---

## Repo-structuur

```
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
├── docs/                      ← Projectdocumentatie
└── docker-compose.yml         ← Full-stack orchestratie
```

---

## Claims

| Claim | Waarde |
|---|---|
| **DSGO proof** | Gebouwd op het DSGO met IAA via iSHARE |
| **0 opschoning** | Upload zoals het is — geen conversie nodig |
| **99% vindbaarheid** | Zonder handmatige classificatie* |
| **10s vindtijd** | Was 45 minuten* |

\* Gebaseerd op vergelijkbare projecten met tunneldocumentatie en PhD-onderzoek naar documentretrieval in de gebouwde omgeving.

---

## Team Vondr

**Milan, Lennart & Dirk** — AI-platform voor de bouw- en infrasector.

Structuuragnostisch. Werkt in alle 17 GEBORA waardestromen, alle fasen van de BouwwerkLevensCyclus, conform FAIR-principes.

vondr.ai · DSGO Hackathon 2026
