import uuid
from datetime import date

import requests

import streamlit as st

from pages.intake import render_intake_page
from pages.results import render_results_page
from services.api import API_BASE_URL


st.set_page_config(page_title="ClaimSense", page_icon="🛡️", layout="wide")

# Route state (only Streamlit session state)
if "page" not in st.session_state:
    st.session_state["page"] = "intake"

if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

if "results" not in st.session_state:
    st.session_state["results"] = {}

if "trace_events" not in st.session_state:
    st.session_state["trace_events"] = []


def _ensure_intake_defaults() -> None:
    defaults = {
        "customer_id_input": "",
        "claimant_name_input": "",
        "incident_date_input": date.today(),
        "coverage_type_input": "motor",
        "incident_desc_input": "",
        "estimated_amount_input": 0.0,
        "police_report_input": False,
        "documents_ready_input": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_data(ttl=30)
def _get_system_health() -> dict:
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        response.raise_for_status()
        return {"ok": True, "payload": response.json()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _set_demo_scenario(
    customer_id: str,
    coverage_type: str,
    incident_desc: str,
    estimated_amount: float,
    claimant_name: str = "Demo Claimant",
) -> None:
    st.session_state["customer_id_input"] = customer_id
    st.session_state["claimant_name_input"] = claimant_name
    st.session_state["incident_date_input"] = date.today()
    st.session_state["coverage_type_input"] = coverage_type
    st.session_state["incident_desc_input"] = incident_desc
    st.session_state["estimated_amount_input"] = float(estimated_amount)
    st.session_state["police_report_input"] = True
    st.session_state["documents_ready_input"] = True
    st.session_state["page"] = "intake"
    st.rerun()


_ensure_intake_defaults()

with st.sidebar:
    st.markdown("## 🛡️ ClaimSense")
    st.caption("UK Insurance Claims AI")
    st.divider()

    st.markdown("### System status")
    health = _get_system_health()
    is_ok = bool(health.get("ok"))
    dot = "🟢" if is_ok else "🔴"

    if is_ok:
        st.markdown(f"{dot} MongoDB Atlas: Connected")
        st.markdown(f"{dot} Voyage AI: voyage-4-lite")
        st.markdown(f"{dot} AWS Bedrock: Claude Sonnet")
        st.markdown(f"{dot} Agents: 3 active")
    else:
        st.markdown(f"{dot} MongoDB Atlas: Disconnected")
        st.markdown(f"{dot} Voyage AI: Unavailable")
        st.markdown(f"{dot} AWS Bedrock: Unavailable")
        st.markdown(f"{dot} Agents: Unavailable")

    st.divider()

    st.markdown("### Quick demo scenarios")

    if st.button("🚗 Motor collision", use_container_width=True):
        _set_demo_scenario(
            "CUST1005",
            "motor",
            "rear-end collision on M25, ABS failed, significant front damage, £8,500 repair quote from BMW dealership",
            8500,
        )

    if st.button("🏠 Home burglary", use_container_width=True):
        _set_demo_scenario(
            "CUST1012",
            "home",
            "returned home to find back door forced open, laptop MacBook Pro, Rolex watch, and £800 cash stolen, police called",
            9800,
        )

    if st.button("🏥 Health claim", use_container_width=True):
        _set_demo_scenario(
            "CUST1021",
            "health",
            "admitted to Spire Hospital for emergency appendectomy, 2 night stay, surgeon and anaesthetist fees, total bill £4,200",
            4200,
        )

    with st.expander("Agent trace log", expanded=False):
        color_by_tag = {
            "sys": "#6b7280",
            "llm": "#2563eb",
            "tool": "#7c3aed",
            "mongo": "#16a34a",
        }

        trace_events = st.session_state.get("trace_events", [])[-15:]
        if not trace_events:
            st.caption("No trace events yet.")
        else:
            for event in trace_events:
                tag = str(event.get("tag", "sys")).lower()
                text = str(event.get("text", ""))
                timestamp = str(event.get("timestamp", ""))
                color = color_by_tag.get(tag, "#6b7280")
                st.markdown(
                    (
                        f"<div style='margin-bottom:6px;'>"
                        f"<span style='color:{color};font-weight:600;'>[{tag}]</span> "
                        f"<span style='color:{color};'>{text}</span> "
                        f"<span style='color:#9ca3af;'>({timestamp})</span>"
                        f"</div>"
                    ),
                    unsafe_allow_html=True,
                )

        if st.button("Clear trace", use_container_width=True):
            st.session_state["trace_events"] = []
            st.rerun()


st.title("ClaimSense")
st.caption("UK insurance claims multi-agent assistant")

if st.session_state["page"] == "intake":
    render_intake_page()

else:
    results = st.session_state.get("results", {})
    render_results_page(results)
