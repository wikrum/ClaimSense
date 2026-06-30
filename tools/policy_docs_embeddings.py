import os
import time
from typing import Dict, List

from dotenv import load_dotenv
from pymongo import MongoClient
import voyageai


VECTOR_DIMENSIONS = 1024
DEFAULT_EMBED_MODEL = "voyage-3-large"


def _build_embedding_input(doc: Dict) -> str:
    parts = [
        str(doc.get("title", "")).strip(),
        str(doc.get("section", "")).strip(),
        str(doc.get("coverage_type", "")).strip(),
        str(doc.get("text", "")).strip(),
    ]
    return "\n".join(p for p in parts if p)


def _embed_text(
    client: voyageai.Client,
    model_id: str,
    text: str,
    output_dimensions: int,
) -> List[float]:
    response = client.embed(
        texts=[text],
        model=model_id,
        input_type="document",
        output_dimension=output_dimensions,
    )
    embedding = response.embeddings[0] if response.embeddings else []

    if not embedding:
        raise ValueError("Voyage returned an empty embedding.")

    if len(embedding) != output_dimensions:
        raise ValueError(
            f"Expected embedding length {output_dimensions}, got {len(embedding)}."
        )

    return embedding


def _embed_with_retry(
    client: voyageai.Client,
    model_id: str,
    text: str,
    output_dimensions: int,
    max_attempts: int = 8,
) -> List[float]:
    for attempt in range(1, max_attempts + 1):
        try:
            return _embed_text(client, model_id, text, output_dimensions)
        except Exception as exc:
            message = str(exc)
            is_throttle = "429" in message or "rate limit" in message.lower() or "too many requests" in message.lower()

            if not is_throttle or attempt == max_attempts:
                raise

            sleep_seconds = min(2 ** attempt, 30)
            print(f"[retry] throttled; waiting {sleep_seconds}s before retry {attempt + 1}/{max_attempts}")
            time.sleep(sleep_seconds)


def backfill_policy_doc_embeddings() -> None:
    load_dotenv()

    mongo_uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB", "claimsense_db")
    voyage_api_key = os.getenv("VOYAGE_API_KEY")
    embedding_model_id = os.getenv("VOYAGE_EMBEDDING_MODEL", DEFAULT_EMBED_MODEL)
    output_dimensions = int(os.getenv("VOYAGE_OUTPUT_DIMENSIONS", str(VECTOR_DIMENSIONS)))

    if not mongo_uri:
        raise RuntimeError("MONGODB_URI is missing in .env")
    if not voyage_api_key:
        raise RuntimeError("VOYAGE_API_KEY is missing in .env")

    mongo_client = MongoClient(mongo_uri)
    voyage_client = voyageai.Client(api_key=voyage_api_key)

    try:
        collection = mongo_client[db_name]["policy_docs"]

        query = {
            "$or": [
                {"embedding": {"$exists": False}},
                {"embedding": None},
                {"embedding": []},
            ]
        }

        docs = list(collection.find(query, {"_id": 1, "doc_id": 1, "title": 1, "section": 1, "coverage_type": 1, "text": 1}))

        if not docs:
            print("No policy_docs missing embeddings. Nothing to do.")
            return

        print(f"Generating embeddings for {len(docs)} policy_docs...")

        success = 0
        failed = 0

        for doc in docs:
            doc_id = str(doc.get("doc_id", doc.get("_id")))
            try:
                input_text = _build_embedding_input(doc)
                if not input_text:
                    raise ValueError("Document has no usable text fields.")

                embedding = _embed_with_retry(
                    voyage_client,
                    embedding_model_id,
                    input_text,
                    output_dimensions,
                )

                collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"embedding": embedding, "embedding_model": embedding_model_id}},
                )
                success += 1
                print(f"[ok] {doc_id}")
                time.sleep(0.6)
            except Exception as exc:
                failed += 1
                print(f"[fail] {doc_id}: {exc}")

        print(f"Done. success={success}, failed={failed}")
    finally:
        mongo_client.close()


if __name__ == "__main__":
    backfill_policy_doc_embeddings()
