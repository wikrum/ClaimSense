from fastapi import FastAPI
from dotenv import load_dotenv
from pydantic import BaseModel

from agents.claim_graph import build_claim_graph

load_dotenv()

app = FastAPI(title="ClaimSense API", version="0.1.0")
graph = build_claim_graph()
SESSION_STATES: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str
    claim_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    route: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    session_id = payload.claim_id or "default"
    previous = SESSION_STATES.get(session_id, {})
    next_state = {
        **previous,
        "user_query": payload.message,
        "claim_id": session_id,
    }
    result = graph.invoke(next_state)
    SESSION_STATES[session_id] = result
    return ChatResponse(reply=result.get("response", "No response generated."), route=result.get("route"))
