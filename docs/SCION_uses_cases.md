# SCION E2E Integration Use Cases

**Source:** Reunion 14 - end to end testing - 4  
**Purpose:** define a practical integration-testing pack for SCION using realistic Transcend-scale extracts.  
**Scope:** technical integration and flow validation, not full UAT. Deep business/end-user validation should be performed later by DataDNA/product owners or beta users.

---

## Direction From Reunion 14

The team agreed to adjust the testing scope:

- Avoid a long UAT-style cycle without dedicated DataDNA/product end-user ownership.
- Complete a shorter integration cycle to confirm that the end-to-end data flow works.
- Focus on whether extracted data is ingested, persisted, compared, enriched, and surfaced correctly across SCION screens.
- Use real Transcend-scale extracts where possible, because demo data is too small to validate performance.
- Run only a few concrete test cases per major screen, using known tables/views/columns from the extracts.

## Required Test Data

Minimum dataset:

1. Two complete data-dictionary extracts from the same Teradata platform, captured at different times.
2. Parser lineage output for the same platform, ideally including at least one table and one view.
3. PDCR Object Usage extract for the same platform.
4. A short object inventory for testing:
   - One table with known column-level changes.
   - One table that did not change.
   - One dropped or added high-level object, if available.
   - One view or table with known parser lineage.
   - One object with known usage activity.
   - One object expected to have downstream impact.

For the current cycle, a one-hour parser/usage window is acceptable. Longer windows can be used later.

## Suggested Evidence to Capture

For each executed case, capture:

- Snapshot IDs used.
- Object names used.
- Expected vs actual result.
- Screenshot or short note if something looks wrong.
- Approximate response time for large-data screens.
- Defect/enhancement link if a gap is found.

---

## UC-01 - Full Extract Ingest and Snapshot Creation

**Business question:** Can SCION ingest a real customer-scale dictionary extract and create a usable metadata snapshot?

**Actor:** SCION operator / tester.

**Data needed:** one complete six-file dictionary extract.

**Flow:**

1. Open **Snapshots**.
2. Use **Import Dict Batch**.
3. Upload the six dictionary files from one full extraction run.
4. Start the import.
5. Wait for the progress checklist to complete.
6. Confirm the new snapshot appears in the snapshot list.

**Expected result:**

- Import completes successfully.
- Snapshot is finalized and selectable.
- Object counts and structural hash are populated.
- No partial snapshot is exposed to the user.
- Import progress is visible while the ingest is running.

**Acceptance signal:** the snapshot can be selected in Changes, Impact, Lineage, Usage, and other snapshot-based screens.

---

## UC-02 - Second Full Extract Ingest for Snapshot Comparison

**Business question:** Can SCION ingest a second full extract from the same platform so structural drift can be compared?

**Actor:** SCION operator / tester.

**Data needed:** second complete six-file dictionary extract from the same Teradata platform, captured later than UC-01.

**Flow:**

1. Open **Snapshots**.
2. Import the second full dictionary batch.
3. Confirm a second finalized snapshot is created.
4. Verify both snapshots are available in snapshot dropdowns.

**Expected result:**

- SCION stores the second snapshot independently.
- The second snapshot is not confused with the first snapshot.
- Both snapshots can be selected as a comparison pair.

**Acceptance signal:** the two full snapshots can be compared in **Changes**.

---

## UC-03 - Large Snapshot Diff and Change Summary

**Business question:** What changed between two full Teradata dictionary extracts?

**Actor:** data architect / release reviewer / SCION tester.

**Data needed:** two finalized full snapshots.

**Flow:**

1. Open **Changes**.
2. Select the older snapshot as **From**.
3. Select the newer snapshot as **To**.
4. Click **Run Diff**.
5. Review the summary cards.
6. Review the detailed Changes table.

**Expected result:**

- SCION produces a change list for the snapshot pair.
- Summary cards show total changes, breaking changes, and severity counts.
- Detailed table loads without browser freeze or timeout.
- Change rows include object type, object identifier, change type, severity, and breaking classification.

**Acceptance signal:** testers can use the summary to understand the overall scope of drift and the table to drill into individual changes.

---

## UC-04 - Validate Known Changed Table

**Business question:** If we know a specific table changed in Teradata, does SCION show the table and changed columns correctly?

**Actor:** technical tester with knowledge of the source extract.

**Data needed:** table name and expected changed columns.

**Flow:**

1. Open **Changes** for the selected snapshot pair.
2. In **Table View**, filter by the known table name.
3. Review all rows returned for that table.
4. Expand relevant rows to inspect before/after details.

