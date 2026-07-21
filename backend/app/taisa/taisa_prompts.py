"""Prompt templates for TAISA reasoning engine.

All prompts instruct the LLM to respond in valid JSON so that the
TaisaClient can parse the response programmatically.
"""

from __future__ import annotations

# Stamped on every persisted ReasoningEvent so historical analyses can be
# replayed against the exact prompt contract that produced them. Bump this
# string whenever the prompt wording or JSON schema changes.
PROMPT_CONTRACT_VERSION = "8.0-production"
DEFAULT_PROMPT_VERSION = PROMPT_CONTRACT_VERSION

# Strict JSON-only contract — the client parses the response with
# json.loads, so any prose or markdown fence outside the JSON object breaks
# the pipeline. The four-key schema is load-bearing for the ReasoningEvent.
SYSTEM_PROMPT = (
    "You are TAISA (Teradata AI System Advisor), an expert database structural "
    "change analyst. You evaluate changes to data warehouse schemas, tables, and "
    "columns and provide risk assessments.\n\n"
    "You MUST respond ONLY with valid JSON (no markdown, no explanation outside JSON).\n"
    "The JSON must have these exact keys:\n"
    "- classification: one of BREAKING, NON_BREAKING, or INFORMATIONAL\n"
    "- risk_level: one of LOW, MEDIUM, HIGH, or CRITICAL\n"
    "- recommendations: array of 1-3 short actionable recommendation strings\n"
    "- explanation: a 2-4 sentence explanation of the risk assessment\n"
)

SINGLE_CHANGE_PROMPT = """Analyze this database structural change:

Change type: {change_type}
Object: {object_identifier}
Object type: {object_type}
Before state: {before_state}
After state: {after_state}

Impact analysis:
- Direct impacts: {direct_count}
- Indirect impacts: {indirect_count}
- Impacted objects: {impacted_objects}

Context:
- Source system: {source_system}
- Snapshot time: {snapshot_time}

Respond with JSON containing: classification, risk_level, recommendations, explanation."""

# ── §2.12 PII Classification prompts ─────────────────────────────────────────

PII_SYSTEM_PROMPT = (
    "You are a data privacy analyst. Classify database columns as PII "
    "(personally identifiable information) based on their name and data type.\n\n"
    "You MUST respond ONLY with valid JSON (no markdown, no explanation outside JSON).\n"
    "The JSON must have exactly this structure:\n"
    '  {"results": {"COLUMN_NAME": {"pii_label": "...", "confidence": 0.0}, ...}}\n\n'
    "Valid pii_label values:\n"
    "  NAME       — full name, first name, last name, display name\n"
    "  EMAIL      — email address\n"
    "  PHONE      — phone number, mobile, fax\n"
    "  SSN        — social security number, national identity number, tax file number\n"
    "  DOB        — date of birth, birthdate, age field\n"
    "  ADDRESS    — street address, city, state, zip/postal code\n"
    "  FINANCIAL  — credit card, bank account number, salary, income, balance\n"
    "  ID_NUMBER  — customer ID, user ID, employee ID, patient ID that identifies a person\n"
    "  NONE       — not PII; technical or business metadata\n"
)

COLUMN_PII_BATCH_PROMPT = """Classify these database columns for PII:

Table: {schema_name}.{table_name}

Columns (name · data_type):
{columns_list}

Respond ONLY with JSON: {{"results": {{"COLUMN_NAME": {{"pii_label": "...", "confidence": 0.0}}, ...}}}}"""

# ──────────────────────────────────────────────────────────────────────────────

BATCH_ANALYSIS_PROMPT = """Analyze ALL these database structural changes detected between two snapshots:

Changes ({change_count} total):
{changes_summary}

Blast radius:
- Total impacted nodes: {total_impacted}
- Max depth: {max_depth}
- Affected schemas: {affected_schemas}
- Breaking changes: {breaking_count}

Context:
- Source system: {source_system}
- Snapshot from: #{snapshot_from}
- Snapshot to: #{snapshot_to}

Provide an OVERALL risk assessment for the entire set of changes.
Respond with JSON containing: classification, risk_level, recommendations, explanation."""
