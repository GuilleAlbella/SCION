<!--
  SCION pull request template.
  Delete sections that don't apply. Don't delete the checklist.
-->

## What

<!-- One paragraph: what does this PR change and why. -->

## How

<!-- High-level approach. If non-obvious, explain trade-offs. -->

## Linked issue / meeting / decision

<!-- e.g. "Meeting #7 follow-up", "v1.11.00 spec", or N/A -->

## Screenshots / output

<!-- For UI changes: before/after. For backend: sample API response or log line. -->

---

## Checklist

- [ ] Code compiles: `cd frontend && npx tsc --noEmit`
- [ ] Backend tests pass: `pytest backend/tests/` (if applicable)
- [ ] Manual smoke test on `dev.ps1` against fresh seed (if applicable)
- [ ] `APP_VERSION` bumped in `frontend/src/lib/constants.ts`
- [ ] README changelog entry added
- [ ] No secrets committed (`.env`, API keys, customer data)
- [ ] If this changes ingest formats or DB schema → Alembic migration included
- [ ] If this is a UX change → narrative pattern preserved (`GuidedSection`)
- [ ] Doc updated when relevant (`docs/internal_roadmap.md`, `docs/release_policy.md`, etc.)

## Reviewer notes

<!-- Anything the reviewer should pay extra attention to. -->
