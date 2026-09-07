# Analysis of SCION's SPEC.md — SDD and DDD Principles

**Date:** 2026-05-28
**Document analyzed:** `SPEC.md` v1.21.5-spec-r10-update
**Scope:** Evaluation of the specification through the lenses of Spec-Driven Development (SDD) and Domain-Driven Design (DDD)

---

## 1. Evaluation under Spec-Driven Development (SDD)

SDD requires the specification to be the primary artifact that drives all implementation: specify before coding, traceable requirements with testable criteria, explicit scope boundary, and the pipeline SPECIFY → DESIGN → TASKS → EXECUTE.

### 1.1 Strengths — what the SPEC already does well

**Spec-first as a living contract.** The document explicitly states: "Any new FR enters this document before the code" (§14.3.1). SPEC.md lives alongside the code, and the CI pipeline treats deviations between spec and implementation as failures (schema_parity test). This materializes SDD's central principle that the spec is the source of truth, not the code.

**Requirements with RFC-2119 vocabulary.** Every FR consistently uses MUST / SHOULD / MAY (§5), allowing a reviewer to compare code against the spec and determine conformance objectively. This is equivalent to the harness's WHEN/THEN/SHALL format — the language differs, but the traceability is the same.

**Non-Goals documented with rationale.** §2.2 lists 13 non-goals (NG1–NG13), each with an explicit justification and the instruction "Anyone proposing to relax one should engage with the rationale first". This fulfills SDD's "Out of Scope" principle with above-average rigor.

**Golden Examples as acceptance anchors.** §9 defines 5 input → expected output examples that function simultaneously as smoke tests and as acceptance criteria. This is exactly what SDD requires: verifiable, independently testable criteria.

**Inline scope guards in FRs.** Each FR that touches a dangerous boundary has an explicit "scope guard" (e.g., FR-1.1 declares "This endpoint never accepts SQL, scripts, or BTEQ files — those go to DataDNA"). This prevents scope creep at the individual requirement level.

**Determinism as a first-class property.** The spec treats idempotency and determinism as formal requirements (structural_hash, identical diff for the same inputs, schema_parity). In SDD, this is equivalent to acceptance criteria that can be verified by automation.

### 1.2 Gaps and improvement opportunities

**No traceable IDs per individual requirement clause.** FRs use grouped IDs (FR-1, FR-2, ... FR-13), but the MUST clauses within each FR have no atomic IDs. SDD requires granular traceability: each MUST clause should have an ID (e.g., FR-1.1-MUST-01, FR-1.1-MUST-02) so that a test can reference exactly which clause it validates. Today, the test → requirement mapping depends on human reading of free-form text.

**Acceptance criteria do not follow WHEN/THEN/SHALL format.** §12 lists 10 criteria (AT-001 to AT-010), but in narrative, unstructured format. Converting to the harness format would make each criterion independently testable and automatable:

```
# Today (narrative):
AT-001: "Demo extract ingests, snapshot finalises, structural_hash is a 64-char hex"

# Suggested (WHEN/THEN/SHALL):
AT-001: WHEN dict-import receives the 6-file demo extract
        THEN the system SHALL finalize the snapshot with a 64-character hex structural_hash
        AND the post-ingest pipeline SHALL complete without errors
```

**No tasks.md or formal breakdown.** The SPEC covers SPECIFY and DESIGN, but there is no artifact that decomposes FRs into atomic tasks with dependencies, verification, and associated commits. ROADMAP.md is mentioned as a "forward-looking plan", but it does not substitute a task breakdown in SDD format. For future features (FR-1.3 usage import, §10.10 end-user testing), the absence of tasks.md can lead to ad-hoc implementation.

**No STATE.md or HANDOFF.md.** The document does not reference mechanisms for persisting state between development sessions. For a single-maintainer project (a declared risk in §14.2), the absence of STATE.md and HANDOFF.md increases the bus factor. The spec acknowledges the problem (§13.4 "win the lottery test") but does not adopt the SDD solution.

**Planned tests with no firm target date.** §10.10 (end-user scenario testing) and §11.5 (cross-team test plan) are in "Planned — pending" status. SDD requires tests to be written before implementation (RED → GREEN → VERIFY). These tests remained as a verbal commitment post-Meeting 10, with no completeness criterion.

---

## 2. Evaluation under Domain-Driven Design (DDD)

DDD organizes software around the problem domain, with ubiquitous language, bounded contexts, aggregates, entities, value objects, and a clear separation between domain, application, and infrastructure.

### 2.1 Strengths — implicit alignment with DDD

