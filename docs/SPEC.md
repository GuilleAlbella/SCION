# SCION — Technical Specification

> **Version:** 1.21.5-spec-phase-2
> **Last Updated:** 2026-05-28
> **Status:** Phases 1-2 of 3 — Sections 1-8 (Executive, Goals, Architecture, Stack, FRs, NFRs, Data Models, Interfaces)
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
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Data Models](#7-data-models)
8. [Interface Contracts](#8-interface-contracts)
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

## 5. Functional Requirements

> **How to read this section.** Each `FR-X.Y` block uses RFC-2119 vocabulary (MUST / SHOULD / MAY). The intent is to be precise enough that a reviewer can read the corresponding code and tell whether it conforms, but not so prescriptive that it freezes implementation details. Where SCION already implements an FR, the description is in present tense; where it's planned, the FR is marked **(planned vX.Y)**.

### FR-1 — Data Ingestion

#### FR-1.1 Dictionary extract import (`POST /api/v1/dict-import`)

```
MUST accept a multipart upload of the 6-file dictionary extract emitted by
the customer-side exporter:
  databasesv_*.dat, tablesv_*.dat, columnsv_*.dat,
  indicesv_*.dat, partitioningconstraintsv_*.dat, tabletextv_*.dat

MUST detect format and content-type per file via app/metadata/format_detector.py
  - Filename prefix is a tiebreaker, never the primary signal
  - Arity-based detection handles renames or missing filenames

MUST validate the 6-file set before persisting anything (batch validator):
  - All files share the same `source_system_name` and `extract_run_id`
  - All files use the same field delimiter (§) and record terminator
    (newline for most; ENDREC for tabletextv and partitioningconstraintsv)
  - Per-file arity is consistent across all rows in the file

MUST persist atomically as a new Snapshot (see FR-2) and only mark the
snapshot as finalised after the post-ingest pipeline (FR-1.4) completes.

MUST stream rather than buffer files into memory — 9.8M-column Transcend
extracts must ingest on a 32 GB VM without OOM.
```

> **Scope guard:** This endpoint never accepts SQL, scripts, or BTEQ files.
> Those go to **DataDNA** (NG1). Trying to upload one returns 415.

#### FR-1.2 Parser lineage import (`POST /api/v1/parser-import`)

```
MUST accept the JSON contract DataDNA emits (Tier-1/2/3 lineage edges).
MUST persist edges into graph_edge with source=`parser_feed`.
MUST be idempotent on (source_id, target_id, edge_type, snapshot_id).
MUST chunk inserts at 900 rows to stay under the SQLite host-parameter
  limit (32 766 in 3.32+ but 999 in older builds we want to keep
  supporting).
```

#### FR-1.3 Usage import — planned

```
PLANNED (v1.22 if Rahul confirms JSON; later if PDCR .dat is the canonical
source — decision pending as of 2026-05-28). When implemented:
  - JSON path: extend ingest_usage_json() with a thin /usage-import endpoint
  - PDCR path: add readers for pdcr_log_* and pdcr_object_usage_*
    layouts (10/11 and 12 fields respectively) and route through the
    same dict-import pipeline with new ContentType.DBQL and
    ContentType.OBJECT_USAGE
```

#### FR-1.4 Post-ingest pipeline (`run_post_ingest_pipeline`)

```
MUST execute after every dict-import, in this order, all in one transaction
per stage:
  1. Snapshot finaliser:
     - compute Snapshot.structural_hash (streaming SHA-256 over
       schema/table/column rows)
     - compute Snapshot.object_count (cached aggregate)
  2. Diff engine: pair the new snapshot with its predecessor
     and emit ChangeEvent rows
  3. Graph builder: extract FK-heuristic edges into graph_edge
     (parser-feed edges land separately via FR-1.2)
  4. Blast radius: compute_batch_impact for every change, persist
     ChangeImpactSummary rows (single per-change pass, no N+1)
  5. Proactive alerts: persist_proactive_alerts (broken_lineage,
     orphan, hub_changed checks, all capped)
  6. Criticality: usage_event × graph_node centrality → ObjectCriticality

MUST log per-phase progress at INFO level so operators see where time is spent.
MAY use batch_validator pre-flight cache to skip already-validated batches.
SHOULD complete in <15 min on Transcend-class data on 8c/32GB.
```

### FR-2 — Snapshot Lifecycle

```
A Snapshot is the canonical immutable representation of the warehouse at time T.

MUST be created exclusively through the snapshot engine (no direct INSERT
into the snapshot table from API code).

MUST be finalised only when the post-ingest pipeline has completed; the
UI MUST filter out non-finalised snapshots from selection lists.

MUST be queryable through:
  GET /api/v1/snapshots                — list (paginated)
  GET /api/v1/snapshots/{id}           — detail
  GET /api/v1/snapshots/{id}/objects   — schema/table/column tree
  GET /api/v1/snapshots/{id}/ddl       — reconstructed DDL text snapshot

MUST be deletable in development (db_init.py reset) but NEVER from the
running app (no DELETE /snapshots endpoint).

MUST preserve `source_system`, `source_extract_run_id`, and `snapshot_time`
fields so two snapshots from the same extract are recognisable.
```

### FR-3 — Diff Engine

```
MUST accept any two snapshot ids and return a typed list of differences:
  POST /api/v1/diff           — quick summary (counts only)
  GET  /api/v1/diff/details   — paginated rows with filter + sort

MUST classify each diff entry as one of:
  ADDED, DROPPED, ALTERED, RENAMED

MUST classify severity (LOW / MEDIUM / HIGH) based on:
  - object_type (column changes on hub tables score higher)
  - change_type (DROP > ALTER > ADD in default policy)
  - downstream_dependency_count

MUST set is_breaking = true when the change can break a downstream
consumer (e.g. column dropped that appears in any view's text or in a
parser-feed lineage edge).

MUST return identical diffs for identical inputs (deterministic). The
schema_parity test guarantees that the persisted schema and Alembic head
match, so re-running diff on the same snapshot pair yields the same
result.

MUST paginate at 100 rows per page on /diff/details, with server-side
filters: severity, is_breaking, object_q (free-text on object_identifier).

MUST stream the summary aggregations (by_change_type, by_object_type,
by_schema) as GROUP BY queries against the full filtered set, not over
the current page slice.
```

### FR-4 — Impact / Blast Radius

```
MUST compute the downstream impact of any ChangeEvent as a traversal
of graph_edge starting from the changed object's GraphNode.

MUST honour edge_type (FEEDS, DEPENDS_ON, etc.) so a "blast radius" can
be filtered to lineage-only vs. all dependencies.

MUST be available pre-computed:
  - At ingest time, run_post_ingest_pipeline persists one row in
    change_impact_summary per change with counts grouped by depth,
    severity, object_type, schema
  - /api/v1/impact reads from the cache; the page paints in <2s on
    Transcend even when there are 250k changes

MUST also support on-demand computation for "what-if" scenarios
(FR-10) — the same engine, but the change is hypothetical and never
persisted to change_event.

MUST chunk any ID list in IN-clauses at 900 rows (SQLite host-parameter
limit). Applies to filter_uncomputed, persist_summaries_for_pair,
compute_batch_impact.
```

### FR-5 — Lineage & Graph Exploration

```
MUST provide two graph endpoints with different shapes:
  GET /api/v1/graph/{snapshot_id}    — full subgraph for one snapshot
                                       (soft-capped at max_nodes)
  GET /api/v1/graph/focus            — BFS from one anchor node with
                                       configurable hops + max_nodes

MUST declare /focus before /{snapshot_id} in FastAPI source order
(route-order trap: with the reverse order, FastAPI tries to parse
the string "focus" as an int and returns 422).

MUST run BFS server-side with hop and max_nodes caps so a
Transcend-scale focus query returns in <500 ms.

MUST return enriched node + edge payloads (database_name,
object_name, object_type for nodes; edge_type, edge_source for edges)
so the frontend doesn't need a second round-trip per node.

MUST keep the rendered subgraph state on the client between
expansions (Map<node_id, GN> + dedup on merge) so users can drill
without losing context. /graph and /lineage share this model.
```

### FR-6 — TAISA Reasoning

```
MUST expose a text-grounded Q&A endpoint:
  POST /api/v1/reasoning/answer

MUST build the LLM prompt context exclusively from SCION data already
in the database — never from external sources, never from the user's
free-text input (only the question itself is user-controlled).

MUST bound the context size by:
  - Per-section caps (e.g. top-30 schemas in inventory, top-50 changes,
    etc.) — see backend/app/taisa/taisa_client.py::_build_scion_context
  - A defensive total cap of 80 000 characters (~20-25k tokens) right
    before the LLM call

MUST never block the UI on TAISA failure. A timeout or upstream error
results in a graceful disabled state in the UI, not a 500.

MUST persist reasoning outputs in reasoning_event for replay and audit.

MUST keep conversation history to 10 turns max — enough for follow-up
references, not so much that history dominates the context.

MUST never include the API key or model name in any user-visible response.

SHOULD avoid the vendor name in all user-facing copy (the model
provider is an implementation detail).
```

### FR-7 — Metrics & Change Intelligence

```
MUST expose snapshot-level KPIs:
  GET /api/v1/metrics/snapshot/{id}   — object counts + structural_hash
  GET /api/v1/metrics/growth          — between two snapshots
  GET /api/v1/metrics/volatility      — global volatility index

MUST read the persisted Snapshot.structural_hash rather than recomputing
on every call. v1.21.1 fixed the symptom where /metrics hung the UI
because the hash was recomputed (9.8M rows) per snapshot per page load.

MUST expose change-intelligence metrics that surface cross-snapshot
patterns:
  GET /api/v1/intelligence/cochange       — pairs of objects that change
                                            together (windowed cap)
  GET /api/v1/intelligence/volatility-trend
                                          — per-schema volatility over
                                            the last N snapshots (capped)

SHOULD support windowed history sizes via query params (max_history_pairs,
max_history_snapshots) so the call is bounded even on a deep history.
```

### FR-8 — Proactive Alerts

```
MUST run the alert detectors at ingest time (FR-1.4 step 5), never on
demand. The /alerts endpoint reads the persisted table only.

MUST support at least these detectors out of the box:
  - broken_lineage:  a parser-feed edge points at an object that
                     no longer exists in the latest snapshot
  - orphan:          a table has zero incoming and zero outgoing edges
  - hub_changed:     a high-centrality node has an ALTERED or DROPPED
                     ChangeEvent in the last pair

MUST cap each detector at a sensible threshold (defaults: 500 alerts per
detector per snapshot) so an extreme case doesn't fill the page.

MUST expose alert acknowledgement so users can hide ones they've handled
without losing the audit trail.
```

### FR-9 — Audit & History

```
MUST persist every TAISA call in reasoning_event with question, response,
snapshot context, and timestamp.

MUST persist every UI action that triggers a backend mutation (today
only the dict-import + parser-import) in usage_event.

MUST expose a server-side paginated timeline:
  GET /api/v1/timeline                — change_event + import events
                                        combined, filterable, paginated

MUST never persist the LLM provider's API key, model name, or response
metadata that isn't user-relevant.
```

### FR-10 — What-If Simulation

```
MUST allow a user to express a hypothetical change without persisting it.
  - Today: pick a target object via ObjectAutocomplete + select change_type
  - Future (planned): bulk simulation from a paste-in DDL list

MUST run the same impact engine (FR-4) on the hypothetical change and
display blast radius in real time, never writing to change_event.

MUST clearly indicate to the user that nothing is being saved — the page
URL is `/simulation` and every action is read-only.
```

### FR-11 — Deploy & Install

```
MUST be deployable through a single command on Linux:
  curl -fsSL .../install.sh | bash

MUST be deployable through a single command on Windows with Docker Desktop:
  irm .../install.ps1 | iex

MUST install on RHEL/CentOS/Rocky/AlmaLinux/Ubuntu/Debian/Fedora when
Docker is missing.

MUST be idempotent: re-running the installer on an existing install
refreshes the compose + nginx config but never overwrites .env.

MUST gate the image pull with `docker login ghcr.io` against a private
GHCR namespace (NG9).

MUST resolve the GHCR PAT in this order:
  1. $SCION_GHCR_TOKEN environment variable
  2. Existing cached docker creds (silent no-op)
  3. Interactive secure prompt (input hidden)

MUST cache the cred via docker login on the host so subsequent installs
and updates run without re-prompting.

MUST support upgrades through an analogous one-liner:
  curl -fsSL .../update.sh | bash    # Linux
  irm .../update.ps1 | iex           # Windows

The update script MUST bail with a clear message if GHCR auth has
expired, never silently fail.
```

### FR-12 — Security & Auth

```
MUST gate every /api/v1/* route with an X-API-Key header check
(via require_api_key dependency), except:
  - /api/v1/health/*       — public for liveness/readiness probes
  - /api/v1/system/version — public so the sidebar pill works
                             before the user authenticates

MUST never include secrets in any artefact that crosses a trust
boundary:
  - GROQ / TAISA API key is baked into the private backend image
    via taisa_llm.yaml; GHCR is private, so the artefact never
    leaves Teradata-controlled hands
  - The user-side X-API-Key is auto-generated by the installer
    (openssl rand -hex 32) and stored only in /opt/scion/.env
    with mode 600

MUST ship .gitignore patterns that catch casual "Token.txt",
"secrets.md", "credentials.txt" files so a developer can't
accidentally commit a secret via `git add .`.

MUST run a monthly Docker Scout scan against the published images
(.github/workflows/security-scan.yml) and surface HIGH/CRITICAL
findings as GitHub issues.

MUST rebuild base images with `apt-get upgrade -y` and `pull: true`
on every tagged release so Debian/Alpine security patches roll in
without needing a separate "security release".
```

---

## 6. Non-Functional Requirements

### 6.1 Performance

> All targets were measured against the Transcend-DevTest extract
> (10 716 schemas / 240k tables / 9.8M columns) running on a single
> 8c/32GB VM with SQLite + WAL. They're contract numbers, not aspirational.

| Concern | Target | Measured (Transcend) |
|---|---|---|
| Dict-import full pipeline | <15 min end-to-end | ~10 min |
| `/snapshots` list | <500 ms p99 | ~120 ms |
| `/changes` first page | <2 s | ~700 ms |
| `/diff/details` first page (filtered) | <2 s | ~800 ms |
| `/impact` summary (cached) | <2 s | ~450 ms |
| `/graph/focus` (hops=1, max_nodes=100) | <500 ms | ~280 ms |
| `/metrics/snapshot/{id}` single call | <1 s | 0.76 s on snapshot 11 (Transcend), 0.16 s on demo |
| TAISA Q&A round-trip | <30 s wall time | typically 4-15 s including LLM latency |
| `install.sh` cold install (warm cache) | <2 min | ~90 s |
| `update.sh` upgrade roundtrip | <2 min | ~45 s |

### 6.2 Reliability

```
MUST never lose data on container restart. Named volumes are the only
persistence layer; bind-mounts are documented but unsupported in prod.

MUST recover automatically from a partial ingest. db_init.py init runs
on every backend start and detects:
  - fresh:    no tables → alembic upgrade head from base
  - managed:  alembic_version populated → upgrade to head (no-op when
              already at head)
  - legacy:   tables exist but alembic_version empty → compare to
              Base.metadata; stamp at head if identical, refuse and
              ask for `reset` if drifted

MUST be deterministic: identical inputs → identical outputs (snapshots,
diffs, structural hashes, blast radius). The schema_parity test enforces
this for the schema itself.

MUST degrade gracefully when TAISA is unreachable. The reasoning
endpoints return a clear disabled state; the rest of the app is
unaffected.

MUST degrade gracefully when GitHub Releases API is unreachable. The
/system/version endpoint returns `latest: null` and the banner stays
quiet.
```

### 6.3 Maintainability

```
MUST keep the schema_parity test green. That test compares
`Base.metadata.create_all()` against `alembic upgrade head` and fails
if they diverge. It is the single most important safety net in the
backend.

MUST ship every new ORM model with a corresponding Alembic migration.
Tools/db_init.py refuses to start a fresh DB if the parity test would
fail.

MUST keep the docker image size under control:
  - backend ≤ 400 MB
  - frontend ≤ 320 MB
  Multi-stage Dockerfiles + .dockerignore are the levers.

MUST surface per-phase timing in the post-ingest pipeline at INFO
level. Operators rely on those lines to spot regressions early.

SHOULD keep public-facing TypeScript strict-mode clean
(frontend CI gate).

SHOULD keep pytest under 90 s end-to-end for the metadata test suite
so PRs stay fast to review.
```

### 6.4 Security

```
MUST require an X-API-Key header on every /api/v1/* route except
/health and /system/version.

MUST distribute the GHCR PAT through internal Teradata channels only
(not in any committed file, not in any chat outside the SCION team).

MUST rotate the GHCR PAT immediately if leaked. Revocation is one
click in GitHub; deploys keep working until they next try to pull
(cached creds remain valid for already-running containers).

MUST keep the SCION application repo private. scion-deploy (compose
+ installer scripts) is public; SCION itself stays private.

MUST never log the LLM API key, the X-API-Key value, or any
customer schema name that could be confidential.

MUST scan the published images monthly and act on every
HIGH/CRITICAL finding within one patch release.
```

### 6.5 Compatibility

```
MUST run on:
  Backend:  Python 3.12 inside python:3.12-slim-bookworm Docker image
  Frontend: Node 22 inside node:22-alpine Docker image
  Host OS:  Linux (Ubuntu 22.04+, RHEL/Rocky/AlmaLinux 8+),
            Windows 10/11 with Docker Desktop, macOS 12+ for dev
  Docker:   Engine ≥ 24 with the Compose plugin

MUST accept dictionary extracts from Teradata 16.20 through 17.20
(the format hasn't changed enough to matter; new fields are
ignored, missing fields default to NULL).

MUST handle UTF-8 input universally and Latin-1 with replacement
fallback (errors='replace') for legacy DBQL exports.

MUST work behind a corporate proxy when configured via the standard
HTTP_PROXY / HTTPS_PROXY / NO_PROXY env vars (passed through to
the backend container via compose).
```

---

## 7. Data Models

### 7.1 ORM Table Inventory

There are **19 ORM tables** + the standard `alembic_version` metadata table.
Group by purpose:

#### Snapshot core (8 tables)

| Table | Module | Purpose |
|---|---|---|
| `snapshot` | `app/db/models/snapshot.py` | One row per ingested extract. Owns `structural_hash`, `object_count`, `snapshot_time`, `source_system_name`, `source_extract_run_id`. |
| `schema_snapshot` | `app/db/models/schema_snapshot.py` | One row per (snapshot, database). |
| `table_snapshot` | `app/db/models/table_snapshot.py` | One row per (snapshot, database, table). Carries `object_type` (TABLE/VIEW/JOIN_INDEX/...), `creator`, `last_alter_timestamp`. |
| `column_snapshot` | `app/db/models/column_snapshot.py` | One row per (snapshot, table, column). Carries type, nullability, default, decimal precision. |
| `index_snapshot` | `app/db/models/index_snapshot.py` | One row per (snapshot, table, index). |
| `partitioning_snapshot` | `app/db/models/partitioning_snapshot.py` | One row per partitioning constraint. 9-col + ENDREC layout since v1.21.5. |
| `ddl_text_snapshot` | `app/db/models/ddl_text_snapshot.py` | RequestText for views/macros, ENDREC-terminated. |
| `attribute_lineage` | `app/db/models/attribute_lineage.py` | Column-level lineage edges from the parser feed. |

#### Process flow (2 tables)

| Table | Module | Purpose |
|---|---|---|
| `process` | `app/db/models/process.py` | Logical process inferred from script / parser feed. |
| `step` | `app/db/models/step.py` | Step inside a process. |

#### Diff + impact (5 tables)

| Table | Module | Purpose |
|---|---|---|
| `change_event` | `app/diff/diff_models.py` | One row per detected change between two snapshots. Carries severity, is_breaking, change_type, object_identifier. |
| `graph_node` | `app/graph/graph_models.py` | One row per snapshot object as a graph vertex. |
| `graph_edge` | `app/graph/graph_models.py` | Lineage / dependency edge between two graph_nodes. Sources tracked: `fk_heuristic`, `parser_feed`, `manual` (planned). |
| `impact_event` | `app/graph/impact_models.py` | One row per (change, impacted_node) pair from blast radius. |
| `change_impact_summary` | `app/graph/impact_models.py` | Pre-aggregated impact summary per change_event. Read by `/impact` for sub-second response. |

#### Alerts + reasoning (2 tables)

| Table | Module | Purpose |
|---|---|---|
| `proactive_alert` | `app/graph/impact_models.py` | One row per detector × snapshot finding (broken_lineage, orphan, hub_changed). |
| `reasoning_event` | `app/taisa/taisa_models.py` | TAISA call audit — question, response, classification, risk_level, change_id (when scoped). |

#### Usage + criticality (2 tables)

| Table | Module | Purpose |
|---|---|---|
| `usage_event` | `app/usage/usage_models.py` | Query count + user count per (snapshot, object). |
| `object_criticality` | `app/usage/usage_models.py` | Combined criticality score derived from usage_event × graph centrality. |

### 7.2 Key Pydantic Response Shapes

Every paginated list endpoint returns a uniform envelope:

```python
class PaginatedResponse(BaseModel):
    items: list[T]
    total: int
    has_more: bool
    summary: dict[str, Any] | None = None   # GROUP-BY aggregates over the
                                            # full filtered set, not over
                                            # the current page slice
```

Examples by router:

| Router | List response | Summary keys |
|---|---|---|
| `changes.py` | `ChangesResponse` | by_change_type, by_severity, by_object_type |
| `diff.py` | `DiffDetailResponse` | by_change_type, by_object_type, by_schema, total_breaking |
| `impact.py` | `ImpactResponse` (single) / `BatchBlastRadius` (batch) | by_severity, by_change_type, by_schema, by_breaking, affected_databases |
| `alerts.py` | `AlertsResponse` | by_severity, by_detector |
| `timeline.py` | (timeline event envelope) | by_event_type |

The shape is deliberate: it lets the UI render KPI tiles from `summary`
without a second round-trip, and the values stay stable across page
flips because they're computed on the filtered set, not the slice.

### 7.3 Storage Layout

```
SQLite + WAL is the v1.x storage backend.

  - DATABASE_URL defaults to sqlite:///{PROJECT_ROOT}/kalido_lite.db
    in dev, sqlite:////data/scion.db inside the Docker container.
  - WAL mode (PRAGMA journal_mode=WAL) is enabled on every connection
    via SQLAlchemy event. The decision is documented inline in
    backend/app/db/engine.py and was driven by the dict_persister
    contention pattern (one big writer + many short readers).
  - Indexes are added via Alembic migrations only. Composite indexes
    on (snapshot_id, ...) cover the hot read paths (per-snapshot
    listings, change_event filters by snapshot pair).
  - The SQLite host-parameter limit (999 in older builds, 32 766 in
    3.32+) is the reason every IN-clause that fans out from a list
    is chunked at 900. See _chunked() in app/graph/impact_summary.py.

Postgres is roadmapped for v1.25 when the first multi-tenant
deployment lands. The portability hygiene step in v1.22 (replace
INSERT OR IGNORE / strftime / julianday with ANSI equivalents) is
what makes the move tractable. SQLAlchemy + Alembic do the bulk of
the work; the application code shouldn't need to change.
```

---

## 8. Interface Contracts

### 8.1 REST API Surface

Twenty-four routers under the `/api/v1` prefix. The full surface is
discoverable via the auto-generated OpenAPI schema
(`GET /openapi.json` when the backend is running), but the table
below summarises the contract.

| Router | Mount | Purpose | Auth |
|---|---|---|---|
| `health.py` | `/api/v1/health` | Liveness, readiness | **public** |
| `system.py` | `/api/v1/system` | Version + update banner | **public** |
| `snapshots.py` | `/api/v1/snapshots` | List + detail + object tree | gated |
| `changes.py` | `/api/v1/changes` | Paginated change feed (server-side filter + sort) | gated |
| `diff.py` | `/api/v1/diff` | Quick diff + `/diff/details` (paginated) | gated |
| `graph.py` | `/api/v1/graph` | `/graph/{snapshot_id}` (full) + `/graph/focus` (BFS) | gated |
| `impact.py` | `/api/v1/impact` | Single-change impact + batch impact + summaries | gated |
| `reasoning.py` | `/api/v1/reasoning` | TAISA Q&A + reasoning history | gated |
| `metrics.py` | `/api/v1/metrics` | snapshot KPIs, growth, volatility | gated |
| `usage.py` | `/api/v1/usage` | Top-N usage + counts | gated |
| `intelligence.py` | `/api/v1/intelligence` | cochange, volatility trend (windowed) | gated |
| `control.py` | `/api/v1/control` | Engine state + manual triggers (dev only) | gated |
| `ddl.py` | `/api/v1/ddl` | Reconstructed DDL text per object | gated |
| `alerts.py` | `/api/v1/alerts` | Proactive alerts list + ack | gated |
| `export.py` | `/api/v1/export` | CSV / JSON downloads of selected data | gated |
| `report.py` | `/api/v1/report` | HTML report rendering | gated |
| `schema_tree.py` | `/api/v1/schema-tree` | Hierarchical schema view (lazy children) | gated |
| `search.py` | `/api/v1/search` | Global text search across objects | gated |
| `simulation.py` | `/api/v1/simulation` | What-if change preview | gated |
| `dict_import.py` | `/api/v1/dict-import` | 6-file dictionary upload + post-ingest pipeline | gated |
| `parser_import.py` | `/api/v1/parser-import` | DataDNA lineage JSON ingest | gated |
| `import_progress.py` | `/api/v1/import-progress` | Polling endpoint for dict-import status | gated |
| `timeline.py` | `/api/v1/timeline` | Paginated cross-event timeline | gated |
| `objects.py` | `/api/v1/objects` | Server-side autocomplete (filters by source + types) | gated |

#### Auth boundary

```
Gated routes:    every request must carry X-API-Key matching API_KEY
                 in /opt/scion/.env. A missing header returns 401;
                 a wrong value returns 403.

Public routes:   /health (probe-friendly, no auth)
                 /system/version (banner-friendly, no auth)

There is no third tier. There is no admin role. There is no per-user
permissioning. v1.x is single-key, single-tenant by design (NG10).
```

### 8.2 Internal Engine Interfaces

The backend exposes four engine interfaces internally. All four are
initialised eagerly at startup (`engine_registry.initialise_engines`)
so the readiness endpoint reflects real state, not a future state.

| Engine | Module | Public surface |
|---|---|---|
| **Snapshot engine** | `app/snapshot/` | `create_snapshot(metadata)`, `finalise_snapshot(snapshot_id)`, `compute_snapshot_metrics()`, `compute_structural_hash()` |
| **Diff engine** | `app/diff/` | `diff_pair(from_id, to_id)`, `paginate_changes(filters, page)`, `summarise_changes(filters)` |
| **Graph / impact engine** | `app/graph/` | `build_graph_for_snapshot()`, `compute_batch_impact(limit, offset)`, `compute_focus_subgraph(node_id, hops, max_nodes)`, `persist_summaries_for_pair()`, `persist_proactive_alerts()` |
| **TAISA client** | `app/taisa/taisa_client.py` | `analyse_change(change_id)`, `answer_question(question, history)`, `_build_scion_context(question)` (bounded) |

Each engine MUST:

```
- Be importable without side effects (no DB calls at import time).
- Accept an explicit Session or engine when called from tests so
  tests can isolate fixtures.
- Never raise unhandled exceptions to the API layer; wrap in
  domain-specific errors (DictFlatFileError, SnapshotFinaliseError,
  TAISAError, ...).
- Document the chunking strategy when handling IDs that may exceed
  SQLite's host-parameter limit.
```

### 8.3 External Contracts

The backend talks to two external systems. Both are optional in the
sense that SCION continues to function when either is unreachable
(see FR-6 and FR-12).

| System | Used for | Failure mode |
|---|---|---|
| **LLM provider (via TAISA)** | natural-language reasoning over metadata | Reasoning endpoints return disabled state; rest of app unaffected. |
| **GitHub Releases API** | version banner ("update available") | `/system/version` returns `latest: null`; banner stays quiet. |

Neither external call is on the critical path of any of the core
flows (ingest, snapshot, diff, impact, graph, simulation).

---

## Document Control

- **Created:** 2026-05-28
- **Last Modified:** 2026-05-28
- **Phase:** 2 of 3 — sections 1-8 (current scope of this PR)
- **Next phase:** Sections 9-14 + appendices (Golden Examples, Test Scenarios, Reference Benchmarking, Acceptance Criteria, Deliverables, Risk Assessment, Glossary, References)
- **Review status:** Awaiting maintainer review
