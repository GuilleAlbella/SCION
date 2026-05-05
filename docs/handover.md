# SCION — Handover for Helton

**Author:** Guillermo Albella.
**Audience:** Helton Guedes, primary maintainer **2026-05-07 → return TBD**.
**Purpose:** everything you'd want to ask me in person but I won't be
around to answer. Pair this with `docs/internal_roadmap.md` (the
*what's next*) — this doc is the *how to actually do it day one*.

---

## 1. The five docs you have to read first (in order)

| Order | File | Why |
|---|---|---|
| 1 | `README.md` | Architecture, engines, Quick Start, full changelog. |
| 2 | `docs/internal_roadmap.md` | Phases, gates, owner cheat-sheet, decision log. |
| 3 | `docs/use_cases.md` | What SCION actually does, in 8 bullet points. |
| 4 | `docs/ingestion_pipelines.md` | The 4-pipeline architecture (committee decision). |
| 5 | `docs/release_policy.md` | Versioning + release discipline. |

`docs/demo.txt` (Spanish) and `docs/demo_en.txt` (English) are the
demo walkthrough scripts. Useful when you want to validate end-to-end
that nothing broke after a change.

## 2. First-day checklist

Once you've cloned the repo (**not inside OneDrive** — see §6):

```powershell
# 1. Set up the venv + node_modules
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements\dev.txt
cd frontend
npm install
cd ..

# 2. Create the SQLite DB (alembic upgrade head, idempotent) and seed demo data.
#    `db_init.py` is the single canonical entry point: it auto-detects fresh /
#    managed / legacy DB states and applies the correct path. The old
#    `bootstrap_sqlite_db.py` (which used Base.metadata.create_all and could
#    drift from migrations) is gone — `db_init.py reset --with-seed` replaces it.
.venv\Scripts\python.exe backend\tools\db_init.py reset --with-seed

# 4. Run both services
.\dev.ps1
```

UI on http://localhost:3000 · API on http://localhost:8000 ·
docs/swagger on /docs.

If `dev.ps1` exits silently right after starting, that's the WatchFiles
bug — the file `dev.ps1` already has the fix (`--reload-dir app`), so
you should not see it. If you do, see §6.

## 3. What's open right now

**Open PRs (as of 2026-04-29):**
- **#1 `feat/dict-ingest`** — Pipeline 2 backend (data dictionary
  ingest). Reader + detector + validator + persister + endpoint +
  5 integration tests against Rahul's first real sample. Ready to
  merge after your review.
- **#2 `feat/dict-followups`** — Builds on #1 with: Alembic migration
  for `extract_run_id` column (replaces the LIKE lookup), 17 edge-case
  tests for the format detector, the `/import` page with drag-and-drop,
  and this handover doc. Merge after #1.

**Waiting on Rahul:**
- Confirmation on whether dict stays `.dat` or migrates to JSON, and
  whether parser stays JSON. Email sent 2026-04-29 — check his reply
  before any work that locks in format assumptions. Background:
  `Transcripciones/Reunion 8.txt`.

**Phase-1 to-dos in priority order** (full list in `internal_roadmap.md`):
1. **Real-JSON benchmark** the moment Rahul ships a full extract
   (target metrics in roadmap §1.1). This decides SQLite vs Postgres
   for the pilot VM.
2. UI page for **parser-import** in addition to dict-import (today
   only the backend exists).
