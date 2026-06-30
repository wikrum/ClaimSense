import os


def build_checkpointer():
    """Create a MongoDB-backed checkpointer when available, else fallback in-memory."""
    mongo_uri = os.getenv("MONGODB_URI")

    if mongo_uri:
        try:
            from langgraph.checkpoint.mongodb import MongoDBSaver

            return MongoDBSaver.from_conn_string(mongo_uri)
        except Exception:
            pass

    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()
