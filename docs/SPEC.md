# SCION — Technical Specification

> **Version:** 1.21.5-spec-phase-1
> **Last Updated:** 2026-05-28
> **Status:** Phase 1 of 3 — Sections 1-4 (Executive, Goals, Architecture, Stack)
> **Author:** Guillermo Albella, with AI-assisted drafting

---

> **Document Purpose:** Canonical reference for **WHAT SCION is, what it does, and what it deliberately does not do**. Lives alongside the code so new contributors, security auditors, and AI assistants can ground themselves without trawling commits.
>
> **Related Documents:**
> - Implementation roadmap → **ROADMAP.md**
> - Change history → **CHANGELOG.md**
> - Deploy guide → **docker/README.md** (and the public companion `scion-deploy/README.md`)
> - Internal product docs → `docs/internal_roadmap.md`, `docs/use_cases.md`, `docs/ingestion_pipelines.md`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [System Overview](#3-system-overview)
4. [Technology Stack](#4-technology-stack)
5. Functional Requirements *(Phase 2)*
6. Non-Functional Requirements *(Phase 2)*
7. Data Models *(Phase 2)*
8. Interface Contracts *(Phase 2)*
9. Golden Examples *(Phase 3)*
10. Test Scenarios & Edge Cases *(Phase 3)*
11. Reference Benchmarking *(Phase 3)*
12. Acceptance Criteria *(Phase 3)*
13. Deliverables *(Phase 3)*
14. Risk Assessment *(Phase 3)*
15. Appendix A: Glossary *(Phase 3)*
16. Appendix B: References *(Phase 3)*

---

## 1. Executive Summary

### 1.1 Purpose

**SCION** — **S**tructural **C**hange **I**ntelligence & **O**bservability **N**ode — is a web-based observability tool for Teradata data warehouses. It takes periodic *dictionary snapshots* of a customer's schema and surfaces — through a single interface — the answers a data steward, DBA, or governance lead needs but currently has to assemble manually:

- **What changed** between two points in time? (added / dropped / altered tables, views, columns)
- **What's the blast radius** of a proposed change? (which downstream objects break if I drop this column?)
- **Where does this data come from / go to?** (column-level lineage explored visually)
- **How is each object used** in production? (query volume, distinct users, last accessed)
- **What's the risk of a planned change?** (LLM-assisted reasoning grounded on actual metadata)

SCION is **read-only**: it never connects to the live Teradata, never modifies the warehouse, and never stores customer payload data. It receives metadata extracts and reasons over them offline.

### 1.2 Problem Statement

Teradata customers running large warehouses (10k+ schemas, 200k+ tables, 9M+ columns) face four recurring problems:

1. **Invisible structural drift.** Schema changes happen continuously across teams. Stewards learn about them when something breaks downstream — not when the change lands.
2. **Manual blast-radius analysis.** "What breaks if I drop this column?" is a multi-hour SQL exercise against `DBC` views, repeated every release.
3. **Tribal knowledge in lineage.** ETL flows that were documented in slide decks years ago are now the only map from raw to consumed data. The map is wrong and nobody knows.
4. **Inconsistent usage signals.** Which tables are actually used? Which views are stale? The answer lives across DBQL, PDCR, and people's heads.

Existing tooling (Kalido legacy, ad-hoc scripts, internal Teradata-built dashboards) addresses pieces of this but none ties structure + lineage + impact + usage into a single workflow.

### 1.3 Solution Approach

SCION solves these problems through a five-stage pipeline:

1. **Ingest** dictionary extracts (6 `*v_*` flat files) + optional parser lineage feed (JSON from DataDNA) + optional usage signals (DBQL/PDCR). Everything offline, all formats validated.
2. **Snapshot** the structure into a versioned, hashable, queryable representation. Snapshots are immutable; each one is the canonical "state of the warehouse at time T".
3. **Diff** any two snapshots to produce a typed list of `ChangeEvent`s with severity + breaking-or-not classification.
4. **Reason** over the changes: graph-based blast radius, criticality scoring, proactive alerts, and natural-language explanations from an LLM (TAISA) grounded on the actual data.
5. **Present** through a modern web UI: interactive graph, sortable tables, autocomplete search, drill-down panels, in-app assistant.

Everything ships as **two public-facing containers + one private installer** that any Teradatan can deploy on a customer VM in under five minutes.

### 1.4 Scope Boundary

> **Critical reading for newcomers.** SCION is intentionally a narrow product. The boundary below is what keeps it from becoming "the next over-scoped data platform". When in doubt, **default to "out of scope"**.

| ✅ Does TODAY (v1.21.4) | 🔵 Will do MAÑANA (ROADMAP) | ❌ NEVER does |
|---|---|---|
| Ingest 6-file dictionary extract from Rahul's exporter | In-app "Update now" button (v1.22) | Parse SQL, scripts, BTEQ, or KSH — that's **DataDNA** |
| Snapshot + diff + structural hash | Pipeline 3 — DBQL / Object Usage ingestion (v1.22 if Rahul confirms JSON; later if PDCR `.dat`) | Connect to a live Teradata over JDBC/ODBC |
| Server-side paginated change feed (Changes page) | Multi-region awareness (`DATA_REGION`, v1.23) | Capture lineage in real time from running queries |
| Blast-radius computation + impact summaries | Parser lineage feed integration when Rahul ships it (v1.24) | Edit the warehouse — no DDL emitted, no DML, no GRANT |
| Click-to-expand graph exploration (`/graph/focus`) | Postgres migration when multi-tenant arrives (v1.25) | Store row-level customer data — only metadata |
| TAISA Q&A grounded on real metadata, bounded context | SSO / RBAC when first multi-user deploy lands (backlog) | Replace the steward — assists, never decides |
| Usage signals + criticality scoring (from seeded data today) | Audit log UI surfacing `usage_event` + `reasoning_event` (backlog) | Provide a query optimizer or recommend index changes |
| Snapshot-pair simulation ("what if I make this change?") | Export streaming / CSV pagination (backlog) | Be a data-catalog replacement (no business glossary, no certifications) |
| Containerised deploy (one-liner installer Linux + Windows) | Naming audit final sweep (backlog) | Auto-update without user consent — Watchtower was removed in v1.21.4 |
| TAISA pre-configured in private image, no per-user setup | TAISA batch-reasoning cap (backlog) | Stream from Kafka, listen on webhooks, or push notifications externally |

### 1.5 Boundary with the Parser (DataDNA)

SCION and DataDNA are **complementary, not overlapping**. The two products together cover the end-to-end "what's in the warehouse and how does data flow through it" story; alone, each is narrow on purpose.

```
   ┌────────────────────────┐                       ┌────────────────────────┐
   │       DATADNA          │ ─── lineage JSON ───▶ │         SCION          │
   │     (Rahul's Parser)   │      via dict-import  │     (this system)      │
   ├────────────────────────┤                       ├────────────────────────┤
   │ Parses Teradata SQL    │                       │ Snapshots dictionary   │
   │ Builds AST via ANTLR4  │                       │ Diffs versions         │
   │ Extracts Tier-1/2/3    │                       │ Computes blast radius  │
   │ lineage                │                       │ Generates TAISA Q&A    │
   │ Outputs Kalido + JSON  │                       │ Visualises graph + UI  │
   └───────────┬────────────┘                       └────────────┬───────────┘
               ▲                                                 ▲
               │                                                 │
   ┌───────────┴────────────┐                       ┌────────────┴───────────┐
   │ SQL / BTEQ / KSH files │                       │ Dictionary extracts:   │
   │ DBQL / PDCR flat files │                       │   databasesv_*         │
   │                        │                       │   tablesv_*            │
   │                        │                       │   columnsv_*           │
   │                        │                       │   indicesv_*           │
   │                        │                       │   partitioningv_*      │
   │                        │                       │   tabletextv_*         │
   └────────────────────────┘                       └────────────────────────┘
```

**Mnemonic for the team:**

- DataDNA looks at the **code** (SQL) — answers "what does this query do?"
- SCION looks at the **structure** (dictionary) — answers "what does the warehouse look like and what's changing in it?"

The two meet when DataDNA ships a lineage JSON to SCION's `/parser-import` endpoint — that's the only data crossing the boundary, and it crosses in **one direction only**.

---

## 2. Goals and Non-Goals

### 2.1 Goals

| ID | Goal | Priority | Success Metric |
|----|------|----------|----------------|
| **G1** | Ingest the 6-file Teradata dictionary extract reliably at customer scale | P0 | Transcend-DevTest extract (10 716 schemas / 240k tables / 9.8M cols) ingests in under 15 min on 8c/32GB |
| **G2** | Detect structural changes between any two snapshots with typed severity | P0 | All 4 standard change types (ADDED, DROPPED, ALTERED, RENAMED) emit `ChangeEvent` rows with `severity ∈ {LOW, MEDIUM, HIGH}` and `is_breaking` flag |
| **G3** | Compute blast radius (downstream impact) of any change in bounded time | P0 | `/impact` page returns first 50 events in <2s on Transcend; deepest impacted path within 30s |
| **G4** | Provide column-level lineage exploration as an interactive graph | P0 | `/graph` renders >100 nodes without freezing; click-to-expand adds neighbours in <500 ms |
| **G5** | Generate LLM-grounded natural-language explanations of changes (TAISA) | P0 | TAISA answers any question on demo + Transcend data without context overflow; never blocks the UI on failure |
| **G6** | Surface usage signals (query count, user count, criticality) per object | P1 | Top-N usage table loads instantly; criticality score available for every object in latest snapshot |
| **G7** | Allow simulation of a proposed change ("what-if") | P1 | User can pick a target object + change type and see blast radius before committing |
| **G8** | Deploy via one-liner on any Linux VM or Windows laptop with Docker Desktop | P0 | `curl …/install.sh \| bash` (or `irm …/install.ps1 \| iex`) brings the stack up in <10 min including image pull |
| **G9** | Stay secure: private GHCR images, monthly CVE scan, no plaintext secrets in artefacts | P0 | Docker Scout reports 0 Critical / 0 High at release time; no secret in any public file |
| **G10** | Update in-place with a single user-driven action | P1 | `update.sh` / `update.ps1` finishes in <2 min on a warm cache |
| **G11** | Survive a network or LLM outage without taking the UI down | P0 | TAISA failure → graceful disabled state; `/system/version` cannot block sidebar render |
| **G12** | Be readable and extensible by a single dev with mid-level Python + React | P1 | New contributor reaches "ran a snapshot diff locally" in under one working day |
| **G13** | Support snapshot reproducibility for governance audits | P1 | `structural_hash` column is deterministic across runs on the same data |
| **G14** | Provide proactive alerts that surface risk without the user asking | P2 | `/alerts` page shows broken-lineage, orphan, and hub-changed alerts auto-computed at ingest time |
| **G15** | Be deployable behind a Teradata reverse proxy without code change | P2 | Stack accepts `X-Forwarded-*` and adapts the rendered base URL |

### 2.2 Non-Goals

> Each non-goal includes the **rationale** for why we won't do it. Anyone proposing to relax one should engage with the rationale first.

| ID | Non-Goal | Rationale |
|----|----------|-----------|
| **NG1** | SCION will **never parse SQL, scripts, BTEQ, or KSH** | That's DataDNA. Two products on the same team with overlapping scope is a maintenance nightmare. Receive lineage as JSON, don't compute it. |
| **NG2** | SCION will **never connect to a live Teradata** (JDBC/ODBC/REST) | Customer security teams object to a tool that needs live read access. Offline-only is a deliberate architectural choice that unblocks every deal. |
| **NG3** | SCION will **never capture lineage in real time** from running queries | Real-time observability is a different product class. Batch-on-demand keeps the implementation simple and the resource footprint bounded. |
| **NG4** | SCION will **never modify the warehouse** | No DDL emitted, no DML, no GRANT. SCION is observation, not control. If the user wants to act on a finding, they leave SCION and use their normal change-management flow. |
| **NG5** | SCION will **never store row-level customer data** | The DB only contains structural metadata (snapshot of dictionary views) plus optionally usage aggregates. No data values are ever persisted. |
| **NG6** | SCION is **not a data catalog** | No business glossary, no certifications, no stewardship workflows. The customer has Collibra / Alation / Atlan for that. SCION fills the **structural intelligence** gap that catalogs handle poorly. |
| **NG7** | SCION is **not a query optimizer** | Index recommendations, statistics suggestions, and physical-design advice are out of scope. The customer has Teradata Workload Analyzer and human DBAs for that. |
| **NG8** | SCION will **never auto-update silently** | Watchtower was tried in v1.21.0 and removed in v1.21.4. The cost (31 CVEs, root-equivalent `docker.sock` mount) exceeds the benefit (saving ~3 s per upgrade). Users explicitly run `update.sh`/`update.ps1`. |
| **NG9** | SCION will **never expose itself publicly without auth** | Every `/api/v1/*` route is gated by an `X-API-Key` header in production. The only exceptions are `/health/*` (liveness) and `/system/version` (banner). |
| **NG10** | SCION will **never include a built-in user/role model** in v1.x | SSO / RBAC arrives only when the first multi-user customer needs it. Until then, the deploy is single-tenant single-key. Premature flexibility = unused code = drift. |
| **NG11** | SCION will **never bundle customer data in container images** | Demo seed is generated synthetically; real customer extracts are mounted into the volume at runtime, never copied into a layer. |
| **NG12** | SCION is **not a notification platform** | No Slack/email/SMS integrations. The UI surfaces alerts; the user decides what to do with them. Notifications are a per-customer concern, not a product concern. |

---

## 3. System Overview

### 3.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          SCION Single-VM Deploy                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                  ┌─────────────────────────────────────┐                     │
│   external ──▶   │   nginx 1.29-alpine  :80           │                     │
│   (browser)      │   ─ /             → frontend       │                     │
│                  │   ─ /api/*        → backend        │                     │
│                  │   ─ /healthz      → backend ready  │                     │
│                  └────────────┬────────────────────────┘                     │
│                               │                                              │
│              ┌────────────────┼────────────────┐                             │
│              ▼                                 ▼                             │
│   ┌────────────────────┐           ┌────────────────────┐                    │
│   │  scion-frontend    │           │  scion-backend     │                    │
│   │  Next.js 16        │           │  FastAPI 0.115.6   │                    │
│   │  React 19          │           │  uvicorn 0.30.6    │                    │
│   │  standalone build  │           │  Python 3.12-slim  │                    │
│   │  :3000 (internal)  │           │  :8000 (internal)  │                    │
│   └────────────────────┘           └─────────┬──────────┘                    │
│                                              │                               │
│                                              ▼                               │
│                                    ┌────────────────────┐                    │
│                                    │  /data volume      │                    │
│                                    │  scion.db (SQLite) │                    │
│                                    │  WAL mode          │                    │
│                                    └────────────────────┘                    │
│                                              │                               │
│                                              ▼                               │
│                                    ┌────────────────────┐                    │
│                                    │  TAISA (LLM)       │                    │
│                                    │  llama-4-scout-17b │                    │
│                                    │  external API call │                    │
│                                    └────────────────────┘                    │
│                                                                              │
│   Images pulled from ghcr.io/guillealbella/* (private, PAT auth)             │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Key properties:**

- **Single-VM**, single-tenant. No clustering, no replicas, no orchestration. One customer = one VM = one stack.
- **SQLite with WAL** in a Docker named volume. Fits up to a Transcend-class warehouse comfortably; Postgres is on the v1.25 roadmap for multi-tenant.
- **Three application containers** (backend, frontend, nginx) + the volume. Watchtower was removed in v1.21.4.
- **TAISA** is the only external dependency — and it's optional. If TAISA is unreachable the reasoning features go quiet but everything else keeps working.

### 3.2 Processing Pipeline

```
External Inputs                        SCION Internal Processing                              UI Surfaces
─────────────────────────────────────────────────────────────────────────────────────────────────────────

┌──────────────┐
│  6-file      │
│  dictionary  │─┐
│  extract     │ │
│  (.dat)      │ │
└──────────────┘ │     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
                 ├────▶│  dict-import    │────▶│  snapshot       │────▶│  /snapshots     │
┌──────────────┐ │     │  endpoint       │     │  finaliser:     │     │  list, detail   │
│  Parser      │ │     │  validate +     │     │  hash, count,   │     │                 │
│  lineage     │─┤     │  persist        │     │  finalise       │     │                 │
│  JSON        │ │     └────────┬────────┘     └────────┬────────┘     │                 │
└──────────────┘ │              │                       │              │                 │
                 │              ▼                       ▼              │                 │
┌──────────────┐ │     ┌─────────────────┐     ┌─────────────────┐     │                 │
│  Usage feed  │─┘     │  graph builder  │     │  diff engine    │     │  /changes       │
│  (planned    │       │  edges from FK  │     │  paired         │────▶│  /diff/details  │
│   v1.22-23)  │       │  + parser feed  │     │  snapshots →    │     │  paginated      │
└──────────────┘       └────────┬────────┘     │  ChangeEvent[]  │     │                 │
                                │              └────────┬────────┘     │                 │
                                │                       │              │                 │
                                ▼                       ▼              │                 │
                       ┌─────────────────┐     ┌─────────────────┐     │                 │
                       │  blast radius   │     │  TAISA          │     │  /impact        │
                       │  + criticality  │────▶│  reasoning      │────▶│  /graph         │
                       │  + alerts       │     │  bounded ctx    │     │  /lineage       │
                       │  pre-aggregated │     │  llama-4-scout  │     │  /simulation    │
                       └─────────────────┘     └─────────────────┘     │  /alerts        │
                                                                       │  /intelligence  │
                                                                       │  /usage         │
                                                                       │  /metrics       │
                                                                       │  /timeline      │
                                                                       └─────────────────┘
```

Every box on the left only runs once per ingest. Every box on the right responds to user navigation in <2 s on Transcend-class data because every aggregate (impact summaries, alerts, criticality, blast radius) is **pre-computed at ingest time** and cached in dedicated tables. The page itself is never doing the heavy SQL.

This pre-aggregation choice is the single biggest architectural decision in SCION and the one that makes the difference between "works on demo data" and "works on a real customer".

---

## 4. Technology Stack

### 4.1 Core Technologies

| Layer | Component | Version | Why this choice |
|---|---|---|---|
| **Backend language** | Python | 3.12 | Best ecosystem for ORM + LLM + scripting; we already use it for `db_init.py`, tests, etc. |
| **API framework** | FastAPI | 0.115.6 | Type-driven, async-ready, OpenAPI for free. Bumped from 0.115.0 in v1.21.4 to pull starlette ≥0.41 (CVE-2024-47874). |
| **ASGI server** | uvicorn | 0.30.6 | Standard for FastAPI; standalone, no external process supervisor needed inside the container. |
| **ORM** | SQLAlchemy | 2.0.35 | New-style API, type-annotated, dialect-portable (sets up the Postgres migration in v1.25 with minimal churn). |
| **Migrations** | Alembic | 1.13.3 | Canonical for SQLAlchemy; idempotent `db_init.py init` wraps it for one-command lifecycle. |
| **Database** | SQLite + WAL | 3.40+ | Zero-config, embedded, file-backed. WAL gives readers a consistent snapshot during the heavy writer in `dict_persister`. Postgres roadmap = v1.25. |
| **LLM client** | TAISA (custom client) | n/a | Wraps the LLM provider behind a stable interface so the underlying model can be swapped without touching `taisa_client.py` callers. |
| **LLM model** | `llama-4-scout-17b-16e-instruct` | 2026-q1 | 131k-token context, fast, cheap, good at structured Q&A over metadata. Configured in `backend/app/config/taisa_llm.yaml` (baked into the private backend image). |
| **Frontend framework** | Next.js | 16.2.3 | App Router, RSC-ready, native standalone output for tight Docker image. |
| **UI library** | React | 19.2.4 | Required by Next 16; concurrent rendering keeps the graph responsive during expansion. |
| **Styling** | Tailwind CSS | 4.x | Utility-first, no runtime cost, deterministic builds. |
| **Graph rendering** | `@xyflow/react` + `@dagrejs/dagre` | 12.10 / 3.0 | Best-in-class for interactive directed graphs; dagre's layered layout handles the lineage shape natively. |
| **Charts** | Recharts | 3.8 | Declarative, SVG-based, good defaults; pairs cleanly with React 19. |
| **Tables** | `@tanstack/react-table` | 8.21 | Headless, lets us style with Tailwind while keeping sorting/filtering primitives sane. |
| **Data fetching** | SWR + axios | 2.4 / 1.15 | SWR for cache + revalidation, axios for the underlying HTTP. |
| **Icons** | lucide-react | 1.8 | Tree-shakable, consistent with the SCION visual language. |

### 4.2 Deployment & Runtime

| Component | Choice | Rationale |
|---|---|---|
| **Container runtime** | Docker Engine ≥ 24 + Compose plugin | Universal, supported on every Linux distro + Windows Docker Desktop. |
| **Reverse proxy** | nginx 1.29-alpine | Actively rebuilt by upstream; bumped from 1.27 in v1.21.4 (79 CVEs eliminated). Single public port. |
| **Image registry** | GHCR (private) | Owned by `GuilleAlbella`; PAT-gated for pull. Internal Teradata images never world-readable. |
| **Image publish** | GitHub Actions on `v*` tags | Build + push on every release; matrix builds backend + frontend in parallel with shared cache. |
| **Security scanning** | Docker Scout (monthly cron + on-demand) | New `.github/workflows/security-scan.yml` from v1.21.4; surfaces HIGH/CRITICAL CVEs without rebuilding. |
| **Auto-update** | **Removed in v1.21.4** | Watchtower removed; users run `update.sh` / `update.ps1`. The Sidebar version pill (v1.22) will surface "update available". |

### 4.3 Development Tools

| Tool | Purpose |
|---|---|
| `pytest` | Backend unit + integration tests. Schema parity test guards against ORM/Alembic drift. |
| `mypy` (planned) | Static type checking for the backend. Not enforced as of v1.21.4 — opportunistic. |
| ESLint + `eslint-config-next` | Frontend lint via `npm run lint`. |
| TypeScript strict mode | Frontend type safety; non-negotiable. |
| `tools/validate_only.py` | Standalone pre-flight validator for ingest files (added by Helton in v1.21.5). Reuses the same readers the backend uses, no persistence. |
| `tools/db_init.py` | Canonical DB lifecycle (`init` / `reset` / `seed`). Replaces every previous bootstrap script. |
| GitHub Actions | CI on every PR (`Backend (pytest)` + `Frontend (TypeScript strict)`). |

### 4.4 Runtime Dependencies (excerpt)

**Backend** — full list in `backend/requirements/base.txt`:

```text
fastapi==0.115.6        # CVE-2024-47874 fix
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
alembic==1.13.3
psycopg[binary]==3.2.13 # ready for v1.25 Postgres migration
httpx==0.27.2
pydantic==2.9.2
pydantic-settings==2.5.2
```

**Frontend** — `frontend/package.json`:

```json
{
  "next": "16.2.3",
  "react": "19.2.4",
  "@xyflow/react": "^12.10.2",
  "@dagrejs/dagre": "^3.0.0",
  "@tanstack/react-table": "^8.21.3",
  "recharts": "^3.8.1",
  "swr": "^2.4.1",
  "axios": "^1.15.0",
  "overrides": {
    "picomatch": "^4.0.4",
    "brace-expansion": "^2.0.3",
    "ip-address": "^10.1.1",
    "postcss": "^8.5.10"
  }
}
```

The `overrides` block forces transitive deps to patched versions; npm audit reports 0 vulnerabilities as of v1.21.4.

### 4.5 Prohibited Technologies

| Technology | Why we won't use it |
|---|---|
| Direct database drivers (JDBC, ODBC, `teradatasql`) | NG2 — SCION never connects to a live Teradata. All data arrives via extract files. |
| Kafka / Pub-Sub / streaming | NG3 — batch on demand only. Real-time observability is a separate product. |
| Heavy orchestrators (Kubernetes, Helm, ECS) in v1.x | Single-VM deploys are the contract. Customers who need orchestration can adapt, but SCION's compose stays the source of truth. |
| Public LLM keys baked into public artefacts | NG9 + general security. TAISA config is baked, but only in **private** GHCR images. |
| `docker.sock` mount in any container | Was needed by Watchtower → removed in v1.21.4. No container needs to control Docker any more. |
| Long-lived JWTs or session cookies for auth | NG10 — single shared `X-API-Key` is the only auth surface until SSO lands. Simpler = fewer ways to misconfigure. |
| Cloud-vendor lock-in primitives (S3-only, Azure-only) | Customer deploys span CloudBolt, Azure AKS, AWS, on-prem. Volume mounts are filesystem-shaped to stay portable. |

---

## Document Control

- **Created:** 2026-05-28
- **Last Modified:** 2026-05-28
- **Phase:** 1 of 3 — sections 1-4 (this PR)
- **Next phase:** Sections 5-8 (Functional Requirements, Non-Functional Requirements, Data Models, Interface Contracts)
- **Review status:** Awaiting maintainer review
