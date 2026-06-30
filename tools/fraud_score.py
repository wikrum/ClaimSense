import json
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from langchain_core.tools import tool
from pymongo import MongoClient


load_dotenv()


@tool
def assess_fraud_risk(customer_id: str, claimed_amount_gbp: float = 0.0) -> str:
    """Assess fraud risk using claim frequency, prior rejections, and amount anomalies."""
    if not customer_id or not customer_id.strip():
        return json.dumps({"error": "customer_id must not be empty."})

    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        return json.dumps({"error": "MONGODB_URI is not configured."})

    twelve_months_ago = (datetime.utcnow() - timedelta(days=365)).strftime("%Y-%m-%d")

    pipeline = [
        {"$match": {"customer_id": customer_id.strip()}},
        {
            "$group": {
                "_id": "$customer_id",
                "total_claims": {"$sum": 1},
                "avg_amount": {"$avg": {"$ifNull": ["$amount_claimed_gbp", 0]}},
                "rejected_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": [{"$toLower": {"$ifNull": ["$status", ""]}}, "rejected"]},
                            1,
                            0,
                        ]
                    }
                },
                "fos_count": {
                    "$sum": {"$cond": [{"$ifNull": ["$fos_referral_risk", False]}, 1, 0]}
                },
                "recent_claims": {
                    "$sum": {
                        "$cond": [
                            {"$gte": [{"$ifNull": ["$date_filed", ""]}, twelve_months_ago]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]

    client = MongoClient(mongo_uri)
    try:
        collection = client["claimsense_db"]["claims_history"]
        rows = list(collection.aggregate(pipeline))
    except Exception as exc:
        return json.dumps({"error": f"failed to assess fraud risk: {exc}"})
    finally:
        client.close()

    if not rows:
        return json.dumps(
            {
                "risk_level": "LOW",
                "score": 0,
                "reasons": ["No prior claims history."],
                "total_prior_claims": 0,
            }
        )

    r = rows[0]
    avg_amount = float(r.get("avg_amount", 0) or 0)
    score = 0
    reasons = []

    if int(r.get("recent_claims", 0) or 0) >= 3:
        score += 3
        reasons.append(
            f"High claim frequency: {int(r.get('recent_claims', 0) or 0)} in last 12 months"
        )

    if avg_amount > 0 and claimed_amount_gbp > avg_amount * 3:
        score += 3
        reasons.append(
            f"Claim amount £{claimed_amount_gbp:,.0f} is above historical average £{avg_amount:,.0f}"
        )

    if int(r.get("rejected_count", 0) or 0) >= 2:
        score += 2
        reasons.append(f"{int(r.get('rejected_count', 0) or 0)} previously rejected claims")

    if int(r.get("fos_count", 0) or 0) >= 1:
        score += 2
        reasons.append("Prior FOS referral risk on record")

    risk_level = "HIGH" if score >= 6 else "MEDIUM" if score >= 3 else "LOW"

    if not reasons:
        reasons = ["No significant fraud indicators detected."]

    return json.dumps(
        {
            "risk_level": risk_level,
            "score": score,
            "reasons": reasons,
            "total_prior_claims": int(r.get("total_claims", 0) or 0),
            "avg_prior_amount_gbp": round(avg_amount, 2),
        }
    )
