import uuid
from datetime import date
import re
from typing import Any, Dict

from requests import RequestException, Timeout
import streamlit as st

from services.api import post_chat


def _build_natural_language_message(form_data: Dict[str, Any]) -> str:
    police_report = "yes" if form_data["police_report"] else "no"
    documents_ready = "yes" if form_data["documents_ready"] else "no"
    return (
        f"Customer ID {form_data['customer_id']}. "
        f"Claimant name {form_data['claimant_name']}. "
        f"Coverage type {form_data['coverage_type']}. "
        f"Incident date {form_data['incident_date'].isoformat()}. "
        f"Incident description: {form_data['incident_desc']}. "
        f"Estimated amount GBP {int(form_data['estimated_amount'])}. "
        f"Police report obtained: {police_report}. "
        f"Supporting documents available: {documents_ready}."
    )


def _is_valid_customer_id(customer_id: str) -> bool:
    return bool(re.match(r"^CUST\d{4,}$", customer_id.strip().upper()))


def _navigate_to_results() -> None:
    st.session_state["page"] = "results"


def _collect_form_data() -> Dict[str, Any]:
    customer_id = st.session_state.get("customer_id_input", "").strip().upper()
    claimant_name = st.session_state.get("claimant_name_input", "").strip()
    incident_date = st.session_state.get("incident_date_input", date.today())
    coverage_type = st.session_state.get("coverage_type_input", "motor")
    incident_desc = st.session_state.get("incident_desc_input", "").strip()
    estimated_amount = float(st.session_state.get("estimated_amount_input", 0.0) or 0.0)
    police_report = bool(st.session_state.get("police_report_input", False))
    documents_ready = bool(st.session_state.get("documents_ready_input", False))

    return {
        "customer_id": customer_id,
        "claimant_name": claimant_name,
        "incident_date": incident_date,
        "coverage_type": coverage_type,
        "incident_desc": incident_desc,
        "estimated_amount": estimated_amount,
        "police_report": police_report,
        "documents_ready": documents_ready,
    }


def _submit_claim_form(form_data: Dict[str, Any]) -> None:
    message = _build_natural_language_message(form_data)

    try:
        st.session_state["session_id"] = str(uuid.uuid4())
        with st.spinner("ClaimSense agents are processing your claim..."):
            chat_data = post_chat(st.session_state["session_id"], message)

        response_text = chat_data.get("response", chat_data.get("reply", ""))
        trace_events = chat_data.get("trace") or []
        if trace_events:
            st.session_state["trace_events"] = trace_events
        fnol_match = re.search(r"FNOL-\d{8}-\d{6}", response_text)
        fnol_id = fnol_match.group(0) if fnol_match else ""
        st.session_state["results"] = {
            "form_data": form_data,
            "chat_response": response_text,
            "customer_id": form_data["customer_id"],
            "fnol_id": fnol_id,
        }
        st.session_state["demo_submission_pending"] = False
        _navigate_to_results()
        st.rerun()
    except Timeout:
        st.error(
            "ClaimSense agents are taking longer than expected. "
            "Please wait and try submitting again in a moment."
        )
    except RequestException as exc:
        st.error(f"Backend request failed: {exc}")


def render_intake_page() -> None:
    st.header("Claim Intake Form")
    st.caption("Step 1 of 2: Collect incident details")

    left_col, right_col = st.columns([2, 1], gap="large")

    with left_col:
        customer_id = st.text_input(
            "Customer ID",
            placeholder="e.g. CUST1005",
            key="customer_id_input",
        )
        claimant_name = st.text_input(
            "Claimant Name",
            placeholder="Full name",
            key="claimant_name_input",
        )
        incident_date = st.date_input(
            "Incident Date",
            max_value=date.today(),
            key="incident_date_input",
        )
        coverage_type = st.selectbox(
            "Coverage Type",
            options=["motor", "home", "health", "travel"],
            key="coverage_type_input",
        )
        incident_desc = st.text_area(
            "Describe what happened",
            height=120,
            key="incident_desc_input",
        )
        estimated_amount = st.number_input(
            "Estimated Amount",
            min_value=0.0,
            step=100.0,
            format="%.0f",
            help="Amount in GBP (£)",
            key="estimated_amount_input",
        )
        police_report = st.checkbox("Police report obtained?", key="police_report_input")
        documents_ready = st.checkbox(
            "Supporting documents available?",
            key="documents_ready_input",
        )

        submitted = st.button("Submit Claim Intake", type="primary", width="stretch")

    with right_col:
        st.subheader("Helper Tips")
        st.info(
            "Use customer ID format CUST####."
            "\n\nWrite a clear incident summary with location, time, and damage."
            "\n\nAdd estimated amount and evidence readiness for faster FNOL processing."
        )

    if st.session_state.get("demo_submission_pending"):
        form_data = _collect_form_data()
        customer_id_clean = form_data["customer_id"]
        incident_desc_clean = form_data["incident_desc"]

        if not customer_id_clean:
            st.error("customer_id is required.")
            return

        if not _is_valid_customer_id(customer_id_clean):
            st.error("customer_id must start with CUST.")
            return

        if len(incident_desc_clean) <= 20:
            st.error("incident_desc must be longer than 20 characters.")
            return

        _submit_claim_form(form_data)
        return

    if not submitted:
        return

    form_data = _collect_form_data()
    customer_id_clean = form_data["customer_id"]
    incident_desc_clean = form_data["incident_desc"]

    if not customer_id_clean:
        st.error("customer_id is required.")
        return

    if not _is_valid_customer_id(customer_id_clean):
        st.error("customer_id must start with CUST.")
        return

    if len(incident_desc_clean) <= 20:
        st.error("incident_desc must be longer than 20 characters.")
        return

    _submit_claim_form(form_data)