**Expected result:**

- The table appears in the Changes table.
- Column-level changes are shown when the table exists in both snapshots.
- Each changed column has the expected change type.
- Severity and breaking flags are consistent with the change type.

**Acceptance signal:** the expected changed table/columns match what is known from the source Teradata/extract.

---

## UC-05 - Validate Known Unchanged Table

**Business question:** Does SCION avoid reporting false positives for objects that did not change?

**Actor:** technical tester.

**Data needed:** table known to be unchanged between the two extracts.

**Flow:**

1. Open **Changes** for the selected snapshot pair.
2. Filter by the known unchanged table name.
3. Review the result set.
4. Optionally switch to **Visual Diff** and inspect the object under unchanged context.

**Expected result:**

- The unchanged table does not appear as a changed row in the detailed Changes table.
- If inspected in Visual Diff, it is marked unchanged.

**Acceptance signal:** no false positive change is reported for the known unchanged table.

---

## UC-06 - High-Level Object Add/Drop Validation

**Business question:** If a table, view, macro-style object, or schema is added/dropped, does SCION report it at the correct level?

**Actor:** technical tester / data architect.

**Data needed:** known added or dropped high-level object.

**Flow:**

1. Open **Changes**.
2. Filter by the known object name.
3. Review object type and change type.
4. Expand the row to inspect before/after state.

**Expected result:**

- Added/dropped high-level objects appear as parent-level change rows.
- A dropped table/view-like object is not exploded into one row per dropped column.
- Dropped schemas appear as schema-level changes.

**Acceptance signal:** SCION reflects the structural level of the change, not noisy duplicate child changes.

---

## UC-07 - Visual Diff Structural Review

**Business question:** Can a reviewer visually understand where structural changes occurred?

**Actor:** data architect / tester.

**Data needed:** snapshot pair with at least one changed schema/table.

**Flow:**

1. Open **Changes**.
2. Run diff for the selected snapshot pair.
3. Switch from **Table View** to **Visual Diff**.
4. Expand a schema/database with changes.
5. Expand one changed table.
6. Use the Visual Diff status filters.

**Expected result:**

- Added, removed, changed, and unchanged objects are visually distinct.
- Schema summary displays changed table count as `M of N tables changed`.
- Filtering to changed statuses hides unrelated unchanged structures.

**Acceptance signal:** a tester can identify changed schemas/tables/columns without reading raw JSON.

---

## UC-08 - Breaking Change Review

**Business question:** Which changes are most likely to break downstream consumers?

**Actor:** release manager / data architect.

**Data needed:** snapshot pair with at least one breaking change, such as dropped column/table or incompatible type change.

**Flow:**

1. Open **Changes**.
2. Run diff for the selected snapshot pair.
3. Filter **Breaking** to **BREAKING**.
4. Review the severity/breaking columns.
5. Expand a breaking row and review the explanatory details.

**Expected result:**

- Breaking-only filter returns only breaking changes.
- High-risk changes are visually identifiable.
- The row provides enough context for a tester to understand why the change is risky.

**Acceptance signal:** testers can isolate the risky changes before reviewing the full change set.

---

## UC-09 - Impact Analysis for a Known Risky Change

**Business question:** If a risky object changes, can SCION show what downstream objects may be affected?

**Actor:** data architect / release reviewer.

**Data needed:** known change expected to have downstream consumers.

**Flow:**

1. Open **Changes**.
2. Locate the known risky change.
3. Expand the row.
4. Open **Impact detail**.
5. Review impacted downstream objects.
6. Open the main **Impact Analysis** page and confirm the change appears there.

**Expected result:**

- Impact detail opens for the selected change.
- Impacted objects are listed when graph/lineage data exists.
- Impact page remains usable with large-volume data.

**Acceptance signal:** the tester can move from a change to its downstream impact without manually searching other screens.

---

## UC-10 - Parser Lineage Availability in SCION

**Business question:** Does parser output from DataDNA become visible and navigable in SCION?

**Actor:** DataDNA/SCION integration tester.

**Data needed:** parser lineage JSON for known objects.

**Flow:**

1. Import parser lineage JSON for the target snapshot.
2. Open **Lineage**.
3. Select the snapshot.
4. Search for a known table or view from parser output.
5. Review upstream and downstream nodes.
6. Click a downstream node and confirm the graph refocuses.

**Expected result:**

- Parser-provided lineage is searchable.
- Known upstream/downstream relationships are shown.
- Refocusing on clicked nodes does not produce stale object or network errors.

**Acceptance signal:** lineage generated outside SCION is correctly consumed and displayed by SCION.

