# Parser team positioning

## Message for Rahul's concern

The harness is not another parser. It does not parse SQL to infer lineage. It evaluates the parser's emitted lineage JSON using:

1. Contract checks: required collections, required keys, natural-key references, rollups.
2. Golden comparison: exact semantic diff against approved expected JSON.
3. AI-assisted triage: explain discrepancies, group likely root causes, and draft expected output candidates.

The AI part is useful for reducing review effort, not for silently replacing approval. For a new feature, first-time expected outputs still need SME review. Once approved, they become regression assets.

## POC scope

Use 3-5 Teradata cases:

- one known-correct SQL with approved expected output;
- one known parser defect if Rahul provides it;
- one or two complex SQL examples from the existing sample corpus;
- optionally one case without approved expected output to demonstrate no-golden checks.

The demo should show three outcomes:

- pass against golden;
- actionable diff against golden;
- no-golden report with confidence limits.

## Talking points

- This reduces repeated manual review after the first approval cycle.
- It does not remove the need to approve brand-new semantics.
- It makes review smaller: humans inspect exceptions and uncertain cases, not every cell.
- It gives Rahul's team a repeatable regression pack as features are added.
- It is technology-adapter friendly: Teradata first; Informatica later when XML/mapping rules and expected behavior are available.

## Known open questions to settle before hardening

- Should Tier-2 repeated source usage be deduplicated or emitted as duplicate rows?
- Should `attributeNaturalKey` be `dataset|column` or column-only?
- Should Teradata identifiers be normalized to uppercase, or should output preserve source casing?
- Which fields are contractually stable and which are audit-only/volatile?
