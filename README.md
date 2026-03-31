# Gevondr

**AI indexeert ongestructureerde documenten, DSGO verbindt de keten.**

> *"Ik wil niet zoeken, ik wil vinden."*

Gevondr is een platform waar de Data Rechthebbende ongestructureerde data uploadt en de Data Service Consumer het veilig ontvangt — gebouwd op het DSGO.

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
# Installeer dependencies
uv sync

# Stel environment variabelen in
cp .env.example .env
# Vul je iSHARE certificaat en private key pad in

# Authenticeer met DSGO en lijst deelnemers
uv run python main.py
```

---

## Repo-structuur

```
src/
  dsgo/           ← iSHARE authenticatie + participantenregister
    auth.py       ← JWT + OAuth2 token flow
    registry.py   ← DSGO deelnemers ophalen
    config.py     ← Environment configuratie
  provider/       ← Data Service Provider (Vondr zoek-API)
  consumer/       ← Data Service Consumer client
  satellite/      ← Satellietdata client

docs/             ← Projectdocumentatie
  1-hackathon.md  ← Teams, jury, puntentelling, planning
  2-dsgo.md       ← DSGO, IAA, rollenmodel, RASCI, IAA flow
  3-gebora.md     ← GEBORA, BLC, waardestromen, CIM, principes
  4-plan.md       ← Strategie, pitch, deliverables

presentatie/      ← One-pager + presentatie slides
demo-projecten/   ← Echt projectarchief (IJ-oeverpark Amsterdam)
assets/           ← Brandbook, verwerkte brondocumenten
```

---

## Documentatie

| Doc | Inhoud |
|---|---|
| [1-hackathon.md](docs/1-hackathon.md) | 12 teams, jury, puntentelling, specialisten, planning |
| [2-dsgo.md](docs/2-dsgo.md) | DSGO, IAA-model, rollenmodel, RASCI-matrix, technische bevindingen |
| [3-gebora.md](docs/3-gebora.md) | GEBORA, architectuurprincipes, BLC, waardestromen, CIM |
| [4-plan.md](docs/4-plan.md) | Vondr strategie, pitch storyline, deliverables checklist |

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

**Milan & Dirk Bakker** — AI-platform voor de bouw- en infrasector.

Structuuragnostisch. Werkt in alle 17 GEBORA waardestromen, alle fasen van de BouwwerkLevensCyclus, conform FAIR-principes.

vondr.ai · DSGO Hackathon 2026