**Well-defined ubiquitous language.** The Glossary (Appendix A) defines 22 domain terms with precision: Snapshot, ChangeEvent, BlastRadius, GraphNode, GraphEdge, TAISA, FK heuristic, Parser feed, etc. These terms are used consistently throughout the spec, in ORM table names (§7.1), in endpoints (§8.1), and in tests (§10). This is ubiquitous language in action — the same vocabulary spans spec, code, and communication with stakeholders.

**Implicit and well-separated Bounded Contexts.** The spec organizes the 19 ORM tables into 5 functional groups (§7.1):

| Group | Tables | Implicit Bounded Context |
|---|---|---|
| Snapshot core | 8 tables | **Structure Context** — warehouse capture and versioning |
| Process flow | 2 tables | **Process Context** — inferred ETL flow |
| Diff + impact | 5 tables | **Change Context** — detection, severity, blast radius |
| Alerts + reasoning | 2 tables | **Intelligence Context** — TAISA + proactive alerts |
| Usage + criticality | 2 tables | **Usage Context** — consumption signals and criticality |

The backend module separation (`app/snapshot/`, `app/diff/`, `app/graph/`, `app/taisa/`, `app/usage/`) reflects these contexts. Each has its own engine, its own models, and its public interface (§8.2).

**Clearly identifiable root Aggregate.** The `Snapshot` is the domain's root aggregate: every relevant operation (diff, graph, impact, alerts, metrics) references a `snapshot_id`. The spec reinforces this in FR-2: "A Snapshot is the canonical immutable representation of the warehouse at time T" and "MUST be created exclusively through the snapshot engine". This is exactly the Aggregate Root pattern — centralized creation control, unique identity, transactional consistency boundary.

**Distinguishable Entities vs Value Objects.** The spec implicitly differentiates:

- **Entities** (persistent identity): Snapshot, ChangeEvent, GraphNode, GraphEdge, ReasoningEvent — all with IDs and their own lifecycle.
- **Value Objects** (identity by value): `structural_hash` (deterministic, content-addressed), `PaginatedResponse` envelope (§7.2), severity/is_breaking as immutable classifications of a ChangeEvent.

**Explicit Anti-Corruption Layer.** The SCION ↔ DataDNA boundary (§1.5) is designed as an ACL: SCION receives JSON from the parser via `/parser-import`, validates it, translates it into internal `graph_edge`, and never exposes parser concepts (Tier-1/2/3) beyond the glossary. Communication is unidirectional. This protects SCION's domain model against changes in DataDNA's model.

**Domain Events as a first-class concept.** The `ChangeEvent` is literally a domain event materialized in a table. It captures what changed, when, with what severity, and whether it is breaking. The post-ingest pipeline (FR-1.4) reacts to these events to generate impact, alerts, and criticality — a classic event-driven flow.

**Domain invariants documented.** The spec codifies explicit invariants:

- A Snapshot is only finalized after the complete pipeline runs (FR-2)
- IN-clauses are always chunked to 900 (a technical invariant that protects the domain from SQLite infrastructure)
- Diff is deterministic for the same inputs (FR-3)
- TAISA never receives user data in the context beyond the question (FR-6)
- No endpoint silently produces partial output (FR-13)

### 2.2 Gaps and improvement opportunities

**Bounded Contexts are not explicitly named.** The separation exists in practice, but the spec does not use the term "bounded context" or declare formal boundaries between modules. Consequence: there is no documented Context Map. A reader of the spec sees the separation, but not the rules governing what happens when contexts need to communicate (e.g., how the Change context consumes data from the Structure context). Documenting a Context Map would prevent accidental coupling as the system grows.

**No explicit Domain Services layer.** The "engines" (§8.2) mix pure domain logic with infrastructure orchestration. For example, `compute_batch_impact` performs graph traversal (domain) AND IN-clause chunking (infrastructure). DDD would recommend isolating the traversal logic in a pure, database-free Domain Service, and delegating the chunking to a Repository. Today, the coupling is tolerable given the project's size, but it will become a problem in the migration to Postgres (v1.25).

**No formal Repository Pattern.** The spec mentions that engines "accept an explicit Session or engine when called from tests" (§8.2), which is good for testability, but does not declare an abstract repository interface. ORM models (SQLAlchemy) are used directly in the engines. For the Postgres migration, the absence of Repositories may force refactoring of the engines. The document itself already anticipates this: "The portability hygiene step in v1.22 (replace INSERT OR IGNORE / strftime / julianday with ANSI equivalents) is what makes the move tractable" — but that is an infrastructure patch, not a layer separation.

