from __future__ import annotations

"""Report Generation API (v1).

Generates an executive HTML report combining diff, impact, and TAISA reasoning.
"""

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import engine
from app.diff.diff_models import ChangeEvent


router = APIRouter(prefix="/report", tags=["report"])


# The report is returned as a standalone, fully self-contained HTML document
# (inline CSS, no external assets) so the user can save it, email it, or open
# it offline. Teradata brand colours (#00233C navy, #F37440 orange) are hard-
# coded to keep presentation consistent across deployments.
def _build_html_report(
    snapshot_from: int,
    snapshot_to: int,
    changes: List[Dict[str, Any]],
    blast_radius: Dict[str, Any] | None,
    reasoning: Dict[str, Any] | None,
) -> str:
    """Build a standalone HTML report."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Summary counts
    total = len(changes)
    breaking = sum(1 for c in changes if c.get("is_breaking"))
    high = sum(1 for c in changes if c.get("severity") == "HIGH")
    medium = sum(1 for c in changes if c.get("severity") == "MEDIUM")
    low = sum(1 for c in changes if c.get("severity") == "LOW")

    # Blast radius info
    br_nodes = blast_radius.get("total_impacted_nodes", 0) if blast_radius else 0
    br_depth = blast_radius.get("max_depth", 0) if blast_radius else 0
    br_score = blast_radius.get("weighted_score", 0) if blast_radius else 0
    br_schemas = blast_radius.get("affected_schemas", []) if blast_radius else []
    overall_risk = "N/A"
    if blast_radius and "summary" in blast_radius:
        overall_risk = blast_radius["summary"].get("overall_risk", "N/A")
    elif blast_radius:
        overall_risk = blast_radius.get("overall_risk", "N/A")

    # TAISA reasoning
    taisa_class = reasoning.get("classification", "N/A") if reasoning else "N/A"
    taisa_risk = reasoning.get("risk_level", "N/A") if reasoning else "N/A"
    taisa_recs = reasoning.get("recommendations", []) if reasoning else []
    taisa_explanation = reasoning.get("explanation", "") if reasoning else ""

    _risk_colors = {"HIGH": "#DC2626", "MEDIUM": "#F59E0B", "LOW": "#16A34A", "CRITICAL": "#7C2D12"}
    risk_color = _risk_colors.get(str(overall_risk), "#7C8185")
    taisa_risk_color = _risk_colors.get(str(taisa_risk), "#7C8185")

    # Build changes table rows
    change_rows = ""
    for c in changes:
        sev = c.get("severity", "LOW")
        sev_color = {"HIGH": "#DC2626", "MEDIUM": "#F59E0B", "LOW": "#16A34A"}.get(sev, "#7C8185")
        brk = "YES" if c.get("is_breaking") else ""
        change_rows += f"""<tr>
            <td>{c.get('change_id','')}</td>
            <td><code>{c.get('object_identifier','')}</code></td>
            <td>{c.get('change_type','')}</td>
            <td style="color:{sev_color};font-weight:bold">{sev}</td>
            <td style="color:#DC2626;font-weight:bold">{brk}</td>
        </tr>"""

    recs_html = "".join(f"<li>{r}</li>" for r in taisa_recs) if taisa_recs else "<li>No recommendations available</li>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SCION Impact Report — Snapshot #{snapshot_from} â†’ #{snapshot_to}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #1a1a2e; }}
  .header {{ background: #00233C; color: white; padding: 32px 40px; }}
  .header h1 {{ font-size: 24px; font-weight: 300; letter-spacing: 2px; }}
  .header .brand {{ color: #F37440; font-weight: bold; font-size: 12px; letter-spacing: 3px; margin-bottom: 4px; }}
  .header .meta {{ margin-top: 8px; font-size: 13px; opacity: 0.7; }}
  .content {{ max-width: 900px; margin: 24px auto; padding: 0 20px; }}
  .card {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 24px; margin-bottom: 20px; }}
  .card h2 {{ font-size: 16px; color: #00233C; margin-bottom: 16px; border-bottom: 2px solid #F37440; padding-bottom: 8px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; }}
  .kpi {{ text-align: center; padding: 16px; background: #f8f9fa; border-radius: 8px; }}
  .kpi .value {{ font-size: 28px; font-weight: bold; }}
  .kpi .label {{ font-size: 11px; color: #7C8185; margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #00233C; color: white; padding: 10px 12px; text-align: left; font-weight: 500; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #f8f9fa; }}
  code {{ background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 12px; }}
  .risk-badge {{ display: inline-block; padding: 4px 16px; border-radius: 20px; color: white; font-weight: bold; font-size: 14px; }}
  .tag {{ display: inline-block; background: #e8edf2; color: #00233C; padding: 2px 8px; border-radius: 4px; font-size: 11px; margin: 2px; }}
  .rec-list {{ padding-left: 20px; }}
  .rec-list li {{ margin-bottom: 6px; line-height: 1.5; }}
  .footer {{ text-align: center; padding: 20px; font-size: 11px; color: #7C8185; }}
  @media print {{ body {{ background: white; }} .content {{ margin: 0; }} }}
</style>
</head>
<body>
<div class="header">
    <div class="brand">TERADATA — PROJECT SCION</div>
    <h1>Impact Comparison Report</h1>
    <div class="meta">Snapshot #{snapshot_from} â†’ #{snapshot_to} &nbsp;|&nbsp; Generated: {now}</div>
</div>
<div class="content">
    <!-- Executive Summary -->
    <div class="card">
        <h2>Executive Summary</h2>
        <div style="text-align:center;margin-bottom:16px">
            <span class="risk-badge" style="background:{risk_color}">{overall_risk} RISK</span>
        </div>
        <div class="kpi-grid">
            <div class="kpi"><div class="value" style="color:#00233C">{total}</div><div class="label">Total Changes</div></div>
            <div class="kpi"><div class="value" style="color:#DC2626">{breaking}</div><div class="label">Breaking</div></div>
            <div class="kpi"><div class="value" style="color:#DC2626">{high}</div><div class="label">High Severity</div></div>
            <div class="kpi"><div class="value" style="color:#F59E0B">{medium}</div><div class="label">Medium</div></div>
            <div class="kpi"><div class="value" style="color:#16A34A">{low}</div><div class="label">Low</div></div>
        </div>
    </div>

    <!-- Blast Radius -->
    <div class="card">
        <h2>Blast Radius</h2>
        <div class="kpi-grid">
            <div class="kpi"><div class="value" style="color:#2563EB">{br_nodes}</div><div class="label">Impacted Nodes</div></div>
            <div class="kpi"><div class="value" style="color:#00233C">{br_depth}</div><div class="label">Max Depth</div></div>
            <div class="kpi"><div class="value" style="color:#F37440">{br_score:.1f}</div><div class="label">Impact Score</div></div>
        </div>
        {"<div style='margin-top:12px'><strong style='font-size:12px;color:#7C8185'>Affected Schemas:</strong> " + " ".join(f'<span class="tag">{s}</span>' for s in br_schemas) + "</div>" if br_schemas else ""}
    </div>

    <!-- TAISA AI Assessment -->
    <div class="card">
        <h2>TAISA AI Assessment</h2>
        <div style="margin-bottom:12px">
            <strong>Classification:</strong> {taisa_class} &nbsp;&nbsp;
            <strong>Risk Level:</strong> <span style="color:{taisa_risk_color}">{taisa_risk}</span>
        </div>
        {f'<div style="margin-bottom:12px;line-height:1.6;font-size:13px">{taisa_explanation}</div>' if taisa_explanation else ''}
        <strong>Recommendations:</strong>
        <ul class="rec-list">{recs_html}</ul>
    </div>

    <!-- Detailed Changes -->
    <div class="card">
        <h2>Detected Changes ({total})</h2>
        <table>
            <thead><tr><th>ID</th><th>Object</th><th>Change Type</th><th>Severity</th><th>Breaking</th></tr></thead>
            <tbody>{change_rows}</tbody>
        </table>
    </div>
</div>
<div class="footer">
    SCION — Structural Change Intelligence &amp; Observability Node &nbsp;|&nbsp; Teradata Corporation &nbsp;|&nbsp; BETA v1.00.00
</div>
</body>
</html>"""
    return html


