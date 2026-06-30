from fastapi import FastAPI
from pydantic import BaseModel

from agents.claim_graph import build_claim_graph

app = FastAPI(title="ClaimSense API", version="0.1.0")
graph = build_claim_graph()


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
    result = graph.invoke(
        {
            "user_query": payload.message,
            "claim_id": payload.claim_id or "",
        }
    )
    return ChatResponse(reply=result.get("response", "No response generated."), route=result.get("route"))
