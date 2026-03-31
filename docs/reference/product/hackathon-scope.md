# Hackathon Scope — Gevondr

## Wat is gebouwd

Deze repository bevat de **volledige werkende applicatie** die is gebouwd voor de DigiGO Hackathon 2026. Het demonstreert hoe het Vondr-platform integreert met het DSGO-stelsel.

### Functionaliteit in deze repo

| Feature | Status |
|---|---|
| Provider login (iSHARE/DSGO) | Werkend (mocked certificaat) |
| Projectbeheer (CRUD) | Volledig |
| Datasource upload | Volledig |
| AI-configuratie (Bring Your Own Model) | Volledig |
| Normen selectie (NEN-catalogus) | Volledig |
| GEBORA ketenrol-gebaseerde access matrix | Volledig |
| Delegaties aan DSGO-deelnemers | Volledig |
| Document indexering pipeline | Volledig |
| Consumer simulatie | Volledig |
| Zoeken met rolgebaseerde filtering | Volledig |
| Project chat (RAG met SSE streaming) | Volledig |
| Audit logging (compliance trail) | Volledig |
| Docker Compose full-stack deployment | Volledig |

### Wat is NIET opgenomen

De **Vondr platform-broncode** is niet opgenomen in deze repository. Dit betreft:

- Het productie-Vondr platform en de bijbehorende services
- Proprietary document processing algoritmes
- Productie-configuratie en deployment pipelines
- Klantspecifieke integraties

De code in deze repo is specifiek geschreven voor de hackathon en laat zien **hoe** het platform met het DSGO werkt, zonder de volledige broncode van het platform bloot te geven.

## Team

**Team Vondr** — Milan, Lennart & Dirk

AI-platform voor de bouw- en infrasector. Structuuragnostisch. Werkt in alle 17 GEBORA waardestromen, alle fasen van de BouwwerkLevensCyclus, conform FAIR-principes.

## Claims

| Claim | Waarde |
|---|---|
| **DSGO proof** | Gebouwd op het DSGO met IAA via iSHARE |
| **0 opschoning** | Upload zoals het is — geen conversie nodig |
| **99% vindbaarheid** | Zonder handmatige classificatie* |
| **10s vindtijd** | Was 45 minuten* |

\* Gebaseerd op vergelijkbare projecten met tunneldocumentatie en PhD-onderzoek naar documentretrieval in de gebouwde omgeving.
