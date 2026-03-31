# DigiGO Backend API

> Auteur: Lennart — Team Vondr

Deze handleiding beschrijft de werkelijk geimplementeerde backend-API van de DigiGO-app voor externe integrators. De code in `be/src/` is de bron van waarheid; deze documentatie legt het huidige gedrag vast zonder roadmap of speculatie.

Zie ook: [System Overview](reference/architecture/system-overview.md) voor de architectuur, [Database Schema](reference/database/schema.md) voor het datamodel, en de [Architecture Decisions](reference/decisions/architecture-decisions.md) voor de fundamentele keuzes.

## Overzicht

- Base path voor de applicatie-API: `/api/v1`
- Health endpoint buiten versioning: `/health`
- Primaire rollen:
  - `provider`: beheerder van eigen projecten
  - `consumer`: gedelegeerde afnemer met rolgebaseerde toegang
- Auth-model: app-issued sessie-JWT via `Authorization: Bearer <token>`
- Content types:
  - `application/json` voor vrijwel alle routes
  - `multipart/form-data` voor uploads
  - `text/event-stream` voor chat-streaming
  - binaire bestandsresponse voor `download` en `open`
- Timestamps worden in de implementatie als ISO-8601 strings zonder timezone-suffix teruggegeven. Deze waardes worden in de code als UTC-naive datetimes opgebouwd en moeten praktisch als UTC worden behandeld.

## Algemene conventies

### Authenticatie

De frontend stuurt een Bearer-token in de `Authorization` header:

```http
Authorization: Bearer <session-jwt>
```

Belangrijke nuance uit de huidige implementatie:

- Een ontbrekende of foutief gevormde `Authorization` header geeft alleen een `401` op routes die een optionele identity lezen en daarna zelf valideren, zoals `GET /api/v1/auth/session`.
- Routes met `require_provider` of `require_consumer` geven bij ontbrekende of verkeerde sessietype meestal `403`.
- `POST /auth/logout` valideert de sessie op dit moment niet en geeft altijd `204`.

### Foutresponses

De API gebruikt vaak deze foutenvelop:

```json
{
  "error": {
    "code": "forbidden",
    "message": "Provider session required."
  }
}
```

De implementatie is niet volledig uniform. Sommige routes geven `detail` als platte string terug, bijvoorbeeld:

```json
{
  "detail": "Project not found"
}
```

Integrators moeten daarom rekening houden met beide patronen:

- `detail.error.code` en `detail.error.message`
- of alleen `detail` als string

### Paginering

- Consumer search gebruikt `page` en `pageSize` in de request body.
- Audit logs gebruiken `page` en `pageSize` als queryparameters.
- Andere lijstendpoints retourneren volledige lijsten zonder expliciete paginering.

### Bestanden en streaming

- Uploads gebruiken `multipart/form-data`.
- `GET /api/v1/consumer/projects/{project_id}/documents/{document_id}/download` retourneert een downloadbare file response.
- `GET /api/v1/projects/{project_id}/documents/{document_id}/open` retourneert een inline file response.
- `POST /api/v1/projects/{project_id}/chat/stream` gebruikt Server-Sent Events met eventtypen `status`, `retrieval`, `tool`, `token`, `done` en `error`.

## Rollen en toegangsmodel

