from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Iterable, List

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _safe_text(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text if text else "-"


def _money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    return f"£{amount:,.0f}"


def _split_lines(text: str, max_chars: int) -> List[str]:
    words = text.split()
    if not words:
        return ["-"]
    lines: List[str] = []
    current: List[str] = []
    for word in words:
        candidate = " ".join(current + [word])
        if len(candidate) <= max_chars:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _risk_color_hex(level: str) -> str:
    risk = level.upper()
    if risk == "LOW":
        return "#15803d"
    if risk == "MEDIUM":
        return "#b45309"
    if risk == "HIGH":
        return "#b91c1c"
    return "#374151"


def _table_styles() -> Dict[str, TableStyle]:
    return {
        "header": TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d1d5db")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
        "details": TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f9fafb")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        ),
        "claims": TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#d1d5db")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        ),
    }


def generate_fnol_pdf(fnol_data: dict) -> bytes:
    """Generate a professional, auto-paginated FNOL summary PDF and return bytes."""
    data: Dict[str, Any] = dict(fnol_data or {})

    fnol_ref = _safe_text(data.get("fnol_id") or data.get("fnol_reference"))
    customer_id = _safe_text(data.get("customer_id"))
    coverage_type = _safe_text(data.get("coverage_type"))
    incident_summary = _safe_text(data.get("incident_summary"))
    estimated_amount = _money(data.get("estimated_amount_gbp") or data.get("estimated_amount"))

    net_settlement_raw = data.get("net_settlement")
    if net_settlement_raw is None:
        try:
            net_settlement_raw = float(data.get("estimated_amount_gbp") or data.get("estimated_amount") or 0) - 250
        except (TypeError, ValueError):
            net_settlement_raw = 0.0
    net_settlement = _money(max(float(net_settlement_raw), 0.0))

    fraud_level = _safe_text(data.get("fraud_risk_level") or data.get("fraud_risk") or "LOW").upper()
    fraud_reasons_value = data.get("risk_reasons") or data.get("reasons") or []
    if isinstance(fraud_reasons_value, str):
        fraud_reasons: List[str] = [fraud_reasons_value]
    elif isinstance(fraud_reasons_value, Iterable):
        fraud_reasons = [str(x) for x in fraud_reasons_value if str(x).strip()]
    else:
        fraud_reasons = []
    if not fraud_reasons:
        fraud_reasons = ["No significant fraud indicators detected."]

    assessment_summary = _safe_text(data.get("assessment_summary"))
    policy_match_title = _safe_text(data.get("policy_match_title"))

    claims_history_payload = data.get("claims_history", {})
    claims_rows: List[Dict[str, Any]] = []
    if isinstance(claims_history_payload, dict):
        raw_claims = claims_history_payload.get("claims", [])
        if isinstance(raw_claims, list):
            for row in raw_claims:
                if isinstance(row, dict):
                    claims_rows.append(row)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        title=f"FNOL {fnol_ref}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "FnolTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        textColor=colors.HexColor("#111827"),
        alignment=TA_LEFT,
        spaceAfter=2,
    )
    subtitle_style = ParagraphStyle(
        "FnolSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        textColor=colors.HexColor("#6b7280"),
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "FnolHeading",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=11.5,
        textColor=colors.HexColor("#111827"),
        spaceBefore=10,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "FnolBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#111827"),
    )
    risk_style = ParagraphStyle(
        "FnolRisk",
        parent=body_style,
        textColor=colors.HexColor(_risk_color_hex(fraud_level)),
        fontName="Helvetica-Bold",
    )

    table_styles = _table_styles()
    story = []

    story.append(Paragraph("ClaimSense - First Notice of Loss", title_style))
    story.append(
        Paragraph(
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Reference: {fnol_ref}",
            subtitle_style,
        )
    )

    story.append(Paragraph("Claim Details", heading_style))
    details_rows = [
        ["FNOL Reference", fnol_ref],
        ["Customer ID", customer_id],
        ["Coverage Type", coverage_type],
        ["Estimated Amount", estimated_amount],
        ["Net Settlement", net_settlement],
        ["Policy Match", policy_match_title],
        ["Incident Summary", incident_summary],
    ]
    details_table = Table(details_rows, colWidths=[48 * mm, 130 * mm], repeatRows=0)
    details_table.setStyle(table_styles["details"])
    story.append(details_table)

    story.append(Paragraph("Risk Assessment", heading_style))
    risk_header = Paragraph(f"Fraud Risk Level: {fraud_level}", risk_style)
    story.append(risk_header)
    for reason in fraud_reasons:
        story.append(Paragraph(f"- {_safe_text(reason)}", body_style))

    story.append(Paragraph("Assessment Summary", heading_style))
    assessment_text = _safe_text(assessment_summary).replace("\n", "<br/>")
    story.append(Paragraph(assessment_text, body_style))

    if claims_rows:
        story.append(Paragraph("Prior Claims History", heading_style))
        claims_table_rows = [["Claim ID", "Date Filed", "Status", "Amount (GBP)"]]
        for row in claims_rows:
            claims_table_rows.append(
                [
                    _safe_text(row.get("claim_id")),
                    _safe_text(row.get("date_filed")),
                    _safe_text(row.get("status")),
                    _money(row.get("amount_claimed_gbp")),
                ]
            )
        claims_table = Table(
            claims_table_rows,
            colWidths=[34 * mm, 34 * mm, 42 * mm, 38 * mm],
            repeatRows=1,
        )
        claims_table.setStyle(table_styles["claims"])
        story.append(claims_table)

    story.append(Spacer(1, 8))
    story.append(Paragraph("Next Steps", heading_style))
    story.append(
        Paragraph(
            "A claims handler will contact you within 1 working day. "
            "Please retain all receipts, photos, and police reports.",
            body_style,
        )
    )

    doc.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
