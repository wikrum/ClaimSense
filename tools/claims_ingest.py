import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne


ROOT_DIR = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT_DIR / "files"

FILE_COLLECTION_MAP: Dict[str, Tuple[str, str]] = {
    "policy_docs_uk.json": ("policy_docs", "doc_id"),
    "policies_uk.json": ("policies", "policy_id"),
    "customers_uk.json": ("customers", "customer_id"),
    "claims_history_uk.json": ("claims_history", "claim_id"),
}


def _load_json_array(file_path: Path) -> List[Dict[str, Any]]:
    with file_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON array in {file_path.name}")

    rows: List[Dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append(item)

    return rows


def _upsert_many(collection, docs: List[Dict[str, Any]], id_field: str) -> Tuple[int, int, int]:
    ops = []
    skipped = 0

    for doc in docs:
        doc_id = doc.get(id_field)
        if doc_id is None:
            skipped += 1
            continue
        ops.append(ReplaceOne({id_field: doc_id}, doc, upsert=True))

    if not ops:
        return (0, 0, skipped)

    result = collection.bulk_write(ops, ordered=False)
    inserted = int(result.upserted_count)
    modified = int(result.modified_count)

    return (inserted, modified, skipped)


def ingest_all() -> None:
    load_dotenv(ROOT_DIR / ".env")

    mongo_uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB", "claimsense_db")

    if not mongo_uri:
        raise RuntimeError("MONGODB_URI is missing. Set it in .env.")

    if not FILES_DIR.exists():
        raise RuntimeError(f"Files folder not found: {FILES_DIR}")

    client = MongoClient(mongo_uri)
    try:
        db = client[db_name]

        print(f"Connected. Target database: {db_name}")
        print(f"Reading files from: {FILES_DIR}")

        total_upserted = 0
        total_modified = 0
        total_skipped = 0

        for file_name, (collection_name, id_field) in FILE_COLLECTION_MAP.items():
            file_path = FILES_DIR / file_name
            if not file_path.exists():
                print(f"[skip] {file_name} not found")
                continue

            docs = _load_json_array(file_path)
            collection = db[collection_name]
            inserted, modified, skipped = _upsert_many(collection, docs, id_field)

            total_upserted += inserted
            total_modified += modified
            total_skipped += skipped

            print(
                f"[ok] {file_name} -> {collection_name} "
                f"(rows={len(docs)}, upserted={inserted}, modified={modified}, skipped={skipped})"
            )

        print("Ingestion complete.")
        print(
            f"Summary: upserted={total_upserted}, modified={total_modified}, skipped={total_skipped}"
        )
    finally:
        client.close()


if __name__ == "__main__":
    ingest_all()
