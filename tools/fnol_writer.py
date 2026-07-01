import os
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.tools import tool
from pymongo import MongoClient


load_dotenv()


@tool
def submit_fnol(
    customer_id: str,
    incident_summary: str,
    coverage_type: str,
    estimated_amount_gbp: float,
    fraud_risk_level: str,
) -> str:
    """Submit FNOL document to MongoDB Atlas and return reference."""
    if not customer_id:
        return "Error: customer_id is required."

    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        return "Error: MONGODB_URI is not configured."

    fnol_doc = {
        "fnol_id": f"FNOL-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
        "customer_id": customer_id,
        "incident_summary": incident_summary,
        "coverage_type": coverage_type,
        "estimated_amount_gbp": float(estimated_amount_gbp or 0.0),
        "fraud_risk_level": fraud_risk_level,
        "status": "submitted",
        "channel": "AI Agent",
        "created_at": datetime.utcnow(),
        "next_steps": (
            "A claims handler will contact you within 1 working day. "
            "Please retain all receipts, photos, and police reports."
        ),
    }

    db_name = os.getenv("MONGODB_DB", "claimsense_db")

    client = MongoClient(mongo_uri)
    try:
        collection = client[db_name]["fnol_submissions"]
        collection.create_index("fnol_id", unique=True)
        result = collection.insert_one(fnol_doc)
    except Exception as exc:
        return f"Error: FNOL submission failed: {exc}"
    finally:
        client.close()

    return (
        "FNOL submitted successfully. "
        f"Reference: {fnol_doc['fnol_id']}. "
        f"Stored in MongoDB Atlas (ID: {result.inserted_id}). "
        "A claims handler will contact you within 1 working day."
    )
