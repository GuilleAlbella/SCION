---
name: lineage-evaluation-harness
description: Evaluate DataDNA / Code Parser lineage outputs for Teradata SQL using deterministic JSON contract checks, approved expected-output comparison, and AI-assisted triage. Use when reviewing parser lineage JSON, building a lineage verification checklist, preparing a POC for Rahul's parser team, comparing actual vs expected lineage, or validating cases where expected output is missing but structural lineage invariants can still be checked.
---

# Lineage Evaluation Harness

Use this skill to evaluate DataDNA lineage output without building a second parser. The harness treats the parser output as a contract: compare stable natural-key records when an approved expected JSON exists, run structural invariants when it does not, and use AI only to explain evidence and guide review.

## Operating principle

Do not claim full semantic correctness from AI-only review. Classify evidence as:

- `APPROVED_GOLDEN_MATCH`: actual output matches an approved expected JSON.
- `DETERMINISTIC_ISSUE`: contract/invariant failure found by script.
- `STRONG_EVIDENCE`: output is internally consistent but no approved expected JSON exists.
- `AI_REVIEW_REQUIRED`: AI generated/triaged a candidate expected result; SME approval is still needed.

This is the point Rahul challenged in meeting 26: the POC must not create a regex parser to test an ANTLR parser.

## Quick workflow

1. Find the SQL input, actual parser JSON, and optional approved expected JSON.
2. Run `scripts/evaluate_lineage.py`.
3. Read the generated Markdown report first; use JSON report for automation.
4. If expected output exists, focus on missing/extra semantic records.
5. If expected output does not exist, focus on invariant failures and call out that semantic correctness still needs first-time human approval.
6. For new features, ask the SME to approve only the uncertain deltas; once approved, promote the expected JSON into the regression pack.

## Commands

Compare actual vs approved expected:

```powershell
python skills\lineage-evaluation-harness\scripts\evaluate_lineage.py `
  --actual Parser\docs\02_Data_Lineage\04_Testing\sample\CTAS\create_table_as_lineage_spec_output.json `
  --expected Parser\docs\02_Data_Lineage\04_Testing\sample\CTAS\create_table_as_lineage_spec_output.json
```

Run no-golden structural checks:

```powershell
python skills\lineage-evaluation-harness\scripts\evaluate_lineage.py `
  --actual path\to\actual_lineage.json `
  --json-report lineage_report.json
```

## What the bundled script checks

- Required top-level collections are present and have the expected list shape.
- Natural-key records compare stably while ignoring volatile fields such as parse run id and timestamp.
- Tier-1, Tier-2, Tier-3, and LineageFact lineage edges are compared by semantic source/target/step keys.
- Lineage rows reference declared datasets and attributes where those collections are present.
- Tier-2 and LineageFact attribute edges have supporting Tier-1 or declared lineage evidence.
- Tier-3 dataset edges cover the dataset-level rollup implied by attribute-level lineage.
- Duplicate semantic records are surfaced for review.

## References

Read `references/parser-team-positioning.md` when preparing the demo narrative or explaining the approach to Rahul/Ashish/Soham.
