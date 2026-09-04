from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.config import SCION_TAISA_MODE
from app.llm import get_llm_provider

from .taisa_models import TaisaAnalysisRequest, TaisaAnalysisResult
from .taisa_prompts import (
    PROMPT_CONTRACT_VERSION,
    SYSTEM_PROMPT,
    SINGLE_CHANGE_PROMPT,
    BATCH_ANALYSIS_PROMPT,
    PII_SYSTEM_PROMPT,
    COLUMN_PII_BATCH_PROMPT,
)

_BREAKING_TYPES = {"TABLE_REMOVED", "COLUMN_REMOVED", "COLUMN_TYPE_CHANGED",
                   "SCHEMA_REMOVED", "TABLE_TYPE_CHANGED"}

# â"€â"€ Â§2.12 PII heuristics â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Each tuple: (substrings_to_match_in_UPPERCASE_column_name, pii_label, confidence)
# First match wins; NONE returned when nothing matches.
_PII_KEYWORD_MAP: list[tuple[list[str], str, float]] = [
    (["EMAIL", "E_MAIL", "EMAILADDRESS", "EMAIL_ADDRESS", "EMAIL_ADDR"], "EMAIL", 0.95),
    (["SSN", "SOCIAL_SECURITY", "SOCIAL_INS", "NATIONAL_ID", "NATL_ID", "TAX_ID", "TAXPAYER_ID", "TFN", "TAXPAYER"], "SSN", 0.97),
    (["DOB", "DATE_OF_BIRTH", "BIRTHDATE", "BIRTHDAY", "BIRTH_DATE", "DATEOFBIRTH", "BIRTH_DT"], "DOB", 0.97),
    (["PHONENO", "PHONE_NO", "PHONE_NUM", "PHONENUM", "MOBILE", "CELLPHONE", "CELL_PHONE", "TELEPHONE", "TEL_NO", "TELNO", "PHONE"], "PHONE", 0.90),
    (["STREETADDRESS", "STREET_ADDRESS", "STREETADDR", "STREET_ADDR", "ZIPCODE", "ZIP_CODE", "POSTALCODE", "POSTAL_CODE", "POSTCODE", "ADDRESS", "ADDR"], "ADDRESS", 0.85),
    (["FIRSTNAME", "FIRST_NAME", "LASTNAME", "LAST_NAME", "FULLNAME", "FULL_NAME", "SURNAME", "GIVENNAME", "GIVEN_NAME", "MIDDLENAME", "MIDDLE_NAME", "CUSTOMER_NAME", "CUST_NAME", "PATIENT_NAME", "EMPLOYEE_NAME", "PERSON_NAME", "CONTACT_NAME", "DISPLAY_NAME"], "NAME", 0.92),
    (["CREDITCARD", "CREDIT_CARD", "CARDNUMBER", "CARD_NUMBER", "CARDNUM", "CARD_NUM", "CVV", "CVC", "IBAN", "ACCOUNTNUMBER", "ACCOUNT_NUMBER", "ACCT_NO", "ACCTNO", "BANKACCOUNT", "BANK_ACCOUNT", "SALARY", "INCOME", "WAGES", "WAGE", "COMPENSATION", "PAYRATE", "PAY_RATE"], "FINANCIAL", 0.88),
    (["PATIENT_ID", "PATIENTID", "CUSTOMER_ID", "CUSTOMERID", "CUST_ID", "EMPLOYEE_ID", "EMPLOYEEID", "EMP_ID", "USER_ID", "USERID", "MEMBER_ID", "MEMBERID", "PERSON_ID", "PERSONID", "INDIVIDUAL_ID", "INDIV_ID"], "ID_NUMBER", 0.85),
]

_PII_VALID_LABELS = frozenset(
    {"NAME", "EMAIL", "PHONE", "SSN", "DOB", "ADDRESS", "FINANCIAL", "ID_NUMBER", "NONE"}
)


def _pii_heuristic(column_name: str) -> tuple[str, float]:
    """Return (pii_label, confidence) for a column name using keyword matching."""
    upper = column_name.upper()
    for keywords, label, confidence in _PII_KEYWORD_MAP:
        if any(kw in upper for kw in keywords):
            return label, confidence
    return "NONE", 0.85


@dataclass
class PiiClassificationResult:
    """Result of classifying one column for PII."""
    column_name: str
    pii_label: str
    confidence: float


# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
# Algorithm knowledge base — explains the logic behind every score and
# classification SCION produces. Injected into every Q&A prompt so TAISA can
# explain WHY something is HIGH/MEDIUM/LOW / BREAKING / critical, not just
# recite the value. This is a replacement for giving TAISA access to the
# actual source code (which would be unsafe and token-expensive).
# â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€
SCION_ALGORITHM_KNOWLEDGE = """SCION ALGORITHM KNOWLEDGE — How metrics are computed:

[Severity — HIGH/MEDIUM/LOW]
Assigned per change_type:
  HIGH: TABLE_REMOVED, SCHEMA_REMOVED, COLUMN_REMOVED, TABLE_TYPE_CHANGED
  MEDIUM: COLUMN_TYPE_CHANGED, COLUMN_NULLABILITY_CHANGED
  LOW: TABLE_ADDED, SCHEMA_ADDED, COLUMN_ADDED, COLUMN_POSITION_CHANGED

[Breaking — yes/no]
A change is BREAKING when it can disrupt dependent consumers (queries, views, ETLs).
Breaking change_types: TABLE_REMOVED, COLUMN_REMOVED, COLUMN_TYPE_CHANGED,
                       SCHEMA_REMOVED, TABLE_TYPE_CHANGED.
Note: Severity and Breaking are INDEPENDENT criteria. A change can be
BREAKING with MEDIUM severity (e.g. COLUMN_TYPE_CHANGED) or HIGH severity
but non-breaking (not common — HIGH types are generally breaking).

[Impact Score per change]
Formula: direct_count * 1.0 + indirect_count * 0.5 + severity_bonus
  severity_bonus: HIGH=+2.0, MEDIUM=+1.0, LOW=+0.0
  breaking_bonus: +3.0 if is_breaking else 0

[Blast Radius — weighted_score (overall risk number)]
Formula: sum(impact_score per change) + breaking_count * 2.0
Used to decide overall_risk:
  HIGH risk if weighted_score >= 15 OR breaking_count >= 3
  MEDIUM risk if weighted_score >= 5 OR breaking_count >= 1
  LOW risk otherwise

[Fragility (graph metric per node)]
Formula: in_degree / (in_degree + out_degree + 1)
Meaning: % of its connections that are incoming. High fragility = the node
mostly consumes data from elsewhere, so upstream changes break it easily.
  <5% = LOW fragility (green)
  5-10% = MEDIUM (amber)
  >=10% = HIGH (red)

[Hub node]
A node is a "hub" if in_degree + out_degree >= 5 (many connections).
Hub nodes are architecturally important — changes to them ripple further.

[Usage Score per object]
Normalized 0-1 score based on how often the object is queried:
Formula: 0.6 * (query_count / max_query_count) + 0.4 * (user_count / max_user_count)

[Graph Score per object]
Normalized 0-1 score based on graph connectivity:
Formula: (in_degree + out_degree) / max_degree_in_graph

[Combined Criticality Score]
Formula: 0.6 * usage_score + 0.4 * graph_score
Level mapping:
  HIGH if combined_score >= 0.70
  MEDIUM if combined_score >= 0.30
  LOW otherwise
Rationale: objects that are heavily used AND heavily connected are the most
critical — if they break, they cause the most damage.

[Domain (database) risk_score — per schema/database]
Formula: (breaking_count * 3 + high_severity_count * 2 + medium_count * 1
          + high_criticality_objects * 2) / (total_changes * 3)
Capped at 1.0. Level mapping:
  HIGH if risk_score >= 0.50
  MEDIUM if risk_score >= 0.25
  LOW otherwise

[Structural Stability Score (Intelligence page)]
Formula: 1.0 - min(1.0, (breaking_changes * 0.1 + high_risk_domains * 0.15))
Level mapping:
  Stable (HEALTHY) if stability_score >= 0.80
  Volatile (AT_RISK) if stability_score >= 0.50
  Highly Volatile (CRITICAL) otherwise

[Volatility Index]
Formula: total_changes / total_objects (in the analyzed snapshot)
  Low < 5% = stable structure
  Medium 5-15% = moderate change rate
  High >= 15% = heavy structural churn

When the user asks "why is X classified as Y" or "how is Z calculated",
refer to these formulas with specific numbers from the user's data above.
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract a JSON object from LLM response text."""
    # LLMs often wrap JSON in prose or markdown fences — try three strategies
    # in order of cleanliness before giving up.
    # Strategy 1: the whole response is already valid JSON.
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Strategy 2: JSON is fenced inside a ```json ... ``` block.
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Strategy 3: scrape the first plausible {...} object (supports one nesting
    # level) out of free-form prose.
    match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _heuristic_classification(change_type: str) -> str:
    """Return ``BREAKING`` or ``NON_BREAKING`` based on the change type."""
    return "BREAKING" if change_type in _BREAKING_TYPES else "NON_BREAKING"


def _heuristic_risk(change_type: str, impact_count: int) -> str:
    """Derive a risk level from the change type and number of impacts.

    Args:
        change_type: The structural change type identifier.
        impact_count: Number of impacted downstream/upstream nodes.

    Returns:
        ``HIGH``, ``MEDIUM``, or ``LOW`` risk label.
    """
    if change_type in _BREAKING_TYPES and impact_count > 2:
        return "HIGH"
    if change_type in _BREAKING_TYPES:
        return "MEDIUM"
    return "LOW"


@dataclass
class TaisaClientConfig:
    """Runtime configuration for ``TaisaClient``.

    Attributes:
        provider_name: LLM provider identifier (e.g. ``groq``).
        model_name: Logical model name advertised in responses.
        prompt_version: Prompt contract version used for requests.
    """

    provider_name: str = "groq"
    model_name: str = "taisa-production"
    prompt_version: str = PROMPT_CONTRACT_VERSION


class TaisaClient:
    """TAISA reasoning client.

    In "real" mode: sends structured prompts to the LLM and parses JSON responses.
    In "mock" mode: uses deterministic heuristics based on change type and severity.
    """

    def __init__(self, config: Optional[TaisaClientConfig] = None) -> None:
        """Initialize the client with an optional custom configuration.

        Args:
            config: Custom ``TaisaClientConfig``; defaults to the standard one.
        """
        self._config = config or TaisaClientConfig()

    @property
    def config(self) -> TaisaClientConfig:
        """Return the active ``TaisaClientConfig`` for this client."""
        return self._config

    def analyze_change(
        self,
        *,
        change_event: Dict[str, Any],
        impacts: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> TaisaAnalysisResult:
        """Analyze a single change with real LLM reasoning or heuristic fallback."""

        # â"€â"€â"€â"€ 1. Validate inputs (fail-fast before any LLM cost) â"€â"€â"€â"€
        if change_event is None:
            raise ValueError("change_event is required")
        if impacts is None:
            raise ValueError("impacts is required")
        if context is None:
            raise ValueError("context is required")

        # â"€â"€â"€â"€ 2. Build the typed request wrapper used for auditing â"€â"€â"€â"€
        request = TaisaAnalysisRequest.from_raw(
            prompt_version=self._config.prompt_version,
            change_event=change_event,
            impacts=impacts,
            context=context,
        )

        change_id = change_event.get("change_id")
        snapshot_id = context.get("snapshot_id")
        change_type = change_event.get("change_type", "")
        impacted_objects = [imp.get("object", "") for imp in impacts]

        # â"€â"€â"€â"€ 3. Render the single-change prompt (only first 10 impacted
        # objects to keep token usage bounded regardless of blast radius) â"€â"€â"€â"€
        prompt = SINGLE_CHANGE_PROMPT.format(
            change_type=change_type,
            object_identifier=change_event.get("object_identifier", ""),
            object_type=change_event.get("object_type", ""),
            before_state=json.dumps(change_event.get("before_state")),
            after_state=json.dumps(change_event.get("after_state")),
            direct_count=sum(1 for i in impacts if i.get("impact_level") == "DIRECT"),
            indirect_count=sum(1 for i in impacts if i.get("impact_level") == "INDIRECT"),
            impacted_objects=", ".join(impacted_objects[:10]) or "none",
            source_system=context.get("source_system", "unknown"),
            snapshot_time=context.get("snapshot_time", "unknown"),
        )

        # â"€â"€â"€â"€ 4. Dispatch to LLM or deterministic heuristic based on mode â"€â"€â"€â"€
        # "real" mode uses the configured LLM provider; "mock" mode uses
        # deterministic rules so tests and offline demos stay reproducible.
        if SCION_TAISA_MODE == "real":
            classification, risk_level, recommendations, explanation = (
                self._call_llm(prompt, change_type, len(impacts))
            )
            summary = "TAISA analysis executed via LLM provider."
        else:
            classification = _heuristic_classification(change_type)
            risk_level = _heuristic_risk(change_type, len(impacts))
            recommendations = self._heuristic_recommendations(change_type)
            explanation = self._heuristic_explanation(change_event, impacts)
            summary = "TAISA analysis via deterministic heuristics (mock mode)."

        return TaisaAnalysisResult(
            change_id=change_id,
            snapshot_id=snapshot_id,
            classification=classification,
            risk_level=risk_level,
            recommendations=recommendations,
            explanation=explanation,
            summary=summary,
            raw_response={
                "provider": self._config.provider_name,
                "model": self._config.model_name,
                "prompt_version": request.prompt_version,
                "mode": SCION_TAISA_MODE,
                "request": request.to_primitive(),
            },
        )

    def analyze_batch(
        self,
        *,
        changes: List[Dict[str, Any]],
        blast_radius: Dict[str, Any],
        context: Dict[str, Any],
    ) -> TaisaAnalysisResult:
        """Analyze a full diff (all changes) with LLM or heuristics."""

        changes_summary = "\n".join(
            f"  - {c.get('change_type', '?')}: {c.get('object_identifier', '?')} "
            f"[severity={c.get('severity', '?')}, breaking={c.get('is_breaking', False)}]"
            for c in changes
        )

        prompt = BATCH_ANALYSIS_PROMPT.format(
            change_count=len(changes),
            changes_summary=changes_summary,
            total_impacted=blast_radius.get("total_impacted_nodes", 0),
            max_depth=blast_radius.get("max_depth", 0),
            affected_schemas=", ".join(blast_radius.get("affected_schemas", [])) or "none",
            breaking_count=sum(1 for c in changes if c.get("is_breaking")),
            source_system=context.get("source_system", "unknown"),
            snapshot_from=context.get("snapshot_from", "?"),
            snapshot_to=context.get("snapshot_to", "?"),
        )

        breaking_count = sum(1 for c in changes if c.get("is_breaking"))
        high_count = sum(1 for c in changes if c.get("severity") == "HIGH")

        if SCION_TAISA_MODE == "real":
            # Pick the most common change_type as the "dominant" one — used
            # only for the heuristic fallback inside _call_llm if parsing fails.
            dominant = max(
                set(c.get("change_type", "") for c in changes),
                key=lambda t: sum(1 for c in changes if c.get("change_type") == t),
                default="",
            )
            classification, risk_level, recommendations, explanation = (
                self._call_llm(prompt, dominant, len(changes))
            )
            summary = "TAISA batch analysis executed via LLM provider."
        else:
            # Heuristic risk-escalation ladder for mock mode.
            if breaking_count >= 3 or high_count >= 2:
                classification, risk_level = "BREAKING", "HIGH"
            elif breaking_count >= 1:
                classification, risk_level = "BREAKING", "MEDIUM"
            else:
                classification, risk_level = "NON_BREAKING", "LOW"
            recommendations = [
                f"Review {breaking_count} breaking change(s) before deployment.",
                "Run regression tests on affected downstream objects.",
                "Validate data type compatibility in dependent views and reports.",
            ]
            explanation = (
                f"Analysis of {len(changes)} structural changes detected {breaking_count} "
                f"breaking change(s) affecting {len(blast_radius.get('affected_schemas', []))} "
                f"schema(s). Max impact depth is {blast_radius.get('max_depth', 0)}."
            )
            summary = "TAISA batch analysis via deterministic heuristics (mock mode)."

        return TaisaAnalysisResult(
            change_id=None,
            snapshot_id=context.get("snapshot_to"),
            classification=classification,
            risk_level=risk_level,
            recommendations=recommendations,
            explanation=explanation,
            summary=summary,
            raw_response={
                "provider": self._config.provider_name,
                "mode": SCION_TAISA_MODE,
                "changes_count": len(changes),
            },
        )

    def _call_llm(
        self, prompt: str, change_type: str, impact_count: int
    ) -> tuple[str, str, list[str], str]:
        """Call the LLM and parse JSON response. Falls back to heuristics."""
        try:
            provider = get_llm_provider()
            raw = provider.generate(prompt)
            # LLM may return JSON wrapped in prose — _extract_json handles that.
            parsed = _extract_json(raw)

            if parsed:
                # Each field falls back to a heuristic if the LLM omitted or
                # malformed it — we never trust the LLM to be 100% compliant.
                classification = parsed.get("classification", _heuristic_classification(change_type))
                risk_level = parsed.get("risk_level", _heuristic_risk(change_type, impact_count))
                recs = parsed.get("recommendations", [])
                if not isinstance(recs, list):
                    recs = [str(recs)]
                explanation = parsed.get("explanation", raw)
                return classification, risk_level, recs, explanation

            return (
                _heuristic_classification(change_type),
                _heuristic_risk(change_type, impact_count),
                ["Review the change manually — automated classification was inconclusive."],
                raw,
            )
        except Exception as exc:
            # Network / auth / rate-limit errors must NOT crash the request —
            # always degrade gracefully to heuristics so the endpoint stays up.
            return (
                _heuristic_classification(change_type),
                _heuristic_risk(change_type, impact_count),
                [f"LLM analysis failed ({exc}). Using heuristic classification."],
                f"Heuristic fallback: {change_type} classified based on change type rules.",
            )

    def _heuristic_recommendations(self, change_type: str) -> List[str]:
        """Return canned recommendations for a change type (mock-mode fallback)."""
        if change_type in _BREAKING_TYPES:
            return [
                "Validate all downstream dependencies before deploying.",
                "Check for data type compatibility in dependent views.",
                "Notify data consumers of the breaking change.",
            ]
        return [
            "Verify downstream reports still produce correct results.",
            "Monitor for anomalies after deployment.",
        ]

    def _heuristic_explanation(self, change_event: Dict[str, Any], impacts: List[Dict[str, Any]]) -> str:
        """Build a short rule-based explanation string for a change event."""
        ct = change_event.get("change_type", "UNKNOWN")
        obj = change_event.get("object_identifier", "unknown")
        n = len(impacts)
        if ct in _BREAKING_TYPES:
            return (
                f"The change '{ct}' on '{obj}' is classified as BREAKING because it "
                f"can disrupt dependent objects. {n} impact(s) detected. "
                f"Manual review recommended before deployment."
            )
        return (
            f"The change '{ct}' on '{obj}' is classified as NON-BREAKING. "
            f"{n} downstream impact(s) detected but structurally compatible."
        )

    # â"€â"€ Scalable context builder for Q&A â"€â"€

    def _build_scion_context(self, question: str) -> str:
        """Build a smart, bounded context from SCION data.

        Strategy for scalability:
        - ALWAYS: lightweight aggregates (counts, top-N, latest reasoning)
        - ON DEMAND: detailed rows only for objects the question mentions
        - HARD CAPS: never exceed ~50 detail rows per section

        This keeps token usage roughly constant regardless of DB size.
        """
        from sqlalchemy import select, desc, func, or_
        from sqlalchemy.orm import Session
        from app.db.engine import engine
        from app.db.models.snapshot import Snapshot
        from app.db.models.schema_snapshot import SchemaSnapshot
        from app.db.models.table_snapshot import TableSnapshot
        from app.diff.diff_models import ChangeEvent
        from app.graph.graph_models import GraphNode, GraphEdge
        from app.graph.impact_models import ImpactEvent
        from app.taisa.taisa_models import ReasoningEvent
        from app.usage.usage_models import UsageEvent, ObjectCriticality
        from app.db.models.reference import (
            TeamEntity, DepartmentEntity, UserEntity,
            ApplicationEntity, TableApplicationMapping,
        )

        q_lower = question.lower()
        # Each section becomes a block in the final prompt, separated by blank
        # lines. Ordering matters: snapshots -> inventory -> changes -> impact
        # -> graph -> usage -> criticality -> reasoning -> algorithm KB.
        sections: List[str] = []

        # Extract potential object names from the question for targeted queries
        # (anything that looks like schema.table or a known keyword). Used to
        # pull detailed rows matching what the user actually asked about.
        keywords = [w.strip("?,.'\"!") for w in question.split() if len(w) > 2]

        with Session(engine) as session:

            # â"€â"€ 1. Snapshots (always lightweight — just a count + list) â"€â"€
            snapshots = session.execute(
                select(Snapshot).order_by(Snapshot.snapshot_id)
            ).scalars().all()
            if snapshots:
                snap_lines = [
                    f"  #{s.snapshot_id}: {s.source_system}, "
                    f"{s.object_count or '?'} objects, "
                    f"{s.snapshot_time.strftime('%Y-%m-%d') if s.snapshot_time else '?'}"
                    for s in snapshots
                ]
                sections.append(f"SNAPSHOTS ({len(snapshots)}):\n" + "\n".join(snap_lines))
                latest_snap = snapshots[-1].snapshot_id
            else:
                latest_snap = None

            # â"€â"€ 2. Inventory summary (always — schemas + table counts) â"€â"€
            #
            # Even the "lightweight" path here was unbounded: at Transcend
            # scale there are 10 716 schemas, each emitting one line, for
            # ~500 KB of inventory text on every TAISA call regardless of
            # the question topic. Cap to the busiest 30 schemas + a tail
            # summary; that's enough for the LLM to reason about the shape
            # of the warehouse without flooding the prompt.
            INVENTORY_TOP_N = 30
            if latest_snap:
                # Get the schema-level table counts in one grouped query
                # rather than N+1 per-schema COUNTs.
                count_rows = session.execute(
                    select(SchemaSnapshot, func.count(TableSnapshot.table_id))
                    .outerjoin(
                        TableSnapshot,
                        TableSnapshot.schema_id == SchemaSnapshot.schema_id,
                    )
                    .where(SchemaSnapshot.snapshot_id == latest_snap)
                    .group_by(SchemaSnapshot.schema_id)
                    .order_by(desc(func.count(TableSnapshot.table_id)))
                ).all()
                # `schemas` is reused below by the inventory_words branch.
                schemas = [row[0] for row in count_rows]

                if count_rows:
                    listed = count_rows[:INVENTORY_TOP_N]
                    rest = count_rows[INVENTORY_TOP_N:]
                    inv_lines = [
                        f"  {sch.schema_name}: {tbl_count} tables/views"
                        for sch, tbl_count in listed
                    ]
                    if rest:
                        rest_total = sum(c for _, c in rest)
                        inv_lines.append(
                            f"  â€¦and {len(rest)} smaller schemas with "
                            f"{rest_total} tables/views in total"
                        )
                    sections.append(
                        f"EDW INVENTORY (snapshot #{latest_snap}, "
                        f"{len(count_rows)} schemas total):\n"
                        + "\n".join(inv_lines)
                    )

                # Only emit the expensive full-table listing when the question
                # actually concerns inventory — keyword gate keeps token usage
                # low for other topics (e.g. questions about risk/impact).
                #
                # Hard caps protect against context overrun on Transcend-class
                # data (10 716 schemas Ã— ~22 tables/schema â‰ˆ 240k rows). Before
                # the caps, any question containing "what" or "list" pulled
                # every table name into the prompt and broke the LLM call
                # (timeout + "no response" symptom).
                inventory_words = {"table", "tables", "schema", "schemas", "inventory",
                                   "view", "views", "column", "columns", "object", "objects",
                                   "list"}
                # `what` / `which` / `how many` removed — they fire on too many
                # questions that aren't actually inventory-shaped. Real
                # inventory questions almost always include one of the nouns
                # above.
                MAX_SCHEMAS_LISTED = 25
                MAX_TABLES_PER_SCHEMA = 40
                if inventory_words & set(q_lower.split()):
                    # Pick the most "interesting" schemas: those with the most
                    # tables. Cap at MAX_SCHEMAS_LISTED, summarise the tail.
                    schemas_with_count: List[tuple[Any, int]] = []
                    for sch in schemas:
                        c = session.execute(
                            select(func.count()).select_from(TableSnapshot)
                            .where(TableSnapshot.schema_id == sch.schema_id)
                        ).scalar() or 0
                        schemas_with_count.append((sch, c))
                    schemas_with_count.sort(key=lambda x: x[1], reverse=True)

                    listed = schemas_with_count[:MAX_SCHEMAS_LISTED]
                    rest = schemas_with_count[MAX_SCHEMAS_LISTED:]

                    for sch, total_tables in listed:
                        tables = session.execute(
                            select(TableSnapshot)
                            .where(TableSnapshot.schema_id == sch.schema_id)
                            .limit(MAX_TABLES_PER_SCHEMA)
                        ).scalars().all()
                        if tables:
                            tbl_names = [f"{t.table_name} ({t.object_type})" for t in tables]
                            tail = (
                                f", â€¦and {total_tables - len(tables)} more"
                                if total_tables > len(tables)
                                else ""
                            )
                            sections.append(
                                f"  {sch.schema_name} tables ({total_tables}): "
                                f"{', '.join(tbl_names)}{tail}"
                            )
                    if rest:
                        rest_total = sum(c for _, c in rest)
                        sections.append(
                            f"  â€¦and {len(rest)} smaller schemas with {rest_total} tables total "
                            f"(omitted to keep context size manageable; "
                            f"ask about a specific schema by name to see its tables)"
                        )

            # â"€â"€ 3. Changes — aggregate summary always, detail if relevant â"€â"€
            total_changes = session.execute(
                select(func.count()).select_from(ChangeEvent)
            ).scalar() or 0
            breaking_total = session.execute(
                select(func.count()).select_from(ChangeEvent)
                .where(ChangeEvent.is_breaking == True)
            ).scalar() or 0
            high_total = session.execute(
                select(func.count()).select_from(ChangeEvent)
                .where(ChangeEvent.severity == "HIGH")
            ).scalar() or 0

            sections.append(
                f"CHANGES SUMMARY: {total_changes} total, {breaking_total} breaking, {high_total} HIGH severity"
            )

            # â"€â"€ Pass 1: keyword-targeted rows (ALWAYS included, no shared cap).
            # Running a separate query per keyword guarantees that changes for
            # the specific object the user asked about are present in the
            # context even when there are thousands of high-signal (breaking /
            # HIGH) changes with lower change_ids that would otherwise fill the
            # LIMIT before reaching the relevant rows.
            detail_changes: List[Any] = []
            seen_ids: set[int] = set()
            for kw in keywords:
                if len(kw) < 5:
                    continue
                rows = session.execute(
                    select(ChangeEvent)
                    .where(ChangeEvent.object_identifier.ilike(f"%{kw}%"))
                    .order_by(ChangeEvent.change_id)
                    .limit(10)
                ).scalars().all()
                for row in rows:
                    if row.change_id not in seen_ids:
                        detail_changes.append(row)
                        seen_ids.add(row.change_id)

            # â"€â"€ Pass 2: high-signal changes fill the remaining slots.
            signal_changes = session.execute(
                select(ChangeEvent)
                .where(or_(
                    ChangeEvent.is_breaking == True,
                    ChangeEvent.severity == "HIGH",
                ))
                .order_by(ChangeEvent.snapshot_from, ChangeEvent.change_id)
                .limit(40)
            ).scalars().all()
            for c in signal_changes:
                if c.change_id not in seen_ids:
                    detail_changes.append(c)
                    seen_ids.add(c.change_id)

            # â"€â"€ Pass 3: panoramic escape hatch for broad questions.
            broad_words = {"all", "every", "changes", "changed", "change", "diff"}
            if broad_words & set(q_lower.split()):
                all_changes = session.execute(
                    select(ChangeEvent)
                    .order_by(ChangeEvent.snapshot_from, ChangeEvent.change_id)
                    .limit(50)
                ).scalars().all()
                for c in all_changes:
                    if c.change_id not in seen_ids:
                        detail_changes.append(c)
                        seen_ids.add(c.change_id)

            if detail_changes:
                ch_lines = []
                for c in detail_changes:
                    brk = "BREAKING" if c.is_breaking else "non-breaking"
                    ch_lines.append(
                        f"  #{c.change_id} [{c.snapshot_from}->{c.snapshot_to}] "
                        f"{c.change_type} on {c.object_identifier} [{c.severity or 'LOW'}, {brk}]"
                    )
                sections.append(f"CHANGE DETAILS ({len(detail_changes)} shown):\n" + "\n".join(ch_lines))

            # â"€â"€ 4. Impact — aggregate + detail for keyword-matching â"€â"€
            impact_total = session.execute(
                select(func.count()).select_from(ImpactEvent)
            ).scalar() or 0

            if impact_total:
                # Node ids alone are meaningless to an LLM — resolve them to
                # schema.object human names once and reuse the map.
                node_names: Dict[int, str] = {}
                if latest_snap:
                    for n in session.execute(
                        select(GraphNode).where(GraphNode.snapshot_id == latest_snap)
                    ).scalars().all():
                        node_names[n.node_id] = f"{n.schema_name}.{n.object_name}" if n.schema_name else n.object_name

                sections.append(f"IMPACT SUMMARY: {impact_total} impact events recorded")

                # Detail if question mentions impact/risk/blast/downstream/affected
                impact_words = {"impact", "affected", "downstream", "upstream", "blast",
                                "radius", "risk", "depth", "impacted", "dependency"}
                if impact_words & set(q_lower.split()):
                    imp_rows = session.execute(
                        select(ImpactEvent).order_by(ImpactEvent.change_id).limit(30)
                    ).scalars().all()
                    if imp_rows:
                        imp_lines = []
                        for imp in imp_rows:
                            name = node_names.get(imp.impacted_node_id, f"node:{imp.impacted_node_id}")
                            imp_lines.append(
                                f"  change #{imp.change_id} -> {name} [{imp.impact_level}, depth={imp.depth}]"
                            )
                        sections.append(f"IMPACT DETAILS ({len(imp_rows)} shown):\n" + "\n".join(imp_lines))

            # â"€â"€ 5. Graph — always aggregate â"€â"€
            if latest_snap:
                node_count = session.execute(
                    select(func.count()).select_from(GraphNode).where(GraphNode.snapshot_id == latest_snap)
                ).scalar() or 0
                edge_count = session.execute(
                    select(func.count()).select_from(GraphEdge).where(GraphEdge.snapshot_id == latest_snap)
                ).scalar() or 0
                if node_count:
                    hub_nodes = []
                    for h in session.execute(
                        select(GraphNode).where(GraphNode.snapshot_id == latest_snap).limit(50)
                    ).scalars().all():
                        m = h.node_metadata or {}
                        if m.get("is_hub"):
                            hub_nodes.append(f"{h.schema_name}.{h.object_name}")
                    hub_text = f"  Hubs: {', '.join(hub_nodes)}" if hub_nodes else ""
                    sections.append(f"GRAPH: {node_count} nodes, {edge_count} edges{hub_text}")

            # â"€â"€ 6. Usage — top 10 always â"€â"€
            usage_rows = session.execute(
                select(UsageEvent).order_by(desc(UsageEvent.query_count)).limit(10)
            ).scalars().all()
            if usage_rows:
                usage_lines = [
                    f"  {u.object_name}: {u.query_count:,} queries, {u.user_count} users"
                    for u in usage_rows
                ]
                sections.append(f"TOP USAGE:\n" + "\n".join(usage_lines))

            # â"€â"€ 7. Criticality — HIGH/MEDIUM only â"€â"€
            crit_rows = session.execute(
                select(ObjectCriticality)
                .where(ObjectCriticality.criticality_level.in_(["HIGH", "MEDIUM"]))
                .order_by(desc(ObjectCriticality.combined_score))
                .limit(10)
            ).scalars().all()
            if crit_rows:
                crit_lines = [
                    f"  {cr.object_name}: {cr.criticality_level} (combined={cr.combined_score:.0%})"
                    for cr in crit_rows
                ]
                sections.append(f"HIGH/MEDIUM CRITICALITY:\n" + "\n".join(crit_lines))

            # â"€â"€ 8. Latest reasoning â"€â"€
            reasoning_rows = session.execute(
                select(ReasoningEvent).order_by(desc(ReasoningEvent.reasoning_id)).limit(3)
            ).scalars().all()
            if reasoning_rows:
                reas_lines = []
                for r in reasoning_rows:
                    scope = f"change #{r.change_id}" if r.change_id else "batch"
                    reas_lines.append(
                        f"  [{scope}] {r.classification}/{r.risk_level}: {r.explanation[:200]}"
                    )
                sections.append(f"LATEST TAISA REASONING:\n" + "\n".join(reas_lines))

        # â"€â"€ 9. Algorithm knowledge base (static — explains HOW SCION computes things) â"€â"€


            # -- 10. §2.10 Org/team usage -- keyword-gated --
            # Only injected when the question is about who uses what. Costs ~30
            # tokens; only meaningful once reference data has been imported.
            org_words = {
                "team", "teams", "department", "org", "organization", "who",
                "app", "apps", "application", "applications", "business", "unit",
                "user", "users", "consumer", "consumers",
            }
            if org_words & set(q_lower.split()):
                team_rows = session.execute(
                    select(
                        TeamEntity.team_name,
                        DepartmentEntity.department_name,
                        func.sum(UsageEvent.query_count).label("total_queries"),
                        func.count(UserEntity.user_id.distinct()).label("user_count"),
                    )
                    .join(UserEntity, UserEntity.team_id == TeamEntity.team_id)
                    .join(UsageEvent, UsageEvent.username == UserEntity.username)
                    .outerjoin(DepartmentEntity, TeamEntity.department_id == DepartmentEntity.department_id)
                    .group_by(TeamEntity.team_name, DepartmentEntity.department_name)
                    .order_by(desc("total_queries"))
                    .limit(5)
                ).all()
                if team_rows:
                    team_lines = [
                        f"  {r.team_name}"
                        + (f" ({r.department_name})" if r.department_name else "")
                        + f": {r.total_queries:,} queries, {r.user_count} users"
                        for r in team_rows
                    ]
                    sections.append("TOP TEAMS BY USAGE:\n" + "\n".join(team_lines))

                app_rows = session.execute(
                    select(
                        ApplicationEntity.application_name,
                        func.count(TableApplicationMapping.mapping_id).label("table_count"),
                    )
                    .outerjoin(
                        TableApplicationMapping,
                        TableApplicationMapping.application_id == ApplicationEntity.application_id,
                    )
                    .group_by(ApplicationEntity.application_name)
                    .order_by(desc("table_count"))
                    .limit(5)
                ).all()
                if app_rows:
                    app_lines = [
                        f"  {r.application_name}: {r.table_count} mapped tables"
                        for r in app_rows
                    ]
                    sections.append("TOP APPLICATIONS (by table coverage):\n" + "\n".join(app_lines))
        sections.append(SCION_ALGORITHM_KNOWLEDGE)

        return "\n\n".join(sections) if sections else "No data in SCION yet."

    def answer_question(
        self,
        *,
        change_id: int,
        question: str,
        context: dict | None = None,
        history: list | None = None,
    ) -> str:
        """Answer a user question with smart, scalable SCION context.

        Builds a bounded context by reading aggregates from the DB and only
        fetching detailed rows for objects/topics relevant to the question.
        Includes conversation history so TAISA can follow multi-turn dialogue.
        Token usage stays roughly constant regardless of database size.
        """
        provider = get_llm_provider()
        scion_context = self._build_scion_context(question)

        # Defensive cap on the assembled SCION context. Per-section caps
        # already keep things bounded, but if a future section is added
        # without proper limits — or if one of the existing caps is
        # accidentally widened — this guards the LLM call from a runaway
        # prompt that times out or overflows the model context window.
        # 80 000 chars â‰ˆ 20k-25k tokens for English/SQL-shaped text,
        # which leaves plenty of headroom in llama-4-scout's 131k window
        # for the question + history + system prompt + the model's reply.
        _MAX_CONTEXT_CHARS = 80_000
        if len(scion_context) > _MAX_CONTEXT_CHARS:
            scion_context = (
                scion_context[:_MAX_CONTEXT_CHARS]
                + "\n\n[context truncated to keep prompt size manageable; "
                "ask a more specific question to surface omitted detail]"
            )

        # Only the last 10 turns are kept: enough to preserve short-term
        # references ("be more specific", "and the second one?") without
        # letting history dominate the prompt window.
        history_block = ""
        if history:
            recent = history[-10:]
            lines = []
            for msg in recent:
                role = "User" if msg.get("role") == "user" else "TAISA"
                lines.append(f"{role}: {msg.get('text', '')}")
            history_block = "\n".join(lines) + "\n"

        qa_prompt = (
            "You are TAISA, the AI reasoning engine inside SCION (Structural Change Intelligence "
            "& Observability Node) built by Teradata. You have full access to SCION's data, shown below.\n\n"
            "Rules:\n"
            "- Answer in the SAME LANGUAGE the user writes in. If they write Spanish, answer in Spanish.\n"
            "- Answer in plain, conversational language.\n"
            "- Be SPECIFIC: name actual tables, columns, schemas, change IDs when relevant.\n"
            "- Do NOT respond with JSON.\n"
            "- Do NOT dump all the data back. Answer the question directly and concisely.\n"
            "- If the user asks about something not in the data, say so.\n"
            "- You have the conversation history below. Use it to understand context "
            "(e.g. 'be more specific' refers to your last answer).\n\n"
            f"=== SCION DATA ===\n\n"
            f"{scion_context}\n\n"
            f"=== END DATA ===\n\n"
        )

        if history_block:
            qa_prompt += f"=== CONVERSATION HISTORY ===\n{history_block}=== END HISTORY ===\n\n"

        qa_prompt += f"User: {question}\n\nTAISA:\n"

        return provider.generate(qa_prompt)

    # â"€â"€ Â§2.12 PII classification â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€â"€

    def classify_column_pii_batch(
        self,
        *,
        table_name: str,
        schema_name: str,
        columns: List[Dict[str, Any]],
    ) -> List["PiiClassificationResult"]:
        """Classify a list of columns for PII using TAISA.

        Args:
            table_name: Name of the table the columns belong to.
            schema_name: Schema/database name.
            columns: List of dicts with keys ``column_name`` and ``data_type``.

        Returns:
            One ``PiiClassificationResult`` per input column, in the same order.
        """
        if SCION_TAISA_MODE == "real":
            return self._classify_pii_llm(schema_name, table_name, columns)
        return self._classify_pii_heuristic(columns)

    def _classify_pii_heuristic(
        self, columns: List[Dict[str, Any]]
    ) -> List["PiiClassificationResult"]:
        results = []
        for col in columns:
            label, confidence = _pii_heuristic(col["column_name"])
            results.append(PiiClassificationResult(
                column_name=col["column_name"],
                pii_label=label,
                confidence=confidence,
            ))
        return results

    def _classify_pii_llm(
        self,
        schema_name: str,
        table_name: str,
        columns: List[Dict[str, Any]],
    ) -> List["PiiClassificationResult"]:
        """LLM-backed PII classification, batching up to 20 columns per call."""
        results: List["PiiClassificationResult"] = []
        BATCH = 20
        for i in range(0, len(columns), BATCH):
            batch = columns[i : i + BATCH]
            cols_list = "\n".join(
                f"- {c['column_name']} Â· {c['data_type']}" for c in batch
            )
            prompt = (
                PII_SYSTEM_PROMPT
                + "\n\n"
                + COLUMN_PII_BATCH_PROMPT.format(
                    schema_name=schema_name,
                    table_name=table_name,
                    columns_list=cols_list,
                )
            )
            try:
                provider = get_llm_provider()
                raw = provider.generate(prompt)
                parsed = _extract_json(raw)
                batch_results = parsed.get("results", {}) if parsed else {}

                for col in batch:
                    entry = batch_results.get(col["column_name"]) if isinstance(batch_results, dict) else None
                    if entry and isinstance(entry, dict):
                        label = entry.get("pii_label", "NONE")
                        if label not in _PII_VALID_LABELS:
                            label = "NONE"
                        confidence = float(entry.get("confidence", 0.5))
                        confidence = max(0.0, min(1.0, confidence))
                    else:
                        label, confidence = _pii_heuristic(col["column_name"])
                    results.append(PiiClassificationResult(
                        column_name=col["column_name"],
                        pii_label=label,
                        confidence=confidence,
                    ))
            except Exception:
                results.extend(self._classify_pii_heuristic(batch))
        return results