**Value Objects are not modeled as such.** `severity`, `change_type`, `edge_type`, `is_breaking` are treated as strings/booleans in the ORM models. In DDD, these would be Value Objects with built-in domain validation (e.g., severity only accepts LOW/MEDIUM/HIGH, change_type only accepts ADDED/DROPPED/ALTERED/RENAMED). The spec defines the valid values, but the guarantee depends on validation in the application layer, not in the domain model.

**Domain event with no bus or formal handler.** The `ChangeEvent` is persisted and read, but there is no publish/subscribe mechanism between contexts. The post-ingest pipeline (FR-1.4) is a procedural sequence (steps 1, 2, 3, 4, 5, 6). If a new consumer needs to react to a ChangeEvent (e.g., an external webhook in the future, even though it is NG12 today), the architecture will require modifying the pipeline. An internal event bus (even a simple one, without Kafka) would provide extensibility without violating NG12.

**Process model (process/step) poorly integrated.** The `process` and `step` tables are mentioned in §7.1 but do not appear in any FR, any golden example, any test scenario, or any acceptance criterion. [Inference] They appear to be a remnant of a planned feature that was never fully specified. In DDD, entities without a mapped use case are candidates for removal or explicit placement in "Out of Scope".

---

## 3. Consolidated view — Maturity Map

| Dimension | Current level | Recommended target | Effort |
|---|---|---|---|
| **Ubiquitous language** | High — glossary + consistent use | Maintain | Low |
| **Bounded contexts** | Medium — implicit separation in modules | Name and document Context Map | Medium |
| **Aggregates** | High — Snapshot as root, centralized creation | Maintain | Low |
| **Value Objects** | Low — treated as primitives | Encapsulate in domain classes | Medium |
| **Repositories** | Low — direct ORM in engines | Abstract interface before Postgres (v1.25) | High |
| **Domain Events** | Medium — ChangeEvent exists, but procedural pipeline | Introduce simple handler registry | Medium |
| **Anti-Corruption Layer** | High — explicit DataDNA boundary | Maintain | Low |
| **SDD traceability** | Medium — FRs with MUST/SHOULD, but no atomic IDs | Add IDs per MUST clause | Low |
| **WHEN/THEN criteria** | Low — narrative format in §12 | Convert AT-001..010 to WHEN/THEN/SHALL | Low |
| **Tasks breakdown** | Absent for future features | Create tasks.md per feature starting v1.22 | Medium |
| **STATE/HANDOFF** | Absent | Adopt to mitigate bus factor | Low |

---

## 4. Prioritized recommendations

### P1 — Do before v1.22

1. **Add atomic IDs to the MUST clauses of each FR.** Moving from "FR-1.1 block of text" to "FR-1.1-M01, FR-1.1-M02, ..." allows each test to reference exactly one clause. Effort: one SPEC review session.

2. **Convert AT-001..010 to WHEN/THEN/SHALL format.** Facilitates automation and eliminates ambiguity in acceptance validation.

3. **Create STATE.md in the repository.** Record recent decisions, blockers, and deferred ideas. Bus factor is the #1 risk declared by the spec itself.

### P2 — Do during v1.22–v1.24

4. **Document the Context Map.** Name the 5 bounded contexts, declare which depend on which, and define whether the relationship is Shared Kernel, Customer-Supplier, or Conformist.

5. **Introduce Repository interfaces** for the engines that access the database directly. Starting with the `snapshot engine` and the `impact engine` — the ones most affected by the Postgres migration.

6. **Encapsulate critical Value Objects.** `Severity`, `ChangeType`, `EdgeType` as domain enums with validation. This already exists partially in the Pydantic models (§7.2), but not in the ORM models.

### P3 — Do before v1.25 (Postgres)

7. **Separate domain logic from infrastructure in the engines.** Extract graph traversal, severity logic, and criticality scoring into pure functions that do not import SQLAlchemy.

8. **Resolve the state of the process/step tables.** Either specify them (FR + golden example + test) or move them to non-goals.

---

## 5. Conclusion

SCION's SPEC.md is a high-quality document that already practices SDD in spirit — spec-first, explicit boundaries, documented non-goals, golden examples as anchors. The alignment with DDD is strong in the aspects of ubiquitous language, aggregates, and anti-corruption layer, but weak in the formalization of bounded contexts, repositories, and value objects.

The most critical gaps are not conceptual — they are matters of formalization. The domain knowledge is in the document; what remains is to structure it in the patterns that enable automated traceability (SDD) and safe architectural evolution (DDD). The recommendations above are incremental and can be adopted without a rewrite, which respects the harness's principle of "surgical changes".
