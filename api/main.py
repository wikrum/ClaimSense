from fastapi import FastAPI
from fastapi import HTTPException
from dotenv import load_dotenv
from pydantic import BaseModel
from pymongo import MongoClient
import os

from agents.claim_graph import build_claim_graph

load_dotenv()

app = FastAPI(title="ClaimSense API", version="0.1.0")
graph = build_claim_graph()
SESSION_STATES: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    claim_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    response: str
    route: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    session_id = payload.session_id or payload.claim_id or "default"
    previous = SESSION_STATES.get(session_id, {})
    next_state = {
        **previous,
        "user_query": payload.message,
        "claim_id": session_id,
    }
    result = graph.invoke(next_state)
    SESSION_STATES[session_id] = result
    text = result.get("response", "No response generated.")
    return ChatResponse(reply=text, response=text, route=result.get("route"))


def _get_mongo_collection(collection_name: str):
    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        raise HTTPException(status_code=500, detail="MONGODB_URI is not configured.")

    client = MongoClient(mongo_uri)
    return client, client["claimsense_db"][collection_name]


def _serialize_mongo_doc(doc: dict) -> dict:
    out: dict = {}
    for key, value in doc.items():
        if key == "_id":
            out[key] = str(value)
        elif hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


@app.get("/fnol/{fnol_id}")
def get_fnol(fnol_id: str) -> dict:
    client = None
    try:
        client, collection = _get_mongo_collection("fnol_submissions")
        doc = collection.find_one({"fnol_id": fnol_id})
        if not doc:
            raise HTTPException(status_code=404, detail=f"FNOL not found: {fnol_id}")
        return _serialize_mongo_doc(doc)
    finally:
        if client is not None:
            client.close()


@app.get("/customer/{customer_id}/claims")
def get_customer_claims(customer_id: str) -> dict:
    client = None
    customer = customer_id.strip().upper()
    try:
        client, collection = _get_mongo_collection("claims_history")
        claims = list(
            collection.find(
                {"customer_id": customer},
                {
                    "_id": 0,
                    "claim_id": 1,
                    "date_filed": 1,
                    "status": 1,
                    "amount_claimed_gbp": 1,
                },
            )
            .sort("date_filed", -1)
            .limit(5)
        )
        serialized_claims = []
        for claim in claims:
            serialized = _serialize_mongo_doc(claim)
            serialized_claims.append(serialized)

        return {"customer_id": customer, "claims": serialized_claims}
    finally:
        if client is not None:
            client.close()