3. Persist **indices / partitioning / tabletext** to dedicated tables
   (today they're parsed and counted but not stored). Phase-2 schema
   migration when graph engine actually consumes them.
4. **Wire dict snapshots into the change-event engine** so `/changes`
   shows column-type changes derived from dict diffs.

## 4. Where things live (mental map)

```
backend/
├─ app/
│  ├─ api/v1/             # FastAPI routes — one file per resource
│  │  ├─ dict_import.py     ← v1.12.00, the multipart endpoint
│  │  ├─ parser_import.py   ← v1.04, JSON ingest
│  │  └─ ...                ← snapshots, changes, impact, graph, etc.
│  ├─ db/
│  │  ├─ engine.py        # global SQLAlchemy engine (SQLite by default)
│  │  └─ models/          # 1 file per ORM entity
│  ├─ engines/            # the 7 analytical engines (graph, impact, …)
│  ├─ metadata/           # data-dictionary readers + persisters
│  │  ├─ dict_flat_file_reader.py    ← v1.12, real 16-col layout
│  │  ├─ format_detector.py          ← content-based dispatch
│  │  ├─ dict_batch_validator.py     ← same source+run_id check
│  │  └─ dict_persister.py           ← snapshot keyed by run_id
│  └─ ...
├─ tests/                 # pytest, mostly unit + a few integration
└─ tools/                 # db_init.py (schema + seed lifecycle), rich_seed.py, …

frontend/
└─ src/
   ├─ app/                # one folder per route, Next.js App Router
   │  ├─ import/             ← v1.13, the drag-and-drop page
   │  ├─ lineage/, impact/, graph/, …
   ├─ components/
   │  ├─ shared/             ← ObjectPicker, GuidedSection, etc.
   │  └─ layout/             ← PageShell, Sidebar
   └─ lib/
      ├─ api/                # 1 file per resource — typed Axios clients
      ├─ constants.ts        # APP_VERSION, CHART_COLORS, …
      └─ terminology.ts      # changeTypeLabel(), OBJECT_TYPE_STYLES

docs/                     # everything you should know about the project
Parser/                   # Rahul's contracts + sample data
alembic/versions/         # migrations — new ones go here
```

## 5. Conventions we follow (so you don't have to relearn)

- **Branches:** `feat/<slug>`, `fix/<slug>`, `chore/<slug>`. Never push
  to `main`.
- **PRs:** one feature per PR. Always use the template (auto-loads).
  CODEOWNERS auto-requests reviewers. Squash-merge by default.
- **Commits:** short imperative subject, optional body. No conventional-
  commit prefixes — too noisy for a 2-person team. See `CONTRIBUTING.md`.
- **Versioning:** single source of truth is
  `frontend/src/lib/constants.ts::APP_VERSION`. README header + changelog
  must be bumped in the same commit. Use semver.
- **Comments:** explain *why*, not *what*. Files in this repo lean heavy
  on inline narrative — match that style. New empty files with sparse
  comments will get review feedback.
- **Narrative UX:** any new page goes through `GuidedSection` for
  numbered intro-boxed sections. Don't break the pattern silently.
- **Tests:** new backend code ships with a test in `backend/tests/`.
  Frontend smoke tests are aspirational — focus on `npx tsc --noEmit`
  passing.

## 6. Windows gotchas (real ones I hit)

### OneDrive corrupts `.git/index`
**The single most painful issue on this project.** OneDrive sync
slowly mangles `.git/index` over weeks. Symptoms: random
`fatal: index file corrupt`, `error: bad index file sha signature`,
weird ghost commits.

**Fix:** clone outside OneDrive. `C:\dev\SCION` is fine. Already in
`CONTRIBUTING.md` but worth saying twice.

If you inherit my OneDrive copy and it breaks, do a fresh clone from
GitHub — never try to "fix" the index. You'll lose more time than the
clone takes.

### PowerShell 5.1 vs 7
`dev.ps1` is ASCII-only deliberately because PS 5.1 reads files with
the system codepage (not UTF-8) and chokes on Unicode box-drawing
characters. If you edit it in VSCode, **save as ASCII**, not UTF-8 with
BOM. PS 7 doesn't care, but we have to stay 5.1-compatible.

### `--reload-dir app` on uvicorn (the silent-shutdown bug)
WatchFiles on Windows propagates a signal that PowerShell interprets
as Ctrl+C on the parent script when it triggers a backend reload.
We fixed it by limiting reload to `backend/app/` only. If editing
`tools/`, `alembic/`, or `tests/` ever starts killing the dev server
again, that scope was widened — narrow it back.

### `taskkill /T /F` instead of `Kill-Process`
npm and uvicorn spawn grandchildren. `dev.ps1` uses `taskkill /T /F`
on the PIDs because PS's native kill leaves orphans holding ports
3000 and 8000. Don't "simplify" it.

### `gh` CLI is at `%LOCALAPPDATA%\GitHubCLI\bin\gh.exe`
Installed portable on 2026-04-29 because winget was broken on this
machine. Already on the user PATH for new terminals. If you join the
project on a different machine, install gh CLI normally — the portable
install was a one-off.

## 7. Decisions you should know about (so you don't re-litigate)

Full table is in `internal_roadmap.md`'s decision log; the highlights:

- **SCION never connects to a customer DB.** Committee decision,
  re-confirmed by Luis in Meeting #7. All inputs come from Rahul's
  offline extractors as files. Don't add a JDBC/ODBC connector
  "because it'd be easier" — it would, but politically it's a
  different conversation.
- **`extract_run_id` is the snapshot key for dict-import.** Every
  record stamped by Rahul's extractor shares this UUID-ish identifier;
  validating consistency at ingest time is what prevents mixed-batch
  corruption.
- **Two ingest endpoints, one detector.** `/parser-import` and
  `/dict-import` stay separate because they consume different content.
  `format_detector.py` is the shared dispatch piece — reuse it if a
  third pipeline (usage) needs it.
- **Column changes redirect to parent table for /lineage.** Columns
  aren't graph nodes in SCION — only databases / tables / views /
  procs are. The redirect happens in `/lineage` UI (green banner) and
  in `/impact` backend (column → parent fallback in `graph_diff_linker`).
- **FK direction in graph: referenced → fk_holder.** A FK from
  accounts(customer_id) to customers means accounts depends on
  customers, not the other way around. This was a bug fix in v1.10.

## 8. Things I'd do if I had one more day

(In case you have a slow day and want a backlog. None of these block
anything.)

1. **Replace the description-LIKE idempotency fallback in
   `dict_persister.py`** with a single `extract_run_id` lookup once
   v1.13 has shipped. Drop ~5 lines of code, no semantic change.
2. **Persist indices to a dedicated `index_snapshot` table** — model
   already has `IndexRecord`, just need migration + persister update.
   Unblocks "what indexes did this object have?" in `/lineage`.
3. **Server-side pagination for `/changes`** when event count crosses
   ~10k. Today the page loads everything; fine on demo data, fragile
   on real customer extracts.
4. **`tools/benchmark_ingest.py`** end-to-end timing script. Spec is
   in `internal_roadmap.md` §1.1 — runs an ingest and prints the
   metrics we care about for SQLite-vs-Postgres decision.

## 9. Who to ping when

| Topic | Person | Channel |
|---|---|---|
| What is SCION supposed to do? | Pilar (PM) | Teams |
| Parser / dict / extractor questions | Rahul Kulkarni | Teams |
| Infra / VM provisioning | Rahul Shiyekar | Teams (via Pilar) |
| Scope / release sign-off | Chris | through Pilar |
| Sales-readiness / customer feedback | Kindy Flyvholm | through Pilar |
| Time-tracking / project codes | Pilar / Luis | Teams |
| Codebase questions | me, when I'm back | — |

Save Pilar's number. She's the central node and unblocks 80% of
non-technical questions in one ping.

## 10. If you're stuck on something I didn't anticipate

- **First**, search `Transcripciones/`. Every meeting since project
  start is transcribed. Most "why is X this way?" answers live there.
- **Second**, search the README changelog. Each version has a one-bullet
  "why" for every change.
- **Third**, look at the decision log in `internal_roadmap.md`.
- **Fourth**, look at recent PR descriptions on GitHub.
- **Fifth**, ask Pilar.

I'll be back. Ping me on email if it's truly blocking and not
embarrassing — `[email]@teradata.com`. (Vacation message will be on,
expect 24h delay.)

Good luck — you've got everything you need. The codebase is in a
healthy state and the roadmap is realistic. Don't over-engineer.
