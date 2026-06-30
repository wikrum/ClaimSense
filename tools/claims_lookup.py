import os
from datetime import datetime
from typing import Any, Dict, List

from langchain_core.tools import tool
from pymongo import MongoClient


def _format_claim_row(claim: Dict[str, Any]) -> str:
    claim_id = claim.get("claim_id", "unknown")
    claim_date = claim.get("date_filed") or claim.get("claim_date")
    status = claim.get("status", "unknown")
    amount = claim.get("amount_claimed_gbp", 0)

    if isinstance(claim_date, datetime):
        claim_date_text = claim_date.strftime("%Y-%m-%d")
    else:
        claim_date_text = str(claim_date) if claim_date is not None else "unknown"

    try:
        amount_text = f"{float(amount):,.2f}"
    except (TypeError, ValueError):
        amount_text = "0.00"

    return (
        f"- claim_id={claim_id}, date={claim_date_text}, "
        f"status={status}, amount_gbp={amount_text}"
    )


@tool
def lookup_customer_claims_history(customer_id: str) -> str:
    """Return customer-level claims summary and most recent 5 claims from MongoDB."""
    if not customer_id or not customer_id.strip():
        return "Error: customer_id must not be empty."

    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        return "Error: MONGODB_URI is not configured."

    pipeline: List[Dict[str, Any]] = [
        {"$match": {"customer_id": customer_id.strip()}},
        {
            "$facet": {
                "summary": [
                    {
                        "$group": {
                            "_id": None,
                            "total_claims_count": {"$sum": 1},
                            "average_amount_claimed_gbp": {
                                "$avg": {"$ifNull": ["$amount_claimed_gbp", 0]}
                            },
                            "rejected_claims_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$eq": [
                                                {"$toLower": {"$ifNull": ["$status", ""]}},
                                                "rejected",
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                    {"$project": {"_id": 0}},
                ],
                "recent_claims": [
                    {"$sort": {"date_filed": -1}},
                    {"$limit": 5},
                    {
                        "$project": {
                            "_id": 0,
                            "claim_id": 1,
                            "date_filed": 1,
                            "status": 1,
                            "amount_claimed_gbp": {"$ifNull": ["$amount_claimed_gbp", 0]},
                        }
                    },
                ],
            }
        },
    ]

    client = MongoClient(mongo_uri)
    try:
        collection = client["claimsense_db"]["claims_history"]
        result = list(collection.aggregate(pipeline))
    except Exception as exc:
        return f"Error: failed to query claims history. Details: {exc}"
    finally:
        client.close()

    if not result:
        return f"No claims found for customer_id={customer_id.strip()}."

    payload = result[0]
    summary_rows = payload.get("summary", [])
    summary = summary_rows[0] if summary_rows else {}

    total_claims = int(summary.get("total_claims_count", 0) or 0)
    rejected_claims = int(summary.get("rejected_claims_count", 0) or 0)
    avg_amount = summary.get("average_amount_claimed_gbp", 0) or 0

    try:
        avg_amount_text = f"{float(avg_amount):,.2f}"
    except (TypeError, ValueError):
        avg_amount_text = "0.00"

    recent_claims = payload.get("recent_claims", [])

    if not recent_claims:
        recent_claims_text = "- none"
    else:
        recent_claims_text = "\n".join(_format_claim_row(claim) for claim in recent_claims)

    return (
        f"Customer Claims Summary (customer_id={customer_id.strip()}):\n"
        f"- total_claims_count: {total_claims}\n"
        f"- average_amount_claimed_gbp: {avg_amount_text}\n"
        f"- rejected_claims_count: {rejected_claims}\n"
        f"- most_recent_5_claims:\n{recent_claims_text}"
    )
