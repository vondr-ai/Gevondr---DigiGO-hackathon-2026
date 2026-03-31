# Database Schema — Quick Reference

Bron van waarheid: `be/src/database/models.py`

## Kerntabellen

### projects

Hoofdentiteit. Elk project heeft één eigenaar (provider).

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `name` | String(255) | Projectnaam |
| `description` | Text | Optionele omschrijving |
| `nen_label` | String(255) | Gekozen NEN-norm label |
| `status` | String(64) | `draft`, `configured`, etc. |
| `owner_party_id` | String(255) | iSHARE party ID van eigenaar |
| `owner_party_name` | String(255) | Naam van eigenaar |
| `active_index_revision_id` | UUID (FK → index_revisions) | Actieve revisie |
| `created_at` / `updated_at` | DateTime | Timestamps (UTC-naive) |

### datasources

Databronnen gekoppeld aan een project. V1 ondersteunt alleen `type: "upload"`.

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `project_id` | UUID (FK → projects) | CASCADE delete |
| `type` | String(64) | `upload` |
| `status` | String(64) | `connected` |
| `display_name` | String(255) | |
| `config` | JSON | Configuratie per type |
| `last_sync_at` | DateTime | Laatste sync |

### staged_folders / staged_documents

Staging area voor geuploade bestanden, voordat ze geindexeerd worden.

**staged_folders:** Hiërarchische mapstructuur met `parent_id` (self-referencing FK). Unique constraint op `(datasource_id, path)`.

**staged_documents:**

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `datasource_id` | UUID (FK) | |
| `project_id` | UUID (FK) | |
| `folder_id` | UUID (FK → staged_folders) | Optioneel |
| `filename` | String(255) | |
| `path` | Text | Genormaliseerd pad |
| `storage_path` | Text | Fysiek opslagpad |
| `mime_type` | String(255) | |
| `size` | Integer | Bytes |
| `sha256` | String(128) | Content hash |
| `status` | String(64) | `ready`, etc. |

### indexed_documents

Geïndexeerde documenten met AI-gegenereerde metadata. Unique constraint op `(project_id, index_revision_id, path)`.

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `project_id` | UUID (FK) | |
| `datasource_id` | UUID (FK) | |
| `staged_document_id` | UUID (FK) | Bron-document |
| `index_revision_id` | UUID (FK) | Revisie |
| `title` | String(255) | |
| `path` | Text | |
| `full_text` | Text | Geëxtraheerde tekst |
| `summary` / `short_summary` | Text | AI-samenvatting |
| `document_type` | String(100) | NEN 2084 documenttype |
| `value_streams` | JSON (list) | GEBORA value streams |
| `index_values` | JSON | Geïndexeerde waarden per norm |
| `selected_norms` | JSON (list) | Toegepaste normen |
| `allowed_role_codes` | JSON (list) | Welke GEBORA-rollen mogen lezen |
| `indexed_at` | DateTime | |

### access_matrix_entries

Rolgebaseerde toegangsregels per project. De DRH bepaalt welke GEBORA-rollen welke folders/documenten mogen zien.

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `project_id` | UUID (FK) | |
| `role_code` | String(255) | GEBORA-rol (bijv. `Aannemer`) |
| `resource_type` | String(32) | `folder` of `file` |
| `resource_id` | String(255) | Node ID |
| `path` | Text | Pad van resource |
| `allow_read` | Boolean | |

### delegations

Koppelt DSGO-deelnemers aan GEBORA-rollen voor een project. Unique constraint op `(project_id, role_code, party_id)`.

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `project_id` | UUID (FK) | |
| `role_code` | String(255) | GEBORA-rol |
| `party_id` | String(255) | iSHARE party ID |
| `party_name` | String(255) | |

### index_revisions

Versioned indexeringen. Een project heeft maximaal één actieve revisie.

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `project_id` | UUID (FK) | |
| `datasource_id` | UUID (FK) | |
| `status` | String(32) | `building`, `active`, etc. |
| `document_count` | Integer | |
| `activated_at` / `superseded_at` | DateTime | Levenscyclus |

### indexing_jobs

Voortgang van indexering.

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `project_id` | UUID (FK) | |
| `index_revision_id` | UUID (FK) | |
| `status` | String(32) | `queued`, `running`, `completed`, `failed` |
| `progress` | Integer | Percentage |
| `total_files` / `indexed_files` / `failed_files` | Integer | Tellingen |
| `warnings` | JSON (list) | |
| `error_message` | Text | |

### project_ai_configs

AI-configuratie per project (Bring Your Own Model).

| Kolom | Type | Beschrijving |
|---|---|---|
| `project_id` | UUID (PK, FK) | |
| `provider` | String(64) | `gemini` |
| `model` | String(255) | Model naam |
| `api_key` | Text | Encrypted API key |
| `chunk_size` | Integer | Default 800 |
| `chunk_overlap` | Integer | Default 120 |

### project_norm_configs

Gekozen normen en indexeringsinstructies per project.

| Kolom | Type | Beschrijving |
|---|---|---|
| `project_id` | UUID (PK, FK) | |
| `selected_norms` | JSON (list) | Bijv. `["NEN 2580", "NEN 2767"]` |
| `indexing_instructions` | Text | Custom instructies voor AI |

### audit_logs

Compliance audit trail met automatische retentie.

| Kolom | Type | Beschrijving |
|---|---|---|
| `id` | UUID (PK) | |
| `occurred_at` | DateTime | Tijdstip |
| `expires_at` | DateTime | Retentie-deadline |
| `owner_party_id` | String(255) | Eigenaar van het event |
| `project_id` | UUID (FK) | |
| `actor_type` | String(64) | `provider` of `consumer` |
| `actor_party_id` / `actor_party_name` | String | |
| `target_party_id` / `target_role_code` | String | |
| `event_domain` | String(64) | Bijv. `search`, `indexing` |
| `event_action` | String(64) | Bijv. `execute`, `start` |
| `outcome` | String(32) | `success`, `failure` |
| `summary` | Text | Leesbare beschrijving |
| `payload` | JSON | Aanvullende data |

## Relatiediagram

```
projects ──┬── datasources ──┬── staged_folders (hiërarchisch)
           │                 └── staged_documents
           ├── project_ai_configs (1:1)
           ├── project_norm_configs (1:1)
           ├── access_matrix_entries
           ├── delegations
           ├── index_revisions ── indexed_documents
           ├── indexing_jobs
           └── audit_logs
```

## Vector store (Weaviate)

Naast PostgreSQL gebruikt Gevondr **Weaviate** als vector database voor semantic search. Document chunks worden als embeddings opgeslagen en doorzocht via cosine similarity. De configuratie staat in `be/src/database/weaviate/`.
