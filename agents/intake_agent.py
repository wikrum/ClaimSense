import re
from typing import Dict, Optional, TypedDict


class IntakeState(TypedDict, total=False):
    customer_id: str
    coverage_type: str
    incident_description: str
    incident_summary: str
    intake_complete: bool


VALID_COVERAGE_TYPES = {"motor", "home", "health", "travel"}


def _extract_customer_id(text: str) -> Optional[str]:
    match = re.search(r"\bCUST\d{4}\b", text.upper())
    return match.group(0) if match else None


def _extract_coverage_type(text: str) -> Optional[str]:
    lowered = text.lower()
    for coverage_type in VALID_COVERAGE_TYPES:
        if coverage_type in lowered:
            return coverage_type
    return None


def _build_incident_summary(description: str, max_words: int = 24) -> str:
    words = description.strip().split()
    if not words:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "..."


def _next_missing_field(state: IntakeState) -> Optional[str]:
    if not state.get("customer_id"):
        return "customer_id"
    if not state.get("incident_description"):
        return "incident_description"
    if not state.get("coverage_type"):
        return "coverage_type"
    return None


def _question_for_missing_field(missing_field: str) -> str:
    if missing_field == "customer_id":
        return (
            "Thank you for contacting ClaimSense. "
            "Please share your customer ID in this format: CUST followed by 4 digits (for example, CUST1005)."
        )
    if missing_field == "incident_description":
        return (
            "Thanks. Please describe what happened in one or two sentences, "
            "including what was damaged or who was affected."
        )
    return (
        "Understood. Which policy type is this claim for: motor, home, health, or travel?"
    )


def run_intake_agent(user_message: str, state: Optional[IntakeState] = None) -> Dict[str, object]:
    """Collect customer_id, incident description, and coverage type for handoff to assessment."""
    current: IntakeState = dict(state or {})
    text = (user_message or "").strip()

    customer_id = _extract_customer_id(text)
    if customer_id:
        current["customer_id"] = customer_id

    coverage_type = _extract_coverage_type(text)
    if coverage_type:
        current["coverage_type"] = coverage_type

    if text and len(text.split()) >= 5:
        current["incident_description"] = text

    missing_field = _next_missing_field(current)
    if missing_field:
        current["intake_complete"] = False
        response = _question_for_missing_field(missing_field)
        return {"response": response, "state": current}

    summary = _build_incident_summary(current["incident_description"])
    current["incident_summary"] = summary
    current["intake_complete"] = True

    response = (
        "Thank you. I have captured the key incident details and will now hand this to assessment.\n\n"
        f"INTAKE_COMPLETE: customer_id={current['customer_id']}, "
        f"coverage_type={current['coverage_type']}, incident={summary}"
    )

    return {"response": response, "state": current}


if __name__ == "__main__":
    sample_state: IntakeState = {}
    turns = [
        "Hi there",
        "My customer id is CUST1001",
        "Someone rear-ended my car at a traffic light and the bumper is damaged",
        "This is for my motor policy",
    ]

    for turn in turns:
        result = run_intake_agent(turn, sample_state)
        sample_state = result["state"]
        print("You:", turn)
        print("Agent:", result["response"])
        print()
