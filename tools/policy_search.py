import os
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pymongo import MongoClient
import voyageai


DB_NAME = "claimsense_db"
COLLECTION_NAME = "policy_docs"
VECTOR_INDEX_NAME = "vector_index"
VECTOR_PATH = "embedding"
VECTOR_DIMENSIONS = 1024
TOP_K = 3


def _embed_query_with_voyage(text: str) -> List[float]:
    """Generate query embedding using Voyage AI for Atlas Vector Search."""
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        raise ValueError("VOYAGE_API_KEY is not configured.")

    model_id = os.getenv("VOYAGE_EMBEDDING_MODEL", "voyage-3-large")
    output_dimensions = int(os.getenv("VOYAGE_OUTPUT_DIMENSIONS", str(VECTOR_DIMENSIONS)))

    client = voyageai.Client(api_key=api_key)
    response = client.embed(
        texts=[text],
        model=model_id,
        input_type="query",
        output_dimension=output_dimensions,
    )
    embedding = response.embeddings[0] if response.embeddings else []

    if not embedding:
        raise ValueError("No embedding returned from Voyage model.")

    if len(embedding) != VECTOR_DIMENSIONS:
        raise ValueError(
            f"Expected embedding length {VECTOR_DIMENSIONS}, got {len(embedding)}. "
            "Verify VOYAGE_OUTPUT_DIMENSIONS matches your Atlas index dimensions."
        )

    return embedding


@tool
def search_policy_clauses(
    incident_description: str,
    coverage_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search policy clauses via Atlas Vector Search and return top 3 matches with score."""
    if not incident_description or not incident_description.strip():
        return [{"error": "incident_description must not be empty."}]

    mongo_uri = os.getenv("MONGODB_URI")
    if not mongo_uri:
        return [{"error": "MONGODB_URI is not configured."}]

    try:
        query_vector = _embed_query_with_voyage(incident_description.strip())

        vector_stage: Dict[str, Any] = {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": VECTOR_PATH,
                "queryVector": query_vector,
                "numCandidates": 100,
                "limit": TOP_K,
            }
        }

        if coverage_type and coverage_type.strip():
            vector_stage["$vectorSearch"]["filter"] = {
                "coverage_type": coverage_type.strip()
            }

        pipeline = [
            vector_stage,
            {
                "$project": {
                    "_id": 0,
                    "doc_id": 1,
                    "title": 1,
                    "section": 1,
                    "coverage_type": 1,
                    "text": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]

        client = MongoClient(mongo_uri)
        try:
            collection = client[DB_NAME][COLLECTION_NAME]
            docs = list(collection.aggregate(pipeline))
        finally:
            client.close()

        for i, doc in enumerate(docs, start=1):
            doc["rank"] = i

        return docs
    except Exception as exc:
        return [{"error": f"policy search failed: {exc}"}]
