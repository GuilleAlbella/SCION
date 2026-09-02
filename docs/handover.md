# SCION — Maintainer Onboarding

**Author:** Guillermo Albella · guillermo.albella@teradata.com
**Audience:** Anyone taking over as primary maintainer, contributing for
the first time, or picking up after a context switch.
**Purpose:** Everything you'd want to ask in person. Pair with
`docs/internal_roadmap.md` (the *what's next*) and `docs/SPEC.md`
(the *what and why*). This doc is the *how to actually do it day one*.

**Current version:** v2.09.12 (2026-09-02)

---

## 1. The docs you must read first (in order)

| Order | File | Why |
|---|---|---|
| 1 | `README.md` | Architecture, engines, Quick Start, API surface. |
| 2 | `docs/SPEC.md` §1–§4 | What SCION is, what it deliberately isn't, tech stack. ~30 min. |
| 3 | `docs/internal_roadmap.md` | Phases, decision log, owner cheat-sheet. |
| 4 | `docs/use_cases.md` | What SCION does in 8 bullet points — how to explain it. |
| 5 | `docs/ingestion_pipelines.md` | The 4-pipeline architecture (committee decision). |
| 6 | `docs/release_policy.md` | Versioning + release discipline. |

`docs/demo_en.txt` (English) and `docs/demo.txt` (Spanish) are the
demo walkthrough scripts — useful for end-to-end validation after a change.

---

## 2. First-day checklist

Clone **outside OneDrive** (see §6 — this is critical on Windows):

```powershell
# 1. Set up the venv + node_modules
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements\dev.txt
cd frontend && npm install && cd ..

# 2. Create the SQLite DB + demo seed
#    db_init.py is the single canonical entry point for all DB lifecycle ops.
#    `reset --with-seed` drops everything and rebuilds with demo data.
#    `init` is idempotent — safe to run on an existing DB.
.venv\Scripts\python.exe backend\tools\db_init.py reset --with-seed

# 3. Run both services
.\dev.ps1
```

UI → http://localhost:3000 · API → http://localhost:8000 · OpenAPI → /docs

If `dev.ps1` exits silently after starting, see the WatchFiles note in §6.

---

## 3. Current state of the codebase (as of v2.09.12)

### What's live and stable

| Area | Status | Notes |
|---|---|---|
| **Pipeline 1** — Code Parser JSON ingest | ✅ Stable | `/parser-import`. Parser output → graph edges + attribute_lineage. |
| **Pipeline 2** — Data Dictionary ingest | ✅ Stable | `/dict-import`. 6-file .dat batch; idempotent on `extract_run_id`. |
| **Pipeline 3** — PDCR usage ingest | ✅ Stable | Bundled with dict-import. Real criticality scoring (60% usage + 40% graph). |
| **Share import** | ✅ Stable | Auto-scan, one-click Import All, manual picker, already-imported detection. |
| **Column-level lineage** | ✅ Stable | `/lineage/columns` + Column view toggle + BFS navigate (breadcrumb, ←/→ buttons). Edge labels via `EdgeLabelRenderer`. |
| **Graph / impact / diff / TAISA** | ✅ Stable | All engines pre-aggregating at ingest time. SQL GROUP BY replaces RAM-heavy Python aggregation. |
| **Containerised deploy** | ✅ Stable | GHCR private images, one-liner installer, `update.sh`. PostgreSQL 16 in production. |
| **Staging Layer** | ✅ Stable | Validation pipeline, import_status tracking, cross-source duplicate detection (v2.03). |
| **Integration Model** | ✅ Backend stable | `object_entity` table + resolver hook + `/entity/` API. Frontend trend charts pending. |
| **Reference Data** | ✅ Stable | `/reference` page — org hierarchy + app metadata. `/reference-import/users` + `/applications`. |
| **Landscape page** | ✅ Stable | Business-friendly entry point; KPI cards, risk distribution, top critical objects (v2.03). |
| **PII Classification** | ✅ Stable | TAISA-powered batch classify; badges + filter in column-level lineage panel (v2.06). |
| **Incremental snapshots** | ✅ Stable | Baseline tracking, gap detection, cumulative object count (v2.08). |
| **Manifest timestamps** | ✅ Stable | `extract_timestamp` from `extract_run_id` prefix shown in Snapshots page (v2.09). |

### Known open items / follow-ups

- **§2.15.d Progressive Disclosure UI** — Landscape + key pages in business language (dept/app, not snapshot/schema). Piloting on Landscape. Validated direction by Kindy/Chris in Reunión 29.
- **§2.10 pending UI** — usage/intelligence filters by team/dept; TAISA user/app context. Blocked on PDCR extractor providing per-user rows.
- **Entity trend charts** — frontend criticality + usage trend charts using `/entity/{id}/history`. Backend ready.
- **DataDNA QueryID correlation** — `dbql_query` stores DBQL text; wiring to Code Parser requires QueryID join key from parser team.
- **Security architecture doc** — still missing (tracked in `docs/SPEC.md` §13.4).
- **Operations / on-call runbook** — still missing (tracked in §13.4).
- **Per-object usage idempotency** — re-uploading the same `pdcr_object_usage_*.dat` inserts duplicates.

### Running tests

```powershell
# All backend tests (29 test files, ~12 types)
.venv\Scripts\pytest backend/tests/ -v

# TypeScript strict check
cd frontend && npm run lint && npx tsc --noEmit
```

---

## 4. Where things live (mental map)

```
backend/
├─ app/
│  ├─ api/v1/                 # FastAPI routes — one file per resource
│  │  ├─ dict_import.py         ← Pipeline 2: 6-file dict + PDCR ingest
│  │  ├─ parser_import.py       ← Pipeline 1: Code Parser JSON ingest
│  │  ├─ share_import.py        ← Server-side share scan + import
│  │  ├─ lineage.py             ← Column-level lineage (/lineage/columns)
│  │  ├─ graph.py               ← Full graph + BFS focus subgraph
│  │  ├─ impact.py              ← Blast radius + batch impact
│  │  ├─ import_progress.py     ← SSE/polling progress channel
│  │  └─ ...                    ← snapshots, diff, reasoning, usage, …
│  ├─ db/
│  │  ├─ engine.py              # global SQLAlchemy engine (SQLite)
│  │  └─ models/                # 20 ORM models (1 file per entity)
│  │     ├─ attribute_lineage.py   ← Tier 1/2 column→column edges
│  │     ├─ graph_node/edge.py     ← dependency graph
│  │     └─ ...
│  ├─ metadata/                 # readers + validators + persisters
│  │  ├─ dict_flat_file_reader.py  ← §-delimited / ENDREC parser
│  │  ├─ format_detector.py        ← content-based file type dispatch
│  │  ├─ dict_batch_validator.py   ← same source+run_id + temporal check
│  │  ├─ dict_persister.py         ← snapshot keyed by extract_run_id
│  │  └─ pdcr_persister.py         ← PDCR usage → UsageEvent rows
│  ├─ graph/                    # graph builder, impact engine, blast radius
│  ├─ diff/                     # diff engine + change classification
│  ├─ taisa/                    # TAISA LLM client + context builder
│  ├─ usage/                    # usage_event + criticality + dbql_query
│  ├─ parser_ingest/            # Code Parser JSON → internal payload
│  └─ snapshot/                 # snapshot engine + structural hash
├─ tests/                       # pytest — unit + integration
└─ tools/
   ├─ db_init.py                  ← canonical DB lifecycle (init/reset/seed)
   └─ validate_only.py            ← pre-flight validator (no DB required)

frontend/
└─ src/
   ├─ app/                      # Next.js App Router — one folder per page
   │  ├─ lineage/page.tsx          ← Lineage graph + Column-Level Lineage panel
   │  ├─ snapshots/page.tsx        ← Import from Share + Live Capture
   │  ├─ impact/, changes/, graph/, …
   ├─ components/
   │  ├─ shared/                  ← GuidedSection, ObjectPicker, etc.
   │  └─ layout/                  ← PageShell, Sidebar
   └─ lib/
      ├─ api/                     # typed Axios clients (1 file per resource)
      ├─ constants.ts              ← APP_VERSION (single source of truth)
      └─ terminology.ts            ← changeTypeLabel(), OBJECT_TYPE_STYLES

docs/                           # all project documentation
alembic/versions/               # migrations — new ones go here
Parser/                         # Code Parser contracts + sample data
```

---

## 5. Conventions we follow

- **Branches:** `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `design/<slug>`. Never push to `main` directly.
- **Commits:** conventional commits — `feat:`, `fix:`, `chore:`, `design:`, `docs:`. Short imperative subject, optional body. CI gates on this.
- **Versioning:** `vMAJOR.MINOR.PATCH` (currently v2.x). Single source of truth → `frontend/src/lib/constants.ts::APP_VERSION`. Bump `README.md` + `CHANGELOG.md` in the same commit. Tag = CI publishes GHCR images.
- **Release flow:** `git tag vX.Y.Z && git push origin main --tags` → GitHub Actions builds and pushes GHCR images → manual deploy via `update.sh` on production VM (ps-ubuntu-0043).
- **Comments:** explain *why*, not *what*. Match the inline-narrative style. One-line max — no multi-paragraph docstrings.
- **Narrative UX:** any new page goes through `GuidedSection` for numbered intro-boxed sections. Keep the pattern consistent.
- **Tests:** new backend code ships with a test in `backend/tests/`. `test_schema_parity.py` must always be green — it guards ORM/Alembic drift and is the single most important safety net.
- **Session patterns:** use `with Session(engine) as db:` (NOT `Session(bind=engine)` — removed in v2.09.05 — and NOT `Depends(get_db)`). See `backend/app/api/v1/lineage.py` for the canonical pattern.

---

## 6. Windows gotchas (real ones)

### OneDrive corrupts `.git/index`
**The single most painful issue on this project.** OneDrive sync
mangles `.git/index` over weeks. Symptoms: random `fatal: index file
corrupt`, weird ghost commits, `bad index file sha signature`.

**Fix:** clone outside OneDrive. `C:\dev\SCION` is fine. Already in
`CONTRIBUTING.md` but worth saying twice. If you inherit a broken copy,
do a fresh clone from GitHub — never try to fix the index.

### PowerShell 5.1 vs 7
`dev.ps1` is ASCII-only deliberately because PS 5.1 reads files with
the system codepage and chokes on Unicode. If you edit it in VSCode,
**save as ASCII**, not UTF-8 with BOM. PS 7 doesn't care, but we stay
5.1-compatible.

### `--reload-dir app` on uvicorn
WatchFiles on Windows propagates a signal that PowerShell interprets as
Ctrl+C on the parent script when a backend reload triggers. We fixed it
by limiting reload to `backend/app/` only. Don't widen that scope.

### `taskkill /T /F` in dev.ps1
npm and uvicorn spawn grandchildren. `dev.ps1` uses `taskkill /T /F`
on the PIDs because PS's native kill leaves orphans holding ports 3000
and 8000.

### SSH key for production deploy
Production VM (ps-ubuntu-0043, 10.27.122.64) requires the SSH key at
`C:/Users/<you>/.ssh/scion_key`. Keep it in KeePass — never commit it.
Deploy command:
```powershell
ssh -i C:/Users/<you>/.ssh/scion_key scionadmin@10.27.122.64 "curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/scion-deploy/main/update.sh | bash"
```

---

## 7. Decisions you should know about (so you don't re-litigate)

Full table in `internal_roadmap.md` decision log. Highlights:

| Decision | Rationale | Since |
|---|---|---|
| SCION never connects to a customer DB | Committee decision re-confirmed by Luis in Meeting #7 | Always |
| All inputs from offline extractor files | Security teams object to live read access | Always |
| `extract_run_id` is the snapshot dedup key | Prevents mixed-batch corruption; stamped by the Metadata Extractor on every record | v1.13 |
| `/dict-import` and `/parser-import` stay separate endpoints | Different content types, different validation pipelines | v1.04 |
| Column changes redirect to parent table for /lineage | Columns aren't graph nodes — only databases/tables/views/procs are | v1.10 |
| FK direction: referenced → fk_holder | accounts(customer_id) → customers means accounts *depends on* customers | v1.10 |
| Dedup column lineage at API layer, not in DB | Parser intentionally stores one row per SQL step for audit trail; dedup at presentation preserves traceability | v1.21.24 |
| Watchtower removed | 31 inherited CVEs + `docker.sock` = root-equivalent. Users run `update.sh` manually | v1.21.4 |
| PostgreSQL 16 in production (since v2.00) | Migration done in lab 2026-07-20; SQLite still used for local dev/demo | v2.00 |
| "No DDL emitted to the warehouse" (NG4) | SCION is observation, not control. Generate DDL produces a *text artefact* only — it never executes | Always |
| Code Parser has no persistent storage | It processes inputs and emits outputs; any QueryID correlation requires external orchestration | Clarified 2026-06-18 |

---

## 8. Backlog items (none of these block anything today)

1. **Per-object usage idempotency** — `pdcr_object_usage_*.dat` re-upload inserts duplicates (no natural key on `usage_event`).
2. **Security architecture doc** — auth, secrets, GHCR, threat model. Pre-GA blocker per SPEC §13.4.
3. **Operations / on-call runbook** — what to do when something fails in prod. Pre-GA blocker per SPEC §13.4.
4. **Customer onboarding guide** — what a customer-side deployer needs to know. Pre-GA blocker per SPEC §13.4.
5. **`tools/benchmark_ingest.py`** — end-to-end timing script for future scaling decisions.
6. **Entity trend charts** — frontend components for criticality/usage trends using the `/entity/{id}/history` endpoint (backend already ready).

---

## 9. Who to ping when

| Topic | Person | Channel |
|---|---|---|
| What is SCION supposed to do? | Pilar (PM) | Teams |
| Code Parser / Metadata Extractor / dict format | Rahul Kulkarni | Teams |
| Infra / VM provisioning | Rahul Shiyekar | Teams (via Pilar) |
| Scope / release sign-off | Chris | through Pilar |
| Sales-readiness / customer feedback | Kindy Flyvholm | through Pilar |
| Time-tracking / project codes | Pilar / Luis | Teams |
| Codebase questions | Guillermo Albella | guillermo.albella@teradata.com |

Save Pilar's contact. She's the central node and unblocks 80% of
non-technical questions in one ping.

---

## 10. If you're stuck on something

1. **First** — search `Transcripciones/`. Every meeting since project start is
   transcribed. Most "why is X this way?" answers live there.
2. **Second** — `CHANGELOG.md`. Each version has a "why" for every change.
3. **Third** — decision log in `internal_roadmap.md`.
4. **Fourth** — recent PR descriptions on GitHub.
5. **Fifth** — `docs/SPEC.md` §2.2 (non-goals) if you're wondering whether
   something is in scope.
6. **Last resort** — ping Guillermo.
