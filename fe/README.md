# Gevondr — Frontend

Vue 3 applicatie voor het Gevondr platform. Biedt de provider setup wizard en de consumer zoek- en chatinterface.

## Tech stack

| Tool | Versie | Doel |
|---|---|---|
| Vue 3 | 3.5 | UI framework (Composition API + `<script setup>`) |
| TypeScript | 5.9 | Type safety |
| Vite | 8 | Dev server + build |
| Tailwind CSS | 4 | Styling |
| Pinia | 3 | State management |
| Vue Router | 4 | Client-side routing |
| Axios | 1.14 | HTTP client |
| Markdown-it | 14 | Markdown rendering in chat |

## Starten

```bash
npm install
npm run dev
```

Draait op **http://localhost:5173**. De Vite dev server proxied `/api/v1` naar `http://localhost:8000` (backend).

## Structuur

```
src/
├── api/                ← API service layer (Axios)
│   ├── client.ts       ← Axios instance + interceptors
│   ├── auth.ts         ← Login, sessie, consumer simulatie
│   ├── projects.ts     ← Project CRUD
│   ├── datasources.ts  ← Upload, discover, tree
│   ├── ai-config.ts    ← AI model configuratie
│   ├── norms.ts        ← Normen + documenttypen
│   ├── roles.ts        ← GEBORA rollen + access matrix
│   ├── delegations.ts  ← Deelnemersdelegaties
│   ├── indexing.ts     ← Indexing jobs
│   └── project-chat.ts ← Chat streaming (SSE)
├── components/
│   ├── layout/         ← TopBar, SetupLayout, ProviderLayout, StepIndicator
│   └── ui/             ← BaseButton, BaseCard, BaseInput, BaseCheckbox, BaseRadio, BaseBadge, BaseModal
├── composables/        ← useStepNavigation
├── stores/             ← Pinia stores
│   ├── auth.ts         ← Sessie + rol state
│   ├── projects.ts     ← Projectlijst
│   └── setup.ts        ← Setup wizard state (7 stappen)
├── views/
│   ├── LoginView.vue          ← Provider login
│   ├── ProjectsView.vue       ← Projectdashboard
│   ├── setup/                 ← Provider setup wizard (6 stappen)
│   │   ├── DatasourceView.vue
│   │   ├── DocumentsView.vue
│   │   ├── AiConfigView.vue
│   │   ├── NormsView.vue
│   │   ├── DelegationsView.vue
│   │   └── OverviewView.vue
│   └── consumer/              ← Consumer interface
│       ├── SimulateView.vue
│       ├── ConsumerProjectsView.vue
│       └── ProjectChatView.vue
├── router/             ← Route definities + guards
├── types/              ← TypeScript interfaces
├── utils/              ← Error handling
└── assets/             ← CSS + afbeeldingen
```

## Scripts

| Commando | Doel |
|---|---|
| `npm run dev` | Ontwikkelserver met hot reload |
| `npm run build` | Productie-build (vue-tsc + vite) |
| `npm run preview` | Preview van productie-build |