@router.get(
    "/{snapshot_from}/{snapshot_to}",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
)
def generate_report(snapshot_from: int, snapshot_to: int) -> str:
    """Generate a standalone HTML executive report."""

    from app.db.models.snapshot import Snapshot

    # Load changes
    with Session(engine) as session:
        all_snaps = session.execute(
            select(Snapshot.snapshot_id)
            .where(Snapshot.snapshot_id >= snapshot_from, Snapshot.snapshot_id <= snapshot_to)
            .order_by(Snapshot.snapshot_id)
        ).scalars().all()

    pairs = []
    if len(all_snaps) >= 2:
        for i in range(len(all_snaps) - 1):
            pairs.append((all_snaps[i], all_snaps[i + 1]))
    else:
        pairs = [(snapshot_from, snapshot_to)]

    with Session(engine) as session:
        rows = []
        for sf, st in pairs:
            pair_rows = session.query(ChangeEvent).filter(
                ChangeEvent.snapshot_from == sf, ChangeEvent.snapshot_to == st
            ).all()
            rows.extend(pair_rows)

    changes = []
    for r in rows:
        changes.append({
            "change_id": r.change_id,
            "object_identifier": r.object_identifier,
            "change_type": r.change_type,
            "severity": r.severity or "LOW",
            "is_breaking": r.is_breaking or False,
        })

    # Blast radius and TAISA reasoning are best-effort — if either engine is
    # stopped or fails, the report still renders with the diff section so the
    # user at least gets the raw change list.
    blast_radius = None
    try:
        from app.graph.blast_radius import compute_batch_impact
        from app.engine_registry import get_engine_states
        if get_engine_states().get("graph_ready"):
            result = compute_batch_impact(snapshot_from, snapshot_to)
            d = result.to_dict()
            blast_radius = {**d.get("blast_radius", {}), "summary": d.get("summary", {})}
    except Exception:
        pass

    # Try to get TAISA reasoning
    reasoning = None
    try:
        from app.engine_registry import get_engine_states, get_taisa_client
        if get_engine_states().get("taisa_ready"):
            taisa = get_taisa_client()
            change_dicts = [
                {
                    "object_type": r.object_type,
                    "object_identifier": r.object_identifier,
                    "change_type": r.change_type,
                    "severity": r.severity,
                    "is_breaking": r.is_breaking,
                }
                for r in rows
            ]
            br_dict = blast_radius or {}
            result = taisa.analyze_batch(
                changes=change_dicts,
                blast_radius=br_dict,
                context={"source_system": "report", "snapshot_time": datetime.utcnow().isoformat()},
            )
            reasoning = {
                "classification": result.classification,
                "risk_level": result.risk_level,
                "recommendations": result.recommendations,
                "explanation": result.explanation,
            }
    except Exception:
        pass

    return _build_html_report(snapshot_from, snapshot_to, changes, blast_radius, reasoning)
