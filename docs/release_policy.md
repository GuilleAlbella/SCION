# SCION Release Policy (draft)

**Status:** draft for discussion — raised by Kindy in Meeting #7.
**Owner:** Guillermo Albella. Needs sign-off from Chris / Kindy / Rahul
before v1.0 tag.

## Why this document exists

Kindy, Meeting #7:

> "Versions of your code. Clear warranty around the code. Regular release
> cycle. Fallback plan. Plan for bug fixes that apply to all customers —
> not just roll out to individual customers."

Today SCION is a moving target in a single repo. Before we ship to a
customer premise (even as a pilot) we need the below.

---

## 1. Versioning

**Scheme:** Semantic Versioning — `MAJOR.MINOR.PATCH`.

- **MAJOR** — breaking change to the ingest file formats, API contract, or
  on-disk schema (requires customer-side action).
- **MINOR** — backwards-compatible feature (new page, new metric, new
  endpoint).
- **PATCH** — bug fix, UI polish, doc-only, perf improvement.

**Source of truth:** `frontend/src/lib/constants.ts::APP_VERSION`.
`dev.ps1` reads this; Sidebar + Home display it. README has its own
changelog that must be updated by the same commit (manual — enforced by
PR checklist).

**Pre-1.0:** stage = `"BETA"` / `"RC"`. Flip to `""` only when criteria in
section 3 are met.

## 2. Release cadence

- **PATCH:** as needed. Typical turnaround same-day while in internal pilot.
- **MINOR:** every 2 weeks during pilot, monthly afterwards.
- **MAJOR:** only when forced by upstream (parser format change, DB schema
  migration). Avoid aggressively.

Every release produces:
1. A tagged git commit (`vX.Y.Z`).
2. A changelog entry in `README.md` + a matching bullet in `CHANGELOG.md`
   *(to create)*.
3. A smoke-test run of the demo script (`docs/demo_en.txt`) against a fresh
   seeded DB.

## 3. v1.0 GA criteria

Cannot flip `APP_STAGE` from `"BETA"` until:

- [ ] Pipeline 2 (dict) live with at least one real customer extract.
- [ ] Pipeline 3 (usage) at least behind-feature-flag.
- [ ] Authentication (even basic HTTP Basic or SSO proxy) — no naked
      local-only deploys at customer.
- [ ] Automated test coverage ≥ 60% on `backend/app/graph` and
      `backend/app/metrics`.
- [ ] Successful dry-run of the rollback procedure (section 5).
- [ ] Infosec / privacy checklist signed by Rahul's team and customer.

## 4. Bug-fix distribution

**Goal:** a fix developed once applies to every deployed customer — no
per-customer patch branches.

- Fixes land on `main` with tests.
- Released as a `PATCH` bump.
- Every customer deployment is pinned to a version tag; upgrade is
  `git fetch && git checkout vX.Y.Z && .venv\Scripts\pip install -r ...`.
- Hotfix branches (`hotfix/X.Y.Z+1`) are allowed *only* when `main` has
  moved past a breaking change; they cherry-pick the minimal fix.

**Explicitly forbidden:** commenting out a feature for one customer; local
SQL patches applied only to one `kalido_lite.db`; untagged production code.

## 5. Fallback / rollback

Each release must ship with:

1. **Alembic down-migrations** verified for the last one MINOR release.
2. A **`ROLLBACK.md`** in each release's tag describing the exact steps.
3. The ability to downgrade by pulling the previous tag — **no data loss**
   for patch/minor rollbacks. For major rollbacks, a documented data
   export/import dance.

On-call procedure: if a release breaks a customer, the default action is
"roll back first, investigate after." Never fix forward during an incident.

## 6. Scope lock for v1.0

A list of in-scope / out-of-scope items for v1.0, frozen two weeks before
tag. Any scope changes after freeze require Chris approval.

**In-scope today (proposed):**
- Pipelines 1 & 2, Impact, Lineage, Graph (focus mode), Intelligence,
  Changes, TAISA widget, criticality engine (with or without usage).

**Deferred to v1.1 or later:**
- Pipeline 3 (usage) full integration.
- Pipeline 4 (raw code).
- SSO, RBAC.
- Multi-customer / multi-tenancy.

## 7. Security / warranty (stubbed)

To be filled in jointly with infosec. Placeholder:
- No customer data leaves the deployment (LLM calls are the sole exception
  — TAISA sends *metadata only*, never row values).
- All file imports are validated (schema, size cap, charset).
- **Storage backend (as of v2.00.00):** lab environment uses Postgres 16
  (via `docker-compose.lab.yml`); production still uses SQLite on a named
  Docker volume pending the production migration (§2.5a of
  `docs/internal_roadmap.md`). No external network writes in either case.

---

## What this document is **not**

- Not a roadmap (`docs/Hoja de Ruta del Producto.txt` covers that).
- Not a marketing one-pager (`docs/use_cases.md`).
- Not a legal warranty. Point the customer at their MSA.
