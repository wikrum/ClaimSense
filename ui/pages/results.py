import re
from datetime import datetime
from typing import Any, Dict

from requests import RequestException
import streamlit as st

from fnol_pdf import generate_fnol_pdf
from services.api import get_customer_claims, get_fnol


def _extract_policy_title(chat_response: str) -> str:
    # Extract first policy finding bullet: "- Title (Section) ..."
    match = re.search(r"Policy Coverage Findings:\n-\s*([^\n]+)", chat_response)
    if not match:
        fallback = re.search(r"-\s*([^\n]+\[score=[^\]]+\][^\n]*)", chat_response)
        if not fallback:
            return "No clause identified"
        line = fallback.group(1).strip()
        return line[:120]
    line = match.group(1).strip()
    if line.lower().startswith("policy search error"):
        return "No clause identified"
    # keep title-ish prefix only
    return line[:120]


def _extract_fraud_risk(chat_response: str) -> str:
    match = re.search(r"risk_level\s*=\s*(LOW|MEDIUM|HIGH)", chat_response, flags=re.IGNORECASE)
    return match.group(1).upper() if match else "UNKNOWN"


def _to_currency(amount: float) -> str:
    return f"£{amount:,.0f}"


def render_results_page(results: Dict[str, Any]) -> None:
    chat_response = results.get("chat_response", "")
    form_data = results.get("form_data", {})
    customer_id = results.get("customer_id", form_data.get("customer_id", ""))
    coverage_type = form_data.get("coverage_type", "unknown")
    incident_date = form_data.get("incident_date", "-")
    estimated_amount = float(form_data.get("estimated_amount", 0.0) or 0.0)
    fnol_id = results.get("fnol_id", "")

    st.success(f"Claim submitted — reference {fnol_id or 'pending'}")

    hdr_left, hdr_right = st.columns(2)
    with hdr_left:
        st.markdown(f"**Customer ID:** {customer_id or '-'}")
        st.markdown(f"**Coverage Type:** {coverage_type}")
        st.markdown(f"**Incident Date:** {incident_date}")
    with hdr_right:
        st.markdown(f"**Estimated Amount:** {_to_currency(estimated_amount)}")
        st.markdown(f"**Submission Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    policy_title = _extract_policy_title(chat_response)
    fraud_risk = _extract_fraud_risk(chat_response)
    net_settlement = max(estimated_amount - 250.0, 0.0)

    m1, m2, m3 = st.columns(3)
    with m1:
        matched = policy_title != "No clause identified"
        st.metric("Policy matched", "Yes ✅" if matched else "No", delta="+1" if matched else "0")
        st.caption(policy_title)
    with m2:
        if fraud_risk == "LOW":
            st.metric("Fraud risk", fraud_risk, delta="-1", delta_color="inverse")
        elif fraud_risk == "HIGH":
            st.metric("Fraud risk", fraud_risk, delta="+1", delta_color="inverse")
        else:
            st.metric("Fraud risk", fraud_risk, delta="0", delta_color="off")
            st.caption("Medium risk")
    with m3:
        st.metric("Net settlement", _to_currency(net_settlement), delta="-£250 excess")

    left, right = st.columns([2, 1])
    with left:
        with st.chat_message("assistant"):
            st.markdown(chat_response or "No agent response available.")

    fnol_doc = results.get("fnol_document", {})
    claims_history = results.get("claims_history", {})

    with right:
        with st.expander("View full FNOL document", expanded=False):
            if fnol_id and (not fnol_doc or fnol_doc.get("error")):
                try:
                    fnol_doc = get_fnol(fnol_id)
                    results["fnol_document"] = fnol_doc
                    st.session_state["results"] = results
                except RequestException as exc:
                    fnol_doc = {"error": f"Failed to fetch FNOL: {exc}"}
            st.json(fnol_doc or {"info": "FNOL document not available yet."})

        with st.expander("Prior claims history", expanded=False):
            if customer_id and (not claims_history or claims_history.get("error")):
                try:
                    claims_history = get_customer_claims(customer_id)
                    results["claims_history"] = claims_history
                    st.session_state["results"] = results
                except RequestException as exc:
                    claims_history = {"error": f"Failed to fetch prior claims: {exc}"}

            claims_rows = claims_history.get("claims", []) if isinstance(claims_history, dict) else []
            if claims_rows:
                st.dataframe(claims_rows, use_container_width=True)
            else:
                st.json(claims_history or {"info": "No prior claims found."})

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Submit another claim", width="stretch"):
            st.session_state["page"] = "intake"
            st.session_state["results"] = {}
            st.session_state["session_id"] = str(uuid.uuid4())
            st.session_state["trace_events"] = []
            st.rerun()
    with b2:
        if fnol_id and (not fnol_doc or fnol_doc.get("error")):
            try:
                fnol_doc = get_fnol(fnol_id)
                results["fnol_document"] = fnol_doc
                st.session_state["results"] = results
            except RequestException:
                pass

        fnol_data = fnol_doc if isinstance(fnol_doc, dict) else {}
        fnol_data = {
            **fnol_data,
            "assessment_summary": chat_response,
            "claims_history": claims_history,
            "policy_match_title": policy_title,
            "fraud_risk_level": fnol_data.get("fraud_risk_level", fraud_risk),
            "net_settlement": net_settlement,
            "estimated_amount_gbp": fnol_data.get("estimated_amount_gbp", estimated_amount),
        }
        st.download_button(
            label="⬇ Download FNOL summary (PDF)",
            data=generate_fnol_pdf(fnol_data),
            file_name=f"FNOL_{fnol_id or 'summary'}.pdf",
            mime="application/pdf",
            use_container_width=False,
        )
