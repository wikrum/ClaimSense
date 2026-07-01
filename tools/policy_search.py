import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from pymongo import MongoClient
import voyageai


load_dotenv()


DB_NAME = os.getenv("MONGODB_DB", "claimsense_db")
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
            docs = []

            # Prefer an exact coverage-type match first so the UI stays scenario-relevant.
            if coverage_type and coverage_type.strip():
                exact_filter = {"coverage_type": coverage_type.strip()}
                exact_docs = list(
                    collection.find(
                        exact_filter,
                        {
                            "_id": 0,
                            "doc_id": 1,
                            "title": 1,
                            "section": 1,
                            "coverage_type": 1,
                            "text": 1,
                        },
                    ).limit(TOP_K)
                )
                if exact_docs:
                    docs = exact_docs
                    for d in docs:
                        d["score"] = 0.0

            if not docs:
                try:
                    docs = list(collection.aggregate(pipeline))
                except Exception:
                    docs = []

            if not docs and coverage_type and coverage_type.strip():
                # Fallback: if strict coverage filter finds nothing, retry unfiltered.
                fallback_stage: Dict[str, Any] = {
                    "$vectorSearch": {
                        "index": VECTOR_INDEX_NAME,
                        "path": VECTOR_PATH,
                        "queryVector": query_vector,
                        "numCandidates": 100,
                        "limit": TOP_K,
                    }
                }
                fallback_pipeline = [
                    fallback_stage,
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
                try:
                    docs = list(collection.aggregate(fallback_pipeline))
                except Exception:
                    docs = []

            if not docs:
                # Final fallback: lexical search on title/text to avoid empty UX when vector retrieval yields none.
                raw_tokens = re.findall(r"[a-zA-Z]{4,}", incident_description.lower())
                stop_words = {
                    "with", "from", "that", "this", "have", "were", "been", "their", "there",
                    "would", "could", "should", "about", "after", "before", "under", "over", "between",
                    "claim", "claims", "incident", "customer", "coverage", "amount", "police", "report",
                }
                keywords = [t for t in raw_tokens if t not in stop_words][:6]

                lexical_filter: Dict[str, Any] = {}
                if keywords:
                    lexical_filter = {
                        "$or": [
                            {"title": {"$regex": "|".join(keywords), "$options": "i"}},
                            {"text": {"$regex": "|".join(keywords), "$options": "i"}},
                        ]
                    }

                if coverage_type and coverage_type.strip():
                    lexical_filter = {
                        "$and": [
                            lexical_filter if lexical_filter else {},
                            {"coverage_type": coverage_type.strip()},
                        ]
                    }

                if lexical_filter:
                    lexical_docs = list(
                        collection.find(
                            lexical_filter,
                            {
                                "_id": 0,
                                "doc_id": 1,
                                "title": 1,
                                "section": 1,
                                "coverage_type": 1,
                                "text": 1,
                            },
                        ).limit(TOP_K)
                    )
                else:
                    lexical_docs = list(
                        collection.find(
                            {},
                            {
                                "_id": 0,
                                "doc_id": 1,
                                "title": 1,
                                "section": 1,
                                "coverage_type": 1,
                                "text": 1,
                            },
                        ).limit(TOP_K)
                    )

                if not lexical_docs and coverage_type and coverage_type.strip():
                    # Final retry without coverage restriction to surface nearest policy guidance.
                    if keywords:
                        broad_filter = {
                            "$or": [
                                {"title": {"$regex": "|".join(keywords), "$options": "i"}},
                                {"text": {"$regex": "|".join(keywords), "$options": "i"}},
                            ]
                        }
                        lexical_docs = list(
                            collection.find(
                                broad_filter,
                                {
                                    "_id": 0,
                                    "doc_id": 1,
                                    "title": 1,
                                    "section": 1,
                                    "coverage_type": 1,
                                    "text": 1,
                                },
                            ).limit(TOP_K)
                        )

                if not lexical_docs:
                    lexical_docs = list(
                        collection.find(
                            {},
                            {
                                "_id": 0,
                                "doc_id": 1,
                                "title": 1,
                                "section": 1,
                                "coverage_type": 1,
                                "text": 1,
                            },
                        ).limit(TOP_K)
                    )

                for d in lexical_docs:
                    d["score"] = 0.0
                docs = lexical_docs
        finally:
            client.close()

        for i, doc in enumerate(docs, start=1):
            doc["rank"] = i

        return docs
    except Exception as exc:
        return [{"error": f"policy search failed: {exc}"}]