---

## UC-11 - Table/View Lineage Sanity Check

**Business question:** For a selected table or view, does the displayed lineage match the parser/source expectation?

**Actor:** DataDNA tester / SCION tester.

**Data needed:** one table and one view with known expected lineage from parser output.

**Flow:**

1. Open **Lineage**.
2. Search for the known table.
3. Validate visible upstream/downstream relationships.
4. Repeat with the known view.
5. Change hop depth and direction if needed.

**Expected result:**

- Table lineage is visible.
- View lineage is visible.
- Direction and depth controls help reduce or expand the graph.
- Displayed relationships align with parser output for the selected test objects.

**Acceptance signal:** at least one table and one view pass lineage sanity validation.

---

## UC-12 - Object Usage Ingest

**Business question:** Does PDCR Object Usage data load and become available for analysis?

**Actor:** SCION operator / tester.

**Data needed:** `pdcr_object_usage_<from>_<to>.dat` for the same platform.

**Flow:**

1. Open **Snapshots**.
2. Import the dictionary extract and include the Object Usage file in the same batch.
3. Wait for import completion.
4. Open **Usage**.
5. Select the imported snapshot.

**Expected result:**

- Object Usage rows are ingested.
- Usage page shows objects with query/user counters.
- Unsupported PDCR object types are skipped with counters, not silent failure.
- Re-uploading the same usage file skips duplicates.

**Acceptance signal:** usage data is visible after ingest and tied to the snapshot objects.

---

## UC-13 - Object Usage Drill-Down

**Business question:** Can a reviewer inspect usage for a specific object selected from another workflow?

**Actor:** data architect / tester.

**Data needed:** object known to have usage activity.

**Flow:**

1. Open **Changes**.
2. Locate a change for an object with expected usage.
3. Expand the row and click **Usage**.
4. Review the Usage page object drill-down card.
5. Confirm the global rankings remain visible as context.

**Expected result:**

- Usage screen opens with the object context.
- Object drill-down card shows query count, distinct users, last accessed, and criticality.
- Global usage tables are clearly labelled as global rankings, not object filters.

**Acceptance signal:** testers can move from structural change to object-specific usage context.

---

## UC-14 - Criticality Ranking

**Business question:** Can SCION help prioritize which objects matter most based on usage and structural centrality?

**Actor:** data architect / release reviewer.

**Data needed:** snapshot with graph nodes and usage data.

**Flow:**

1. Open **Usage**.
2. Select the target snapshot.
3. Review usage score, graph score, combined score, and criticality tier.
4. Pick a high criticality object and navigate to Lineage or Impact where available.

**Expected result:**

- Criticality ranking is populated.
- Scores are visible and understandable.
- High-criticality objects can be used as starting points for deeper review.

**Acceptance signal:** testers can identify a shortlist of important objects instead of reviewing every object equally.

---

## UC-15 - Timeline / History for a Known Object

**Business question:** Can SCION show how a specific object evolved across snapshots?

**Actor:** support engineer / data architect.

**Data needed:** object with change history across snapshots.

**Flow:**

1. Open **Timeline** directly, or navigate from a Changes row.
2. Search/select the known object.
3. Review the historical change events.
4. Check severity and change type over time.

**Expected result:**

- Timeline returns events for the selected object.
- Events are ordered and readable.
- The user can understand whether the object is stable or frequently changing.

**Acceptance signal:** historical object evolution can be reviewed without manually comparing many snapshot pairs.

---

## UC-16 - Alerts and Statistical Anomalies

**Business question:** Can SCION surface unusual or risky patterns without the user manually searching for them?

**Actor:** support engineer / data architect.

**Data needed:** several snapshots with enough history to compute anomaly baseline.

**Flow:**

1. Ingest enough snapshots to establish history.
2. Open **Alerts**.
3. Review proactive alerts.
4. Review **Statistical Anomalies** if present.
5. Inspect observed vs expected change volume and z-score.

**Expected result:**

- Alerts page loads successfully.
- Proactive alerts appear when relevant.
- Statistical anomalies appear when a schema has unusual change volume compared with its own history.

**Acceptance signal:** SCION can highlight suspicious change patterns without requiring the user to know the exact object in advance.

---

## UC-17 - DDL Generation for Selected Change Rows

**Business question:** Can SCION suggest DDL for a selected subset of changes?

**Actor:** data engineer / release reviewer.

**Data needed:** snapshot pair with one or more changes.

**Flow:**

1. Open **Changes** in **Table View**.
2. Filter to a target table/object if needed.
3. Select one or more change rows.
4. Click **Generate DDL**.
5. Review the generated DDL panel.

