# Contributing to SCION

Internal Teradata project. Two maintainers (Guillermo, Helton). This doc is
the short version of how we work — read once, reference when in doubt.

## Quick start

```powershell
# clone
git clone https://github.com/GuilleAlbella/SCION.git
cd SCION

# IMPORTANT: do NOT clone inside a OneDrive-synced folder. OneDrive
# corrupts .git/index over time. Use C:\dev\SCION or similar.

# backend
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements\dev.txt

# frontend
cd frontend
npm install
cd ..

# seed demo data
.venv\Scripts\python.exe backend\tools\rich_seed.py

# run both services
.\dev.ps1
```

UI at http://localhost:3000 · API at http://localhost:8000 · Docs at /docs.

## Branch naming

| Pattern | When |
|---|---|
| `feat/<short-slug>` | new feature or page |
| `fix/<short-slug>` | bug fix |
| `chore/<short-slug>` | refactor, docs, deps, CI |
| `hotfix/<short-slug>` | urgent fix on top of a release tag |

No work on `main` directly. `main` is the protected, releasable branch.

## Commit messages

Short imperative subject, optional body. Skip the conventional-commit prefix —
we're a 2-person team, the noise outweighs the value.

Good:
```
Fix Impact donut showing zero counts for column-level changes

Column events weren't matched against the parent table in
graph_diff_linker; added a fallback that uses object_identifier.rsplit('.', 1).
```

Bad:
```
fix: stuff
```

## Pull requests

- Always open a PR, even for one-line fixes (audit trail).
- Use the PR template — it auto-loads.
- One reviewer required. Either of us can approve the other's PRs.
- CODEOWNERS auto-requests reviewers based on which paths changed.
- Squash-merge by default. Rebase-merge for chains of independent commits.

## Versioning (see `docs/release_policy.md` for the full policy)

Single source of truth: `frontend/src/lib/constants.ts::APP_VERSION`.
Every PR that ships user-visible behaviour bumps it:

- **PATCH** (`v1.11.01 → v1.11.02`): bug fix, doc-only, polish.
- **MINOR** (`v1.11.00 → v1.12.00`): new feature, new page, new metric.
- **MAJOR**: only when ingest format or API contract breaks.

Add a matching changelog entry to `README.md`.

## Code style

- **Backend:** PEP 8, type hints on public APIs. We don't run a formatter
  yet — keep diffs small.
- **Frontend:** TypeScript strict. No `any` unless commented why. Prefer
  `useMemo` over re-computation. Recharts: explicit width/height,
  `ResponsiveContainer` only when you've tested it doesn't warn.
- **Comments:** explain *why*, not *what*. Files in this repo lean heavy
  on inline narrative — match that style.
- **Narrative UX:** any new page goes through `GuidedSection` for numbered,
  intro-boxed sections. Don't break the pattern silently.

## What NOT to commit

- `.env`, `.env.local`, anything with API keys.
- `kalido_lite.db` and other `*.db` files.
- `frontend/node_modules/`, `.venv/`, `__pycache__/`, `.next/`.
- Customer data of any kind. Even synthetic-looking test files — when in
  doubt, ask.

`.gitignore` covers most of this. If you accidentally stage a secret,
**rotate it first**, then `git rm --cached` and force-push to your branch.
Don't try to "rewrite history" on `main`.

## Tests

Today: minimal. Goal in `docs/internal_roadmap.md` is 60% backend coverage
on `graph/` and `metrics/` before v1.0 GA. New backend code should ship
with a test in `backend/tests/`.

Frontend tests are aspirational at this point — focus on `npx tsc --noEmit`
passing and a manual walk-through against `docs/demo_en.txt`.

## Where to look

| Question | File |
|---|---|
| What does SCION do? | `docs/use_cases.md`, `docs/demo_en.txt` |
| What's next on the roadmap? | `docs/internal_roadmap.md` |
| How do data inputs work? | `docs/ingestion_pipelines.md` |
| How do we release? | `docs/release_policy.md` |
| Why is X the way it is? | `docs/internal_roadmap.md` § Decision log |
| How do I run it locally? | This file (top), or `dev.ps1` |

## Handover notes

Guillermo on vacation **2026-05-07** through TBD. Helton primary maintainer
during that window. See `docs/handover.md` (TBD) for open tasks list.

## Asking for help

Slack/Teams the other maintainer first. Loop in Pilar (PM), Rahul Kulkarni
(parser/extractor), Rahul Shiyekar (infra), Chris (scope), Kindy (sales) as
the topic warrants. The owner cheat-sheet at the bottom of
`docs/internal_roadmap.md` is the source of truth.
