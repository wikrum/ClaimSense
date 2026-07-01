import json
import re
from datetime import datetime
from typing import TypedDict
from concurrent.futures import ThreadPoolExecutor, as_completed

from langgraph.graph import END, START, StateGraph

from agents.intake_agent import IntakeState, run_intake_agent
from tools.claims_lookup import lookup_customer_claims_history
from tools.fnol_writer import submit_fnol
from tools.fraud_score import assess_fraud_risk
from tools.policy_search import search_policy_clauses


class ClaimState(TypedDict, total=False):
    user_query: str
    claim_id: str
    route: str
    response: str
    customer_id: str
    coverage_type: str
    incident_description: str
    incident_summary: str
    intake_complete: bool
    assessment_complete: bool
    fnol_submitted: bool
    fraud_risk_level: str
    estimated_amount_gbp: float
    trace_events: list[dict]


def _append_trace(state: ClaimState, tag: str, text: str) -> ClaimState:
    trace_events = list(state.get("trace_events", []))
    trace_events.append(
        {
            "tag": tag,
            "text": text,
            "timestamp": datetime.utcnow().strftime("%H:%M:%S"),
        }
    )
    state["trace_events"] = trace_events
    return state


def assessment_agent(state: ClaimState) -> ClaimState:
    _append_trace(state, "agent", "Starting assessment stage")
    customer_id = state.get("customer_id", "")
    coverage_type = state.get("coverage_type", "")
    incident_description = state.get("incident_description", "") or state.get("user_query", "")
    claimed_amount = state.get("estimated_amount_gbp", 0.0) or _extract_amount_gbp(incident_description)
    if not claimed_amount:
        claimed_amount = _extract_amount_gbp(state.get("user_query", ""))

    # Parallelize tool calls using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as executor:
        policy_future = executor.submit(
            search_policy_clauses.invoke,
            {
                "incident_description": incident_description,
                "coverage_type": coverage_type,
            },
        )
        claims_future = executor.submit(
            lookup_customer_claims_history.invoke,
            {"customer_id": customer_id},
        )
        fraud_future = executor.submit(
            assess_fraud_risk.invoke,
            {
                "customer_id": customer_id,
                "claimed_amount_gbp": float(claimed_amount or 0.0),
            },
        )

        # Wait for all futures to complete
        policy_result = policy_future.result()
        claims_history = claims_future.result()
        fraud_result_raw = fraud_future.result()

    _append_trace(state, "tool", f"Policy search completed for coverage {coverage_type or 'unknown'}")
    _append_trace(state, "tool", "Claims history lookup completed")
    _append_trace(state, "tool", "Fraud assessment completed")

    policy_lines = []
    if isinstance(policy_result, list) and policy_result:
        for doc in policy_result[:3]:
            if "error" in doc:
                policy_lines.append(f"- Policy search error: {doc['error']}")
                continue
            title = doc.get("title", "Policy clause")
            section = doc.get("section", "")
            score = doc.get("score", 0)
            text = str(doc.get("text", ""))[:260].strip()
            policy_lines.append(
                f"- {title} ({section}) [score={score:.4f}] {text}"
            )
    else:
        policy_lines.append("- No policy clauses returned.")

    fraud_text = fraud_result_raw
    fraud_risk_level = "LOW"
    try:
        parsed = json.loads(fraud_result_raw)
        fraud_risk_level = str(parsed.get("risk_level", "LOW"))
        fraud_text = (
            f"risk_level={parsed.get('risk_level', 'UNKNOWN')}, "
            f"score={parsed.get('score', 0)}, "
            f"reasons={'; '.join(parsed.get('reasons', []))}"
        )
    except Exception:
        pass

    assessment_summary = (
        "ASSESSMENT_COMPLETE\n"
        f"Customer: {customer_id or 'unknown'}\n"
        f"Coverage Type: {coverage_type or 'unknown'}\n"
        "\nPolicy Coverage Findings:\n"
        + "\n".join(policy_lines)
        + "\n\nClaims History:\n"
        + str(claims_history)
        + "\n\nFraud Risk:\n"
        + str(fraud_text)
    )

    return {
        **state,
        "response": assessment_summary,
        "assessment_complete": True,
        "fraud_risk_level": fraud_risk_level,
        "estimated_amount_gbp": float(claimed_amount or 0.0),
    }


def _extract_amount_gbp(text: str) -> float:
    if not text:
        return 0.0

    lowered = text.lower()
    contextual_matches = re.finditer(
        r"(?:estimated\s+amount|claimed\s+amount|amount|gbp|£)\s*[:=]?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        lowered,
    )

    contextual_amounts = []
    for match in contextual_matches:
        try:
            contextual_amounts.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue

    if contextual_amounts:
        return contextual_amounts[-1]

    numeric_matches = re.finditer(r"\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b", lowered)
    candidates = []
    for match in numeric_matches:
        token = match.group(1)
        start = match.start()
        prefix = lowered[max(0, start - 6):start]
        if "cust" in prefix:
            continue
        try:
            value = float(token.replace(",", ""))
        except ValueError:
            continue
        if value >= 100:
            candidates.append(value)

    return max(candidates) if candidates else 0.0