Zie [ADR-001](reference/decisions/architecture-decisions.md#adr-001--één-platform-twee-rollen) en [ADR-002](reference/decisions/architecture-decisions.md#adr-002--dsgo-als-fundament-iaa-met-least-privilege) voor de achtergrond bij dit model.

### Provider

Een provider-sessie mag alleen projecten beheren waarvan `ownerPartyId` gelijk is aan `session.partyId`. Deze ownership-check wordt op projectroutes afgedwongen.

### Consumer

Een consumer-sessie ontstaat in deze v1-implementatie alleen via `POST /auth/consumer/simulate`. Toegang tot consumer-routes hangt af van een projectdelegatie:

- zonder delegatie is projecttoegang in de regel verboden
- documenttoegang vereist daarnaast dat de gedelegeerde rol voorkomt in `allowed_role_codes`

### Audit-admin

Audit-leesrechten vereisen altijd een provider-sessie. Een provider kan extra audit-admin-rechten krijgen via `AUDIT_ADMIN_PARTY_IDS`. Niet-admin providers zien alleen audit-events met hun eigen `owner_party_id`.

## Authenticatie en sessies

### `POST /api/v1/auth/provider/login`

Start een provider-sessie.

- Actor: geen bestaande sessie vereist
- Request body: leeg JSON-object
- Response `200`:

```json
{
  "token": "<jwt>",
  "user": {
    "actorType": "provider",
    "partyId": "did:ishare:EU.NL.NTRNL-98499327",
    "partyName": "...",
    "simulation": false,
    "dsgoRoles": ["..."],
    "certificateStatus": "mocked-valid"
  }
}
```

Praktische bijzonderheden:

- De provider-login is momenteel gemockt.
- De backend zoekt een vaste provider-participant op en geeft `certificateStatus: "mocked-valid"` terug.
- Bij misconfiguratie van de mock provider kan de route `500` geven.

### `GET /api/v1/auth/session`

Geeft de huidige sessie terug.

- Actor: provider of consumer
- Request body: geen
- Response `200`:

```json
{
  "user": {
    "actorType": "consumer",
    "partyId": "did:ishare:EU.NL.NTRNL-09036504",
    "partyName": "...",
    "simulation": true,
    "dsgoRoles": ["ServiceConsumer"],
    "certificateStatus": "mocked-valid"
  }
}
```

Statuscodes:

- `200` bij geldige sessie
- `401` bij geen actieve sessie
- `401` bij ongeldige Bearer-header of ongeldige token

### `POST /api/v1/auth/consumer/simulate`

Start een consumer-sessie vanuit een provider-sessie.

- Actor: `provider`
- Request body:

```json
{
  "consumerPartyId": "did:ishare:EU.NL.NTRNL-09036504"
}
```

- Response `200`:

```json
{
  "token": "<jwt>",
  "user": {
    "actorType": "consumer",
    "partyId": "did:ishare:EU.NL.NTRNL-09036504",
    "partyName": "...",
    "simulation": true,
    "dsgoRoles": ["ServiceConsumer"],
    "certificateStatus": "mocked-valid"
  }
}
```

Statuscodes:

- `200` bij succesvolle simulatie
- `403` zonder provider-sessie
- `404` als `consumerPartyId` niet in de participant registry voorkomt

### `POST /api/v1/auth/logout`

Beeindigt de sessie client-side.

- Actor: geen verplichte auth in huidige implementatie
- Request body: leeg JSON-object
- Response `204` zonder body

Praktische bijzonderheid:

- De server invalideert geen token-state; de route retourneert simpelweg `204`.

## Catalogi en lookup-routes

Alle routes in deze sectie vereisen een provider-sessie.

### `GET /api/v1/norms/catalog`

Retourneert de normen-catalogus.

- Response `200`:

```json
{
  "items": [
    {
      "code": "NEN 2580",
      "label": "NEN 2580",
      "category": "metingen"
    }
  ]
}
```

### `GET /api/v1/roles/gebora`

Retourneert de GEBORA-rollen.

- Response `200`:

```json
{
  "items": [
    {
      "code": "Aannemer",
      "label": "Aannemer",
      "description": "Uitvoerende hoofdaannemer."
    }
  ]
}
```

### `GET /api/v1/document-types/nen2084`

Retourneert een vaste catalogus met documenttypen.

- Response `200`:

```json
{
  "items": [
    {
      "code": "Overeenkomst",
      "label": "Overeenkomst",
      "category": "Contractueel"
    }
  ]
}
```

### `GET /api/v1/value-streams/gebora`

Retourneert vaste GEBORA-value-streams.

- Response `200`:

```json
{
  "items": [
    {
      "code": "4",
      "label": "Bouwwerk realisatie",
      "description": "Uitvoering, bouwproductie en oplevering"
    }
  ]
}
```

### `GET /api/v1/delegations/participants`

Zoekt deelnemers in de registry.

- Queryparameters:
  - `search` optioneel
  - `requiredDsgoRole` optioneel
- Response `200`:

```json
{
  "items": [
    {
      "partyId": "did:ishare:EU.NL.NTRNL-09036504",
      "name": "...",
      "membershipStatus": "active",
      "dsgoRoles": ["ServiceConsumer"]
    }
  ]
}
```

Praktische bijzonderheid:

- De backend gebruikt `requiredDsgoRole` als filter richting de registry, niet als aparte hard validation op andere endpoints.

## Projectbeheer

Alle projectbeheer-routes vereisen een provider-sessie en ownership op het project, tenzij anders vermeld. Zie de [projects tabel](reference/database/schema.md#projects) in het database schema voor het onderliggende datamodel.

### `GET /api/v1/projects`

Geeft alle projecten van de ingelogde provider.

- Response `200`:

```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Smoke Project",
      "status": "draft",
      "fileCount": 1,
      "normCount": 1,
      "datasourceCount": 1,
      "lastIndexedAt": null
    }
  ]
}
```

### `POST /api/v1/projects`

Maakt een nieuw project aan.

- Request body:

```json
{
  "name": "Stationsplein 12",
  "description": "Optioneel",
  "nenLabel": "NEN 2580",
  "status": "draft"
}
```

- Response `201`:

```json
{
  "id": "uuid",
  "name": "Stationsplein 12",
  "status": "draft",
  "ownerPartyId": "did:ishare:EU.NL.NTRNL-98499327"
}
```

### `GET /api/v1/projects/{project_id}`

Geeft projectdetail en simpele statistieken.

- Response `200`:

```json
{
  "id": "uuid",
  "name": "Stationsplein 12",
  "description": "Optioneel",
  "status": "draft",
  "ownerPartyId": "did:ishare:EU.NL.NTRNL-98499327",
  "stats": {
    "files": 3,
    "indexedFiles": 2
  }
}
```

Statuscodes:

- `200`
- `404` als project niet bestaat
- `403` als provider geen eigenaar is

### `PATCH /api/v1/projects/{project_id}`

Werkt projectmetadata bij.

- Request body:

```json
{
  "name": "Nieuwe naam",
  "description": "Nieuwe omschrijving",
  "status": "configured"
}
```

- Response `200`:

```json
{
  "id": "uuid",
  "name": "Nieuwe naam",
  "status": "configured"
}
```

### `DELETE /api/v1/projects/{project_id}`

Verwijdert een project.

- Response `204` zonder body

Statuscodes:

- `204`
- `404` als project niet bestaat
- `403` als provider geen eigenaar is

Praktische bijzonderheid:

- De route bestaat en wordt ook door de frontend gebruikt.

## Datasources en uploads

### `GET /api/v1/projects/{project_id}/datasources`

Geeft gekoppelde datasources voor een project.

- Response `200`:

```json
{
  "items": [
    {
      "id": "uuid",
      "type": "upload",
      "status": "connected",
      "displayName": "Uploads",
      "lastSyncAt": null
    }
  ]
}
```

### `POST /api/v1/projects/{project_id}/datasources`

Maakt een datasource aan.

- Request body:

```json
{
  "type": "upload",
  "config": {
    "displayName": "Uploads"
  }
}
```

- Response `201`:

```json
{
  "id": "uuid",
  "type": "upload",
  "status": "connected",
  "configMasked": {
    "displayName": "Uploads"
  }
}
```

Statuscodes:

- `201`
- `400` met foutenvelop als `type` niet `upload` is
- `404` als project niet bestaat

Praktische bijzonderheid:

- In v1 accepteert de backend alleen `type: "upload"`.

### `POST /api/v1/projects/{project_id}/datasources/{datasource_id}/discover`

Start een async discover-job.

- Request body:

```json
{
  "rootPath": "/"
}
```

- Response `202`:

```json
{
  "jobId": "queue-job-id",
  "status": "discovering"
}
```

Praktische bijzonderheden:

- De route bestaat ook voor `upload` datasources.
- De response bevat een queue-job-id als string, geen projectgebonden indexing job-id.

### `GET /api/v1/projects/{project_id}/datasources/{datasource_id}/tree`

Retourneert de boomstructuur van staged folders en documenten.

- Response `200`:

```json
{
  "root": {
    "id": "root",
    "path": "",
    "type": "folder",
    "children": [
      {
        "id": "file-id",
        "path": "contracts/2026/report.pdf",
        "type": "file"
      }
    ]
  }
}
```

### `POST /api/v1/projects/{project_id}/datasources/{datasource_id}/uploads`

Uploadt een of meer bestanden.

- Content type: `multipart/form-data`
- Form fields:
  - `files`: herhaalbaar, verplicht
  - `relativePaths`: herhaalbaar, optioneel
  - `targetPath`: optioneel

Voorbeeld:

```bash
curl -X POST /api/v1/projects/{project_id}/datasources/{datasource_id}/uploads \
  -H "Authorization: Bearer <token>" \
  -F "files=@report.pdf" \
  -F "relativePaths=contracts/2026/report.pdf" \
  -F "targetPath=inbox"
```

- Response `201`:

```json
{
  "uploaded": [
    {
      "documentId": "uuid",
      "fileName": "report.pdf",
      "size": 11,
      "path": "inbox/contracts/2026/report.pdf"
    }
  ]
}
```

Statuscodes:

- `201`
- `400` als het aantal `relativePaths` niet overeenkomt met het aantal files
- `404` als project of datasource niet bestaat

Praktische bijzonderheden:

- `relativePaths` bepaalt het genormaliseerde bronpad per bestand.
- `targetPath` wordt ervoor geplaatst.
- Een bestaande staged file op hetzelfde pad wordt geupdate in plaats van gedupliceerd.

## AI-config

Zie [ADR-005](reference/decisions/architecture-decisions.md#adr-005--bring-your-own-model) voor de Bring Your Own Model architectuurbeslissing.

### `GET /api/v1/projects/{project_id}/ai-config`

Geeft de actieve AI-config of de v1-defaults terug.

- Response `200` zonder opgeslagen config:

```json
{
  "provider": "gemini",
  "model": "gemini-3-flash-preview",
  "apiKeySet": true,
  "chunking": {
    "size": 800,
    "overlap": 120
  }
}
```

- Response `200` met opgeslagen config:

```json
{
  "provider": "gemini",
  "model": "gemini-test",
  "apiKeySet": true,
  "chunking": {
    "size": 800,
    "overlap": 120
  }
}
```

Praktische bijzonderheid:

- `apiKeySet` is alleen een boolean. De plaintext API-key wordt nooit teruggegeven.

### `PUT /api/v1/projects/{project_id}/ai-config`

Slaat AI-config op.

- Request body:

```json
{
  "provider": "gemini",
  "model": "gemini-test",
  "apiKey": "project-test-key",
  "chunking": {
    "size": 800,
    "overlap": 120
  }
}
```

- Response `200`:

```json
{
  "provider": "gemini",
  "model": "gemini-test",
  "apiKeySet": true,
  "updatedAt": "2026-03-31T10:00:00"
}
```

Statuscodes:

- `200`
- `400` met foutenvelop als `provider` niet `gemini` is
- `404` als project niet bestaat

Praktische bijzonderheid:

- Alleen `gemini` wordt ondersteund in v1.

## Normen, access matrix en delegaties

Zie [ADR-004](reference/decisions/architecture-decisions.md#adr-004--provider-side-autorisatie) voor de achtergrond bij provider-side autorisatie en het access matrix model.

### `PUT /api/v1/projects/{project_id}/norms`

Slaat de projectnormen en indexing-instructies op.

- Request body:

```json
{
  "selectedNorms": ["NEN 2580", "NEN 2767"],
  "indexingInstructions": "Classificeer documenten."
}
```

- Response `200`:

```json
{
  "selectedNorms": ["NEN 2580", "NEN 2767"],
  "instructionsPreview": "Classificeer documenten."
}
```

Praktische bijzonderheid:

- Er is geen losse `GET /projects/{project_id}/norms`; de opgeslagen normen komen terug via indexing summary.

### `GET /api/v1/projects/{project_id}/roles/access-matrix`

Geeft de opgeslagen access matrix terug.

- Response `200`:

```json
{
  "entries": [
    {
      "roleCode": "Aannemer",
      "resourceType": "folder",
      "resourceId": "node-12",
      "path": "/Realisatie",
      "allowRead": true,
      "inherited": true
    }
  ]
}
```

Praktische bijzonderheid:

- `inherited` wordt in de response afgeleid als `resourceType == "folder"`.

### `PUT /api/v1/projects/{project_id}/roles/access-matrix`

Vervangt de volledige access matrix.

- Request body:

```json
{
  "entries": [
    {
      "roleCode": "Aannemer",
      "resourceType": "folder",
      "resourceId": "node-12",
      "path": "/Realisatie",
      "allowRead": true
    }
  ]
}
```

- Response `200`:

```json
{
  "updatedCount": 1,
  "documentAclVersion": "2026-03-31T10:00:00"
}
```

Praktische bijzonderheid:

- De backend wist eerst alle bestaande regels voor het project en slaat daarna de nieuwe set op.

### `GET /api/v1/projects/{project_id}/delegations`

Geeft projectdelegaties terug.

- Response `200`:

```json
{
  "items": [
    {
      "roleCode": "Aannemer",
      "partyId": "did:ishare:EU.NL.NTRNL-09036504",
      "partyName": "..."
    }
  ]
}
```

### `PUT /api/v1/projects/{project_id}/delegations`

Vervangt alle delegaties voor een project.

- Request body:

```json
{
  "items": [
    {
      "roleCode": "Aannemer",
      "partyId": "did:ishare:EU.NL.NTRNL-09036504"
    }
  ]
}
```

- Response `200`:

```json
{
  "items": [
    {
      "roleCode": "Aannemer",
      "partyId": "did:ishare:EU.NL.NTRNL-09036504",
      "partyName": "..."
    }
  ],
  "validation": {
    "allParticipantsExist": true
  }
}
```

Statuscodes:

- `200`
- `400` met foutenvelop `invalid_participant` als een participant onbekend is
- `404` als project niet bestaat

## Indexing

### `GET /api/v1/projects/{project_id}/indexing/summary`

Geeft de huidige readiness-status voor indexing.

- Response `200`:

```json
{
  "project": {
    "id": "uuid",
    "name": "Smoke Project",
    "status": "draft"
  },
  "datasources": [
    {
      "id": "uuid",
      "type": "upload",
      "status": "connected",
      "displayName": "Uploads"
    }
  ],
  "norms": {
    "selectedNorms": ["NEN 2580"],
    "instructions": "Classificeer documenten."
  },
  "delegations": {
    "count": 1
  },
  "accessMatrix": {
    "count": 3
  },
  "readyToStart": false,
  "warnings": [
    "No staged documents available.",
    "AI config is missing."
  ]
}
```

Praktische bijzonderheid:

- Readiness kijkt onder andere naar staged documenten, AI-config, Jina API key en geselecteerde normen.

### `POST /api/v1/projects/{project_id}/indexing-jobs`

Start een indexing job of retourneert de actieve job als er al een `queued` of `running` job bestaat.

- Request body:

```json
{
  "mode": "full",
  "reindex": true
}
```

- Response `202`:

```json
{
  "jobId": "uuid",
  "status": "queued",
  "progress": 0,
  "totalFiles": 0,
  "indexedFiles": 0,
  "failedFiles": 0,
  "startedAt": null,
  "finishedAt": null,
  "errorMessage": null
}
```

Statuscodes:

- `202` bij nieuwe of hergebruikte actieve job
- `400` met platte `detail` als geen datasource bestaat
- `409` met foutenvelop `indexing_not_ready` en `warnings` als project niet klaar is voor indexing
- `404` als project niet bestaat

Praktische bijzonderheden:

- De route maakt geen tweede actieve job aan als er al een job in `queued` of `running` staat.
- `jobId` is de database-id van de indexing job, niet de queue-job-id.

### `GET /api/v1/projects/{project_id}/indexing-jobs/latest`

Geeft de laatste indexing job voor het project terug.

- Response `200`: hetzelfde schema als hierboven

Statuscodes:

- `200`
- `404` met platte `detail` als geen job bestaat

### `GET /api/v1/projects/{project_id}/indexing-jobs/{job_id}`

Geeft een specifieke indexing job terug.

- Response `200`: hetzelfde schema als hierboven

Statuscodes:

- `200`
- `404` met platte `detail` als project of job niet bestaat, of job niet bij project hoort

## Consumer API

Alle consumer-routes vereisen een consumer-sessie, behalve dat search op een project zonder actieve index eerst leeg kan terugkomen voordat delegatie wordt gecontroleerd.

### `GET /api/v1/consumer/projects`

Geeft alleen projecten terug waarvoor de consumer een delegatie heeft.

- Response `200`:

```json
{
  "items": [
    {
      "id": "uuid",
      "name": "Chat Project",
      "status": "draft",
      "resolvedRole": "Aannemer",
      "accessibleFileCount": 1
    }
  ]
}
```

### `POST /api/v1/consumer/projects/{project_id}/search`

Zoekt binnen een project.

- Request body:

```json
{
  "query": "fundering",
  "filters": {
    "norms": ["NEN 2580"]
  },
  "page": 1,
  "pageSize": 20,
  "includeBlocked": true
}
```

- Response `200`:

```json
{
  "accessContext": {
    "consumerPartyId": "did:ishare:EU.NL.NTRNL-09036504",
    "resolvedRole": "Aannemer"
  },
  "results": [
    {
      "documentId": "uuid",
      "title": "hello.txt",
      "snippet": "hello world",
      "access": "allowed",
      "path": "inbox/hello.txt"
    },
    {
      "documentId": "uuid-2",
      "title": "secret.pdf",
      "snippet": null,
      "access": "blocked",
      "path": "private/secret.pdf"
    }
  ],
  "totals": {
    "allowed": 1,
    "blocked": 1
  }
}
```

Statuscodes:

- `200`
- `403` met foutenvelop als de consumer geen delegatie heeft
- `404` met foutenvelop als project niet bestaat

Praktische bijzonderheden:

- Alleen `filters.norms` wordt functioneel gebruikt; andere filterkeys worden genegeerd.
- `includeBlocked: true` voegt geblokkeerde documenten toe als metadata-only hits.
- Als een project nog geen actieve index heeft, geeft de route `200` met lege resultaten terug in plaats van `409`.

### `GET /api/v1/consumer/projects/{project_id}/documents/{document_id}`

Geeft documentmetadata terug voor een toegestane consumer.

- Response `200`:

```json
{
  "documentId": "uuid",
  "title": "hello.txt",
  "path": "inbox/hello.txt",
  "snippet": "Roof inspection",
  "downloadUrl": "/api/v1/consumer/projects/{project_id}/documents/{document_id}/download"
}
```

Statuscodes:

- `200`
- `403` met foutenvelop als de delegatie of document-ACL ontbreekt
- `404` met foutenvelop als project of document niet bestaat

### `GET /api/v1/consumer/projects/{project_id}/documents/{document_id}/download`

Downloadt het documentbestand.

- Response `200`: binaire file response

Statuscodes:

- `200`
- `403` met foutenvelop als documenttoegang ontbreekt
- `404` met foutenvelop als document niet bestaat

Praktische bijzonderheid:

- Deze route gebruikt dezelfde documenttoegangscontrole als de metadata-route.

## Project chat API

Deze routes worden gebruikt voor chatten over een project en voor inline document-openen vanuit chatresultaten.

### Toegangsregels

Toegang is toegestaan voor:

- de provider die eigenaar van het project is
- een consumer met delegatie op het project

Een niet-ingelogde gebruiker of een provider zonder ownership krijgt `403`.

### `POST /api/v1/projects/{project_id}/chat/stream`

Start een SSE-chatstream.

- Actor: project-owner provider of gedelegeerde consumer
- Request body:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Wanneer is het dak geinspecteerd?"
    }
  ],
  "filters": {
    "norms": ["NEN 2580"],
    "document_ids": ["uuid"]
  }
}
```

Requestregels:

- `messages` moet minimaal 1 item bevatten
- de laatste message moet `role: "user"` hebben
- toegestane rollen zijn `user` en `assistant`

HTTP-statuscodes:

- `200` bij succesvolle streamstart
- `403` als de caller geen toegang heeft
- `404` als project niet bestaat
- `409` met foutenvelop `index_not_ready` als het project nog geen actieve index heeft

Response content type:

```http
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
```

Mogelijke SSE-events:

- `status`

```text
event: status
data: {"phase": "started"}
```

- `retrieval`

```text
event: retrieval
data: {"phase": "progress", "queryCount": 4, "completedQueries": 2, "sourcesUsed": 5}
```

- `tool`

```text
event: tool
data: {"tool": "search_project", "phase": "completed", "uniqueDocumentCount": 3}
```

- `token`

```text
event: token
data: {"text": "Hello"}
```

- `done`

```text
event: done
data: {"output": "Hello world", "usage": {"requests": 1, "inputTokens": 2, "outputTokens": 3}}
```

- `error`

```text
event: error
data: {"message": "Project chat stream failed"}
```

Praktische bijzonderheden:

- Runtime-fouten na start van de stream komen als SSE `error`, niet als HTTP-foutcode.
- De backend ondersteunt documentfiltering via `filters.document_ids`, met snake_case in de request body.

### `GET /api/v1/projects/{project_id}/documents/{document_id}/open`

Opent een document inline voor provider-owner of gedelegeerde consumer.

- Response `200`: inline file response

Statuscodes:

- `200`
- `403` met foutenvelop als toegang ontbreekt
- `404` met foutenvelop als project of document niet bestaat

Praktische bijzonderheden:

- Deze route staat buiten `/consumer` zodat dezelfde link bruikbaar is in chat-antwoorden voor zowel provider als consumer.
- De response zet `content-disposition: inline`.

## Audit API

Audit-routes vereisen een provider-sessie. Zie de [audit_logs tabel](reference/database/schema.md#audit_logs) voor het onderliggende datamodel.

### `GET /api/v1/audit-logs`

Geeft audit-events terug.

- Queryparameters:
  - `projectId` optioneel, UUID
  - `actorPartyId` optioneel
  - `targetPartyId` optioneel
  - `eventDomain` optioneel
  - `eventAction` optioneel
  - `from` optioneel, datetime
  - `to` optioneel, datetime
  - `page` optioneel, default `1`
  - `pageSize` optioneel, default `50`, max `200`

- Response `200`:

```json
{
  "items": [
    {
      "id": "uuid",
      "occurredAt": "2026-03-31T10:00:00",
      "projectId": "uuid",
      "datasourceId": null,
      "jobId": null,
      "eventDomain": "search",
      "eventAction": "execute",
      "outcome": "success",
      "source": "api",
      "summary": "Zoekopdracht uitgevoerd in project ...",
      "actor": {
        "actorType": "consumer",
        "partyId": "did:ishare:EU.NL.NTRNL-09036504",
        "partyName": "..."
      },
      "target": {
        "partyId": "did:ishare:EU.NL.NTRNL-09036504",
        "roleCode": "Aannemer"
      },
      "resource": {
        "type": "project",
        "id": "uuid",
        "path": null
      }
    }
  ],
  "page": 1,
  "pageSize": 50,
  "total": 1
}
```

Statuscodes:

- `200`
- `403` als de sessie geen provider-sessie is

Praktische bijzonderheden:

- Niet-admin providers zien alleen logs van hun eigen `owner_party_id`.
- Audit-admin providers kunnen alle logs lezen.

### `GET /api/v1/audit-logs/{event_id}`

Geeft detail van een audit-event terug.

- Response `200`:

```json
{
  "id": "uuid",
  "occurredAt": "2026-03-31T10:00:00",
  "projectId": "uuid",
  "datasourceId": null,
  "jobId": null,
  "eventDomain": "search",
  "eventAction": "execute",
  "outcome": "success",
  "source": "api",
  "summary": "Zoekopdracht uitgevoerd in project ...",
  "actor": {
    "actorType": "consumer",
    "partyId": "did:ishare:EU.NL.NTRNL-09036504",
    "partyName": "...",
    "tokenId": "uuid"
  },
  "target": {
    "partyId": "did:ishare:EU.NL.NTRNL-09036504",
    "roleCode": "Aannemer"
  },
  "resource": {
    "type": "project",
    "id": "uuid",
    "path": null
  },
  "ownerPartyId": "did:ishare:EU.NL.NTRNL-98499327",
  "expiresAt": "2027-03-31T10:00:00",
  "payload": {
    "query": "hello",
    "totals": {
      "allowed": 1,
      "blocked": 0
    }
  }
}
```

Statuscodes:

- `200`
- `403` als de sessie geen provider-sessie is of geen toegang tot het event heeft
- `404` als het event niet bestaat

## Integratieflows

### Flow 1: provider login en project aanmaken

```bash
curl -X POST /api/v1/auth/provider/login \
  -H "Content-Type: application/json" \
  -d "{}"
```

Response:

```json
{
  "token": "<provider-token>",
  "user": {
    "actorType": "provider",
    "partyId": "did:ishare:EU.NL.NTRNL-98499327",
    "partyName": "...",
    "simulation": false,
    "dsgoRoles": ["..."],
    "certificateStatus": "mocked-valid"
  }
}
```

Gebruik daarna het token om een project aan te maken:

```bash
curl -X POST /api/v1/projects \
  -H "Authorization: Bearer <provider-token>" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"Smoke Project\",\"status\":\"draft\"}"
```

### Flow 2: datasource upload en indexing starten

1. Maak een upload-datasource:

```bash
curl -X POST /api/v1/projects/{project_id}/datasources \
  -H "Authorization: Bearer <provider-token>" \
  -H "Content-Type: application/json" \
  -d "{\"type\":\"upload\",\"config\":{\"displayName\":\"Uploads\"}}"
```

2. Upload een bestand:

```bash
curl -X POST /api/v1/projects/{project_id}/datasources/{datasource_id}/uploads \
  -H "Authorization: Bearer <provider-token>" \
  -F "files=@hello.txt" \
  -F "targetPath="
```

3. Sla AI-config op:

```bash
curl -X PUT /api/v1/projects/{project_id}/ai-config \
  -H "Authorization: Bearer <provider-token>" \
  -H "Content-Type: application/json" \
  -d "{\"provider\":\"gemini\",\"model\":\"gemini-test\",\"apiKey\":\"project-test-key\",\"chunking\":{\"size\":800,\"overlap\":120}}"
```

4. Sla normen op:

```bash
curl -X PUT /api/v1/projects/{project_id}/norms \
  -H "Authorization: Bearer <provider-token>" \
  -H "Content-Type: application/json" \
  -d "{\"selectedNorms\":[\"NEN 2580\"],\"indexingInstructions\":\"Classificeer documenten.\"}"
```

5. Controleer readiness:

```bash
curl -X GET /api/v1/projects/{project_id}/indexing/summary \
  -H "Authorization: Bearer <provider-token>"
```

6. Start indexing:

```bash
curl -X POST /api/v1/projects/{project_id}/indexing-jobs \
  -H "Authorization: Bearer <provider-token>" \
  -H "Content-Type: application/json" \
  -d "{\"mode\":\"full\",\"reindex\":true}"
```

### Flow 3: consumer search en document ophalen

1. Simuleer een consumer:

```bash
curl -X POST /api/v1/auth/consumer/simulate \
  -H "Authorization: Bearer <provider-token>" \
  -H "Content-Type: application/json" \
  -d "{\"consumerPartyId\":\"did:ishare:EU.NL.NTRNL-09036504\"}"
```

2. Zoek in het project:

```bash
curl -X POST /api/v1/consumer/projects/{project_id}/search \
  -H "Authorization: Bearer <consumer-token>" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"hello\",\"filters\":{\"norms\":[\"NEN 2580\"]},\"page\":1,\"pageSize\":20,\"includeBlocked\":true}"
```

3. Vraag documentmetadata op:

```bash
curl -X GET /api/v1/consumer/projects/{project_id}/documents/{document_id} \
  -H "Authorization: Bearer <consumer-token>"
```

4. Download het document:

```bash
curl -X GET /api/v1/consumer/projects/{project_id}/documents/{document_id}/download \
  -H "Authorization: Bearer <consumer-token>" \
  -O -J
```

### Flow 4: chat stream met SSE-events

Request:

```bash
curl -N -X POST /api/v1/projects/{project_id}/chat/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":\"When was the roof inspected?\"}]}"
```

Voorbeeldstream:

```text
event: status
data: {"phase":"started"}

event: retrieval
data: {"phase":"started","queryCount":4,"completedQueries":0,"sourcesUsed":0}

event: tool
data: {"tool":"search_project","phase":"completed","uniqueDocumentCount":3}

event: token
data: {"text":"See "}

event: token
data: {"text":"Roof inspection"}

event: done
data: {"output":"See Roof inspection","usage":{"requests":1,"inputTokens":1,"outputTokens":1}}
```

### Flow 5: audit-log query met filters

```bash
curl -X GET "/api/v1/audit-logs?projectId={project_id}&eventDomain=search&page=1&pageSize=50" \
  -H "Authorization: Bearer <provider-token>"
```

Gebruik daarna een `id` uit de lijst voor detail:

```bash
curl -X GET /api/v1/audit-logs/{event_id} \
  -H "Authorization: Bearer <provider-token>"
```

## Bekende implementatiegrenzen

- Alleen `upload` datasources zijn via de API aan te maken.
- Alleen `gemini` is als AI-provider toegestaan (zie [ADR-005](reference/decisions/architecture-decisions.md#adr-005--bring-your-own-model)).
- Consumer-auth is een provider-gestarte simulatie, geen zelfstandige consumer-login.
- Project chat werkt alleen als een project een actieve index heeft.
- Search gebruikt functioneel alleen `filters.norms`; andere filtervelden worden momenteel niet verwerkt.
- Foutresponses zijn niet volledig uniform tussen alle routes.

## Operationele endpoints

Naast de applicatie-API expose't FastAPI ook deze operationele routes:

- `GET /health`
- `GET /docs`
- `GET /docs/oauth2-redirect`
- `GET /redoc`
- `GET /openapi.json`

Praktische noot:

- `/docs`, `/redoc` en `/openapi.json` zijn framework-gegenereerde endpoints en geen apart domeincontract bovenop de routes in deze handleiding.

## Appendix: volledige route-inventaris

### Applicatie-API

| Methode | Pad | Actor | Omschrijving |
|---|---|---|---|
| GET | `/health` | geen | Simpele healthcheck |
| POST | `/api/v1/auth/provider/login` | geen | Start provider-sessie |
| GET | `/api/v1/auth/session` | provider of consumer | Lees huidige sessie |
| POST | `/api/v1/auth/consumer/simulate` | provider | Start consumer-simulatie |
| POST | `/api/v1/auth/logout` | optioneel | Retourneert altijd `204` |
| GET | `/api/v1/norms/catalog` | provider | Normen-catalogus |
| GET | `/api/v1/roles/gebora` | provider | GEBORA-rollen |
| GET | `/api/v1/document-types/nen2084` | provider | Documenttypen-catalogus |
| GET | `/api/v1/value-streams/gebora` | provider | GEBORA-value-streams |
| GET | `/api/v1/delegations/participants` | provider | Registry participant-search |
| GET | `/api/v1/projects` | provider | Provider-projectlijst |
| POST | `/api/v1/projects` | provider | Project aanmaken |
| GET | `/api/v1/projects/{project_id}` | provider-owner | Projectdetail |
| PATCH | `/api/v1/projects/{project_id}` | provider-owner | Project bijwerken |
| DELETE | `/api/v1/projects/{project_id}` | provider-owner | Project verwijderen |
| GET | `/api/v1/projects/{project_id}/datasources` | provider-owner | Datasources tonen |
| POST | `/api/v1/projects/{project_id}/datasources` | provider-owner | Datasource aanmaken |
| POST | `/api/v1/projects/{project_id}/datasources/{datasource_id}/discover` | provider-owner | Discover-job starten |
| GET | `/api/v1/projects/{project_id}/datasources/{datasource_id}/tree` | provider-owner | Datasource tree ophalen |
| POST | `/api/v1/projects/{project_id}/datasources/{datasource_id}/uploads` | provider-owner | Bestanden uploaden |
| GET | `/api/v1/projects/{project_id}/ai-config` | provider-owner | AI-config lezen |
| PUT | `/api/v1/projects/{project_id}/ai-config` | provider-owner | AI-config opslaan |
| PUT | `/api/v1/projects/{project_id}/norms` | provider-owner | Projectnormen opslaan |
| GET | `/api/v1/projects/{project_id}/roles/access-matrix` | provider-owner | Access matrix lezen |
| PUT | `/api/v1/projects/{project_id}/roles/access-matrix` | provider-owner | Access matrix vervangen |
| GET | `/api/v1/projects/{project_id}/delegations` | provider-owner | Delegaties lezen |
| PUT | `/api/v1/projects/{project_id}/delegations` | provider-owner | Delegaties vervangen |
| GET | `/api/v1/projects/{project_id}/indexing/summary` | provider-owner | Indexing readiness |
| POST | `/api/v1/projects/{project_id}/indexing-jobs` | provider-owner | Indexing starten of hergebruiken |
| GET | `/api/v1/projects/{project_id}/indexing-jobs/latest` | provider-owner | Laatste indexing job |
| GET | `/api/v1/projects/{project_id}/indexing-jobs/{job_id}` | provider-owner | Specifieke indexing job |
| GET | `/api/v1/consumer/projects` | consumer | Consumer-projectlijst |
| POST | `/api/v1/consumer/projects/{project_id}/search` | consumer | Zoeken in project |
| GET | `/api/v1/consumer/projects/{project_id}/documents/{document_id}` | consumer | Documentmetadata ophalen |
| GET | `/api/v1/consumer/projects/{project_id}/documents/{document_id}/download` | consumer | Document downloaden |
| POST | `/api/v1/projects/{project_id}/chat/stream` | provider-owner of gedelegeerde consumer | SSE-chat |
| GET | `/api/v1/projects/{project_id}/documents/{document_id}/open` | provider-owner of gedelegeerde consumer | Inline document openen |
| GET | `/api/v1/audit-logs` | provider | Audit-events lijst |
| GET | `/api/v1/audit-logs/{event_id}` | provider | Audit-event detail |

### Framework-generated docs

| Methode | Pad | Omschrijving |
|---|---|---|
| GET | `/docs` | Swagger UI |
| GET | `/docs/oauth2-redirect` | Swagger OAuth redirect helper |
| GET | `/redoc` | ReDoc UI |
| GET | `/openapi.json` | OpenAPI-document |
