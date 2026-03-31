# Architecture Decision Records — Gevondr

De fundamentele beslissingen waar dit platform op gebouwd is.

---

## ADR-001 — Eén platform, twee rollen

**Datum:** 2026-03-31
**Status:** Accepted
**Beslissers:** Team Vondr (Milan, Lennart & Dirk)

### Context

Het DSGO kent gescheiden rollen (Data Rechthebbende, Data Service Consumer, Data Service Utilisator). Traditioneel zijn dit aparte systemen. Wij kiezen voor één applicatie met rolgebaseerde toegang.

### Beslissing

Gevondr is één platform voor zowel producer als consumer.

**Producer (Data Rechthebbende):**
- Maakt projecten aan
- Koppelt databronnen
- Kiest normen
- Wijst organisaties en ketenrollen toe

**Consumer (DSC + DSU):**
- DSC krijgt projecttoegang, kent leesrechten toe aan DSU's
- DSU zoekt en vindt via browser of app — no-code

### Consequenties

- Eén codebase, één deployment, één login
- Rolgebaseerde UI: je ziet alleen wat bij je rol past
- Lagere drempel voor adoptie — geen apart systeem voor aanbieders en afnemers

### Alternatieven overwogen

- Aparte applicaties per DSGO-rol: hogere complexiteit, meer onderhoud, hogere drempel voor adoptie

---

## ADR-002 — DSGO als fundament: IAA met least privilege

**Datum:** 2026-03-31
**Status:** Accepted
**Beslissers:** Team Vondr (Milan, Lennart & Dirk)

### Context

Data-uitwisseling in de gebouwde omgeving vereist vertrouwen tussen partijen die elkaar niet kennen. Het DSGO biedt een gestandaardiseerd stelsel.

### Beslissing

We bouwen op het DSGO. IAA via iSHARE. Elke gebruiker ziet alleen wat die mag zien — niet meer, niet minder (least privilege).

### Consequenties

- Elke deelnemer moet een geldig iSHARE-certificaat hebben
- Autorisatie op documentniveau: de DRH bepaalt welke GEBORA ketenrollen welke documenten mogen zien
- Geblokkeerde documenten tonen metadata maar geen inhoud
- Toegang wordt geëvalueerd bij indexering — snel en voorspelbaar
- Onze oplossing is interoperabel met alle andere DSGO-datadiensten

### Alternatieven overwogen

- Eigen authenticatiesysteem zonder DSGO: niet interoperabel met de rest van de keten
- Volledige AR-delegatie: externe Authorisation Registries zijn in de acceptance-omgeving nog niet operationeel

---

## ADR-003 — Structuuragnostisch

**Datum:** 2026-03-31
**Status:** Accepted
**Beslissers:** Team Vondr (Milan, Lennart & Dirk)

### Context

De gebouwde omgeving zit vol ongestructureerde data: PDF's, scans, Word-documenten, afbeeldingen, e-mails, tekeningen en planningen. Het DSGO gaat ervan uit dat data gestructureerd wordt aangeleverd. In de praktijk is dat niet zo.

### Beslissing

Gevondr werkt met data zoals die IS, niet zoals die zou moeten zijn.

### Consequenties

- We accepteren alle gangbare documentformaten zonder opschoning of conversie
- De gebruiker kiest welke norm(en) van toepassing zijn — AI indexeert de documenten volgens die norm
- De data wordt wél geïndexeerd en doorzoekbaar gemaakt — structuur ontstaat door indexering, niet door de gebruiker
- De drempel voor adoptie is nul: upload zoals het is

### Alternatieven overwogen

- Verplichte dataconversie voor upload: hoge drempel, veel handwerk, past niet bij de realiteit van projectarchieven

---

## ADR-004 — Provider-side autorisatie

**Datum:** 2026-03-31
**Status:** Accepted
**Beslissers:** Team Vondr (Milan, Lennart & Dirk)

### Context

Het DSGO voorziet in een externe Authorisation Registry (AR). In de huidige acceptance-omgeving zijn de geregistreerde AR's nog niet operationeel.

### Beslissing

Gevondr beheert autorisatie zelf als Data Service Provider, conform GEBORA ketenrollen.

### Consequenties

- De DRH definieert per project welke rollen welke documenten mogen zien
- Zodra een externe AR operationeel is, kan de delegatietabel verplaatst worden — het model verandert niet
- De DRH houdt altijd de controle

### Alternatieven overwogen

- Wachten op externe AR: blokkeert ontwikkeling zonder meerwaarde voor het hackathon-prototype
- Geen autorisatie: niet DSGO-conform, geen least privilege

---

## ADR-005 — Bring Your Own Model

**Datum:** 2026-03-31
**Status:** Accepted
**Beslissers:** Team Vondr (Milan, Lennart & Dirk)

### Context

Organisaties in de bouw hebben verschillende eisen rond privacy, kosten en controle. Sommige willen data niet naar externe servers sturen.

### Beslissing

De gebruiker kiest zelf welk taalmodel wordt gebruikt. Jouw data, jouw model, jouw server.

### Consequenties

- Gebruikers kunnen hun eigen API-key per project instellen
- Het platform is modelagnostisch — Gemini is de standaard, maar niet de verplichting
- Data blijft bij de klant als die dat wil
- Per-project kostenbeheersing is mogelijk

### Alternatieven overwogen

- Vast model voor alle gebruikers: eenvoudiger, maar geen rekening met privacy- en kostenwensen van verschillende organisaties
