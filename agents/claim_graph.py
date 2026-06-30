from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class ClaimState(TypedDict, total=False):
    user_query: str
    claim_id: str
    route: str
    response: str


def triage_agent(state: ClaimState) -> ClaimState:
    query = state.get("user_query", "")
    route = "policy" if "policy" in query.lower() else "fraud"
    return {**state, "route": route}


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


def build_claim_graph():
    graph = StateGraph(ClaimState)
    graph.add_node("triage", triage_agent)
    graph.add_node("policy", policy_agent)
    graph.add_node("fraud", fraud_agent)

    graph.add_edge(START, "triage")
    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        {
            "policy": "policy",
            "fraud": "fraud",
        },
    )
    graph.add_edge("policy", END)
    graph.add_edge("fraud", END)

    return graph.compile()