def _is_submission_confirmation(text: str) -> bool:
    lowered = text.lower()
    patterns = [
        r"\bconfirm\b.*\bsubmit\b",
        r"\bsubmit\b.*\bfnol\b",
        r"\bgo\s+ahead\b",
        r"\bproceed\b",
    ]
    return any(re.search(pattern, lowered) for pattern in patterns)


def resolution_agent(state: ClaimState) -> ClaimState:
    _append_trace(state, "agent", "Preparing resolution and FNOL decision")
    prior_assessment = state.get("response", "")
    incident_summary = state.get("incident_summary", state.get("incident_description", ""))
    coverage_type = state.get("coverage_type", "unknown")
    customer_id = state.get("customer_id", "")
    fraud_risk_level = state.get("fraud_risk_level", "LOW")
    amount = state.get("estimated_amount_gbp", 0.0)
    if not amount:
        amount = _extract_amount_gbp(state.get("user_query", ""))

    should_submit_fnol = bool(state.get("intake_complete", False)) or _is_submission_confirmation(
        state.get("user_query", "")
    )

    if should_submit_fnol:
        _append_trace(state, "tool", "Submitting FNOL to MongoDB")
        fnol_response = submit_fnol.invoke(
            {
                "customer_id": customer_id,
                "incident_summary": incident_summary,
                "coverage_type": coverage_type,
                "estimated_amount_gbp": amount,
                "fraud_risk_level": fraud_risk_level,
            }
        )
        if prior_assessment:
            final_response = f"{prior_assessment}\n\n{fnol_response}"
        else:
            final_response = fnol_response
        return {
            **state,
            "response": final_response,
            "fnol_submitted": True,
            "estimated_amount_gbp": amount,
        }

    response = (
        "RESOLUTION_READY\n"
        f"Coverage type: {coverage_type}\n"
        f"Estimated claimed amount: £{amount:,.2f}\n"
        f"Fraud risk level: {fraud_risk_level}\n\n"
        "If you want me to submit the FNOL now, reply with: confirm submit FNOL.\n"
        "Please retain all receipts, photos, and police reports."
    )

    return {
        **state,
        "response": response,
        "fnol_submitted": False,
        "estimated_amount_gbp": amount,
    }


def intake_agent(state: ClaimState) -> ClaimState:
    _append_trace(state, "agent", "Running intake agent")
    intake_state: IntakeState = {
        "customer_id": state.get("customer_id", ""),
        "coverage_type": state.get("coverage_type", ""),
        "incident_description": state.get("incident_description", ""),
        "incident_summary": state.get("incident_summary", ""),
        "intake_complete": state.get("intake_complete", False),
    }

    result = run_intake_agent(state.get("user_query", ""), intake_state)
    updated = result["state"]

    next_route = "policy" if updated.get("coverage_type") in {"motor", "home", "health", "travel"} else "policy"

    _append_trace(
        state,
        "tool",
        f"Intake completed with customer {updated.get('customer_id', 'unknown')} and coverage {updated.get('coverage_type', 'unknown')}",
    )

    return {
        **state,
        "response": result["response"],
        "customer_id": updated.get("customer_id", ""),
        "coverage_type": updated.get("coverage_type", ""),
        "incident_description": updated.get("incident_description", ""),
        "incident_summary": updated.get("incident_summary", ""),
        "estimated_amount_gbp": _extract_amount_gbp(state.get("user_query", "")),
        "intake_complete": updated.get("intake_complete", False),
        "route": next_route,
    }


def policy_agent(state: ClaimState) -> ClaimState:
    return {
        **state,
        "response": "Policy agent: I can help explain coverage and deductibles for your claim.",
    }


def fraud_agent(state: ClaimState) -> ClaimState:
    return {
        **state,
        "response": "Fraud agent: I can help flag suspicious patterns for investigator review.",
    }


def route_after_triage(state: ClaimState) -> str:
    return state.get("route", "policy")


def route_after_intake(state: ClaimState) -> str:
    return "assessment" if state.get("intake_complete", False) else "end"


def route_after_assessment(state: ClaimState) -> str:
    return "resolution" if state.get("assessment_complete", False) else "end"


def build_claim_graph():
    graph = StateGraph(ClaimState)
    graph.add_node("intake", intake_agent)
    graph.add_node("assessment", assessment_agent)
    graph.add_node("resolution", resolution_agent)

    graph.add_edge(START, "intake")
    graph.add_conditional_edges(
        "intake",
        route_after_intake,
        {
            "assessment": "assessment",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "assessment",
        route_after_assessment,
        {
            "resolution": "resolution",
            "end": END,
        },
    )
    graph.add_edge("resolution", END)

    return graph.compile()