**Expected result:**

- DDL is generated for selected rows.
- If no rows are selected, DDL is generated for all loaded changes.
- Breaking changes may include TAISA warnings when TAISA is available.

**Acceptance signal:** the generated statements are tied to the selected change rows, not an unrelated global set.

---

## UC-18 - Natural-Language Review with TAISA

**Business question:** Can a user ask SCION a question about the current metadata/change context?

**Actor:** data steward / architect / tester.

**Data needed:** snapshot pair with changes and TAISA available.

**Flow:**

1. Open a screen with meaningful context, such as Changes or Impact.
2. Ask TAISA a targeted question, for example:
   - "What is the riskiest change in this snapshot pair?"
   - "Which breaking changes should I review first?"
3. Review whether the answer references real SCION objects/change IDs.

**Expected result:**

- TAISA answer is grounded in SCION metadata.
- The answer references real objects or change IDs.
- If TAISA is unavailable, SCION shows a graceful disabled/error state and the rest of the UI continues working.

**Acceptance signal:** natural-language assistance works as an aid, without becoming a blocker.

---

## UC-19 - Cross-Screen Navigation Context

**Business question:** Does SCION preserve user context when moving between review screens?

**Actor:** tester / data architect.

**Data needed:** snapshot pair with changes, lineage, impact, and usage where possible.

**Flow:**

1. Open **Changes**.
2. Expand a row.
3. Use row actions:
   - **Lineage**
   - **Timeline**
   - **Impact detail**
   - **Usage**
4. Confirm each target screen opens with the expected object/snapshot context.

**Expected result:**

- Navigation opens the right screen.
- Object context is carried where applicable.
- Changing snapshot/object clears stale errors and stale graph data.

**Acceptance signal:** users can follow an investigation path without repeatedly re-entering object names.

---

## UC-20 - Large-Volume Performance Smoke Test

**Business question:** Does SCION remain usable with realistic customer-scale metadata?

**Actor:** technical integration tester.

**Data needed:** two complete Transcend-scale extracts.

**Flow:**

1. Ingest two full extracts.
2. Run diff between the snapshots.
3. Open the following screens:
   - Snapshots
   - Changes Table View
   - Visual Diff
   - Impact Analysis
   - Lineage
   - Usage
   - Alerts
4. Record rough response times and any browser/server failures.

**Expected result:**

- Ingest completes without memory failure.
- Diff completes and produces stable results.
- First page of large result sets loads without browser freeze.
- Heavy screens remain usable enough for integration testing.

**Acceptance signal:** SCION can be tested on realistic metadata volume, not only demo data.

---

## UC-21 - Update / Refresh Deployed SCION

**Business question:** Can the deployed SCION instance be updated without rebuilding the VM or losing existing data?

**Actor:** SCION operator.

**Data needed:** deployed SCION VM with Docker Compose.

**Flow:**

1. Connect to the SCION VM.
2. Run the update script or equivalent:
   - `curl -fsSL https://raw.githubusercontent.com/GuilleAlbella/scion-deploy/main/update.sh | bash`
3. Confirm Docker pulls the latest images.
4. Confirm containers are recreated and healthy.
5. Open SCION in the browser.

**Expected result:**

- Backend and frontend images update.
- Existing SQLite volume/data is preserved.
- Containers return healthy.
- UI remains reachable.

**Acceptance signal:** a tester can update the shared test deployment and continue testing without reinstalling SCION.

---

## UC-22 - Graceful Handling of Missing or Unsupported Inputs

**Business question:** Does SCION fail clearly when the uploaded data is incomplete or out of scope?

**Actor:** tester / operator.

**Data needed:** intentionally incomplete or unsupported upload sample.

**Flow:**

1. Try an incomplete dictionary batch, or include unsupported file types.
2. Start import.
3. Review the error or skipped counters.

**Expected result:**

- SCION does not silently ingest bad data.
- Error message explains what is wrong.
- Unsupported PDCR object types are counted/skipped where applicable.
- SQL/BTEQ/KSH inputs are not accepted by SCION.

**Acceptance signal:** integration testers can distinguish valid product gaps from bad input or out-of-scope content.

---

## Not in Scope for This Cycle

- Full UAT with business end users.
- Customer acceptance testing.
- Exhaustive validation of every lineage edge.
- New feature development unless a blocker is found.
- Transformation-expression diffing. SCION stores parser expressions today, but comparing expression changes between snapshots is a future enhancement.
- Multi-tenant/multi-platform deployment validation.

