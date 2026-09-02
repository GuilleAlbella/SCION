# SCION Roadmap

Forward-looking plan for SCION releases. Companion to `CHANGELOG.md`
(which records what already shipped) and `docs/internal_roadmap.md`
(the detailed engineering view with decision log and owner cheat-sheet).

Current version: **v2.09.12 BETA** (see `frontend/src/lib/constants.ts`).

---

## Completed phases

### Phase 0 — Foundations ✅

7 backend engines, 13 UI pages, Pipeline 1 (parser JSON ingest), narrative
UX with guided sections. Shipped as v1.11.00 BETA.

### Phase 1 — Pipelines 2 & 3 ✅ (done v1.21.43)

- Pipeline 2 (data dictionary `.dat` batch) — live since v1.12
- Pipeline 3 (PDCR usage statistics) — live since v1.21.6
- Column-level lineage via DataDNA parser — live since v1.21.23
- Containerised Docker deploy with GHCR images — v1.21.0
- 165 CVEs cleared — v1.21.4

### Phase 2 — Scale & Hardening ✅ (mostly done, one item pending)

All major items completed by v2.09.12:

| Item | Done | Version |
|------|------|---------|
| SQLite → PostgreSQL migration | ✅ | v2.00.00 |
| Graph engine performance (SQL GROUP BY, dead-code removal) | ✅ | v2.01.00 |
| Frontend infinite scroll (Changes, Impact) | ✅ | v2.02.00 |
| Staging Layer (validation pipeline, import status) | ✅ | v2.03.00 |
| Integration Model / entity layer (object_entity, cross-snapshot IDs) | ✅ | v2.03.00 |
| Access Layer — Landscape page | ✅ | v2.03.00 |
| Production runtime (systemd units, structured JSON logging) | ✅ | v2.04.00 |
| Column-level lineage navigation (breadcrumb, BFS traverse) | ✅ | v2.05.00 |
| AI column PII classification (TAISA batch, badges, filter) | ✅ | v2.06.00 |
| Reference Data (org hierarchy + business apps, `/reference` page) | ✅ | v2.07.00 |
| Incremental snapshot handling (baseline tracking, gap detection) | ✅ | v2.08.00 |
| Manifest-derived timestamps in Snapshots page | ✅ | v2.09.00 |
| Phase 2 deep audit — 25+ correctness + reliability fixes | ✅ | v2.09.01–v2.09.06 |
| Case normalisation + change-ID search (Rahul round-3 bugs) | ✅ | v2.09.08 |
| VIEW object type + duplicate node prevention in graph | ✅ | v2.09.11 |

**Still pending in Phase 2:**

- **§2.15.d Progressive Disclosure UI** — Landscape and key pages rewritten
  in business language (by dept/app, not by snapshot/schema). Kindy Flyvholm
  confirmed this is the differentiated value. Piloting on Landscape first,
  then extending to Changes, Intelligence, Timeline if validated by Chris/Ripley.

- **§2.10 pending items** — usage filter by team/dept in Usage + Intelligence
  pages; TAISA user/app context in Q&A. Blocked on PDCR extractor providing
  per-user rows (today only `user_count`).

- **§2.15.c Entity-Centric view** — criticality trend chart + usage trend
  per object. Backend `/entity/{id}/history` is ready; frontend chart
  components pending.

---

## Phase 3 — First Customer Pilot 🔴 Blocked

**Blocked on:** Phase 2 §2.15.d, authentication, infosec clearance.

- Auth: decide HTTP Basic / SSO via Teradata IDP / reverse-proxy with
  customer auth. `API_KEY` header auth is built in but not sufficient alone.
- Infosec: no PII in logs, no row-level data exfiltration via TAISA.
- Release discipline: tag v1.0-rc1, write `ROLLBACK.md`, verify Alembic
  down-migrations end-to-end. Per `docs/release_policy.md`.
- Use-case validation sessions with 6–8 field architects (Kindy to organise).

---

## Phase 4 — v1.0 GA 🔴 Future

Flip `APP_STAGE` from `"BETA"` to `""` once all GA criteria in
`docs/release_policy.md §3` are satisfied. Sign-off needed from:
Chris (scope), Kindy (sales-readiness), Rahul (extractor stability), infosec.

---

## Near-term backlog (no version pinned)

- **§2.3 Dict view-definition parsing** — parser team to parse view DDLs
  from the data dictionary so SCION fills lineage gaps for views created
  before the DBQL extraction window. Same JSON output format as Pipeline 1.
- **§2.4 DDL timestamp merge** — keep the most recent DDL version when the
  same object arrives from both DBQL and dict extracts. Absorbed into §2.16
  staging validator but not yet surfaced in UI.
- **In-app update button** — trigger `update.sh` from the sidebar version
  pill. Backend `POST /system/update` → Watchtower API. ~1 day.
- **TAISA batch reasoning cap** — reasoning-event generator can spike memory
  on very large change sets. Cap + paginate.
- **SSO / RBAC** — required for multi-user deployments. Likely Azure Entra.
- **Audit log UI** — surface `usage_event` + `reasoning_event` in a
  filterable table for compliance review.
- **Per-object usage idempotency** — re-uploading the same
  `pdcr_object_usage_*.dat` currently inserts duplicates. Needs a natural
  key on `usage_event`.
- **Security + ops runbooks** — pre-GA blockers tracked in `docs/SPEC.md §13.4`.

---

## Out of scope

- **Kubernetes Helm chart** — overkill for single-VM topology.
- **Real-time change detection** — current model is batch-on-demand.
- **Mobile UI** — desktop-first; mobile is read-only at best.
- **Custom LLM fine-tuning** — TAISA uses the platform model.
- **Raw code pipeline (Pipeline 4)** — deferred until a customer asks.
  Parsed tree is sufficient for impact + lineage today.

---

*Last updated: 2026-09-02. Edit this file when scope shifts.*
