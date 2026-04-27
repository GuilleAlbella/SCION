# SCION — What It Does Today (one-pager)

**Audience:** account architects & sales engineers (US, EMEA, APAC).
**Purpose:** starting point for the 30-min working sessions Kindy proposed
in Meeting #7 — we ship this, they react, we aggregate and refine.

---

## In one sentence

SCION tells you **what changed in a Teradata warehouse, why it matters, and
what breaks if it does** — automatically, across every parsed BTEQ/SQL job
and every snapshot over time.

## Use cases the current build supports

### 1. Pre-deployment impact analysis
*"If I merge this change, what else will I have to touch?"*

Compare any two snapshots → SCION lists every object that changed, classifies
severity, and traces downstream consumers via graph edges. Replaces the
manual "grep the whole codebase" Data DNA teams do today.

**Personas:** developers, release managers, architects.

### 2. Post-incident root cause
*"Production broke last night. What changed?"*

Timeline view: every change event, clickable, ranked by criticality. Z-score
anomaly detection flags snapshots with unusually high change volume.

**Personas:** on-call engineers, managed-service teams.

### 3. Environment-sync validation
*"Is dev actually in sync with prod?"*

Import one snapshot from each environment, run the diff. Any drift is
surfaced as change events, already classified HIGH / MEDIUM / LOW.

**Personas:** Kindy flagged this in the meeting as a high-value use case —
"they think things are in sync but of course they're not."

### 4. Lineage discovery
*"Where does this table's data come from? Who uses it?"*

Interactive graph, N-hop drill. Search or drill-down by database →
table/view → column. Designed for hundred-thousand-object warehouses, not
10-node demos.

**Personas:** data stewards, governance, report owners.

### 5. Criticality-weighted change review
*"I have 200 changes. Which 10 do I actually care about?"*

Criticality engine combines graph centrality + usage (when Pipeline 3 lands)
+ blast radius. The "HIGH" shortlist is usually 5–10% of total changes.

**Personas:** architects, data owners, planners.

### 6. Co-change pattern mining
*"When X changes, what usually changes with it?"*

Apriori-style association mining over change history. Catches silent
couplings the schema doesn't enforce (e.g. "amount is always followed by
currency 3 days later").

**Personas:** architects doing refactoring planning.

### 7. Volatility profiling
*"Which objects are the firefighting hot-spots?"*

Rolling 30-day change-rate per object. Highlights objects that are
continuously churning — usually a sign of unclear ownership or bad schema.

**Personas:** architects, managed-service leads.

### 8. Natural-language Q&A (TAISA)
*"Ask SCION anything about your warehouse."*

TAISA, grounded on the parsed snapshot + change events.
Demoed live. Works best for "what / why / when" questions about specific
objects.

**Personas:** any — zero-training entry point.

---

## Use cases **not** in the current build (be honest)

- ❌ Direct connection to customer DB (architectural decision, not a gap).
- ❌ Write-back / auto-remediation.
- ❌ ML-based anomaly root-causing (we detect, we don't explain yet).
- ❌ Multi-warehouse federation (one customer at a time).
- ❌ SSO / enterprise auth (local-only for now).

---

## Ask for the session

We'd like 30 minutes with **2 architects per region** (US, EMEA, APAC) to ask
three questions:

1. Which of these use cases would you sell first, and to whom?
2. What's missing that would unblock a deal?
3. What language do customers actually use for this problem? (So we can
   name things the way they already think about them.)

*Kindy to coordinate scheduling.*
