# SCION — Maintainer Onboarding

**Author:** Guillermo Albella · guillermo.albella@teradata.com
**Audience:** Anyone taking over as primary maintainer, contributing for
the first time, or picking up after a context switch.
**Purpose:** Everything you'd want to ask in person. Pair with
`docs/internal_roadmap.md` (the *what's next*) and `docs/SPEC.md`
(the *what and why*). This doc is the *how to actually do it day one*.

**Current version:** v2.09.15 (2026-09-02)

---

## 1. The docs you must read first (in order)

> These files are all inside the repository. Read them **after** you have
> completed §2 (cloned and running). You don't need them to set up the app —
> they give you the *why* behind the design decisions.

| Order | File (open after cloning) | Why |
|---|---|---|
| 1 | `README.md` | Architecture, engines, API surface. |
| 2 | `docs/SPEC.md` §1–§4 | What SCION is, what it deliberately isn't, tech stack. ~30 min. |
| 3 | `docs/internal_roadmap.md` | Phases, decision log, owner cheat-sheet. |
| 4 | `docs/use_cases.md` | What SCION does in 8 bullet points — how to explain it. |
| 5 | `docs/ingestion_pipelines.md` | The 4-pipeline architecture (committee decision). |
| 6 | `docs/release_policy.md` | Versioning + release discipline. |

`docs/demo_en.txt` (English) and `docs/demo.txt` (Spanish) are the
demo walkthrough scripts — useful for end-to-end validation after a change.

---

## 2. Local dev setup — step by step

This section is self-contained. You can follow it before you have anything
installed. Estimated time: 30–45 minutes on a clean machine.

---

### Step 1 — Install prerequisites

You need three tools. Install them in this order.

**Git**
```powershell
winget install --id Git.Git -e --source winget
```
Or download from https://git-scm.com/download/win and run the installer with
all defaults.

**Python 3.11**
```powershell
winget install --id Python.Python.3.11 -e --source winget
```
Or download from https://www.python.org/downloads/release/python-3119/ —
pick "Windows installer (64-bit)". During install, **check "Add Python to PATH"**.

Verify:
```powershell
python --version   # should print Python 3.11.x
```

**Node.js 18 LTS**
```powershell
winget install --id OpenJS.NodeJS.LTS -e --source winget
```
Or download from https://nodejs.org/en/download (choose the LTS installer).

Verify:
```powershell
node --version   # should print v18.x.x or higher
npm --version    # should print 9.x.x or higher
```

---

### Step 2 — Get repository access

Ask Guillermo (guillermo.albella@teradata.com) or Rahul Kulkarni to invite
your **personal GitHub account** (the one linked to your Teradata email) as
a collaborator on:

- `https://github.com/GuilleAlbella/SCION` — application code
- `https://github.com/GuilleAlbella/scion-deploy` — production deploy config

You will receive an invitation email from GitHub. Accept it before continuing.

---

### Step 3 — Clone the repository

> ⚠️ **Critical on Windows:** do NOT clone inside your OneDrive folder.
> OneDrive silently corrupts `.git/index` over time. Clone to a plain local
> path such as `C:\dev\`.

```powershell
# Create a clean dev directory (skip if it already exists)
New-Item -ItemType Directory -Force C:\dev

# Clone
cd C:\dev
git clone https://github.com/GuilleAlbella/SCION.git
cd SCION
```

---

### Step 4 — Python virtual environment

Always use a venv — never install packages into the system Python.

```powershell
# From C:\dev\SCION
python -m venv .venv
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r backend\requirements\dev.txt
```

If `pip install` fails with a red SSL or proxy error, you may need to add
Teradata's internal certificate. Ask IT or Rahul Shiyekar for the `.pem` file
and run:
```powershell
.venv\Scripts\pip install --cert path\to\teradata-cert.pem -r backend\requirements\dev.txt
```

---

### Step 5 — Frontend dependencies

```powershell
cd frontend
npm install
cd ..
```

This installs ~500 MB of packages into `frontend\node_modules`. It only needs
to run once (or again after a `package.json` change).

---

### Step 6 — AI configuration file

SCION's AI assistant needs a configuration file that contains an API key.
This file is **not in the repository** (for security reasons).

Ask Guillermo to send you `taisa_llm.yaml` by email or Teams.
Place it at:
```
C:\dev\SCION\backend\app\config\taisa_llm.yaml
```

Do **not** commit this file. It is already in `.gitignore`.

If you don't have the file yet, the app still runs — the AI widget will
return an error, but everything else works normally.

---

### Step 7 — Initialize the database

```powershell
# From C:\dev\SCION
.venv\Scripts\python.exe backend\tools\db_init.py reset --with-seed
```

This creates `scion_dev.db` (SQLite) in the project root and loads demo data
so you have something to explore immediately. It is safe to re-run — it drops
and rebuilds from scratch.

Expected output ends with something like:
```
✓ Schema applied (alembic upgrade head)
✓ Demo seed loaded — 2 snapshots, 500+ objects
```

---

### Step 8 — Run

```powershell
# From C:\dev\SCION
.\dev.ps1
```

`dev.ps1` starts both the backend (FastAPI on port 8000) and the frontend
(Next.js on port 3000) in the same terminal window.

Open your browser at **http://localhost:3000**

You should see the SCION dashboard with demo data loaded.

API docs (Swagger UI) → http://localhost:8000/docs

To stop: press `Ctrl+C` in the terminal.

---

### Step 9 — Verify everything works

Run the backend test suite to confirm nothing is broken:

```powershell
.venv\Scripts\pytest backend\tests\ -v
```

Expected: all tests pass (a couple may be marked `skip` — that is normal).

TypeScript check for the frontend:

```powershell
cd frontend
npx tsc --noEmit
cd ..
```

Expected: no output (zero errors).

---

### Troubleshooting

| Symptom | Fix |
|---|---|
| `dev.ps1` exits immediately with no output | Open PowerShell as Administrator, run `Set-ExecutionPolicy RemoteSigned` |
| Port 3000 or 8000 already in use | Close whatever is using it, or edit `dev.ps1` to use different ports |
| `python: command not found` | Re-open PowerShell after Python install so PATH is refreshed |
| `ModuleNotFoundError` on backend start | Make sure you ran `pip install` inside `.venv`, not with system Python |
| `NEXT_PUBLIC_API_BASE_URL` warning in browser console | Normal in dev — the frontend defaults to `http://localhost:8000/api/v1` |
| AI widget shows "Service unavailable" | `taisa_llm.yaml` is missing or has wrong key — everything else works fine |

---

### After setup — daily workflow

```powershell
cd C:\dev\SCION
.\dev.ps1          # start
# … make changes …
# Ctrl+C            # stop
git add <files>
git commit -m "fix: describe what you changed"
git push origin main
```

When the push includes a new tag (`git tag vX.Y.Z && git push origin main --tags`),
GitHub Actions automatically builds and publishes new Docker images to GHCR.
Production is then updated manually (see §6).

---

## 3. Current state of the codebase (as of v2.09.15)

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
`C:\Users\<you>\.ssh\scion_key`. Ask Guillermo for the key file — keep it
in KeePass, never commit it.

Deploy command (run after GitHub Actions finishes building the new images):
```powershell
ssh -i C:\Users\<you>\.ssh\scion_key root@10.27.122.64 "cd /var/opt/scion && docker compose pull && docker compose up -d"
```

Verify containers are healthy after deploy:
```powershell
ssh -i C:\Users\<you>\.ssh\scion_key root@10.27.122.64 "docker ps --format 'table {{.Names}}\t{{.Status}}'"
```

Expected output — all four containers showing `(healthy)` or `Up`:
```
NAMES            STATUS
scion-frontend   Up 15 seconds (healthy)
scion-backend    Up 21 seconds (healthy)
scion-nginx      Up 30 minutes
scion-postgres   Up 9 hours (healthy)
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
