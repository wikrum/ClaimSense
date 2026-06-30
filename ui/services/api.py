import os
from typing import Any, Dict

import requests


API_BASE_URL = os.getenv("CLAIMSENSE_API_URL", "http://localhost:8000")
CHAT_TIMEOUT_SECONDS = int(os.getenv("CLAIMSENSE_CHAT_TIMEOUT", "120"))
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("CLAIMSENSE_DEFAULT_TIMEOUT", "30"))


def post_chat(session_id: str, message: str) -> Dict[str, Any]:
    res = requests.post(
        f"{API_BASE_URL}/chat",
        json={"session_id": session_id, "message": message},
        timeout=(10, CHAT_TIMEOUT_SECONDS),
    )
    res.raise_for_status()
    return res.json()


def get_fnol(fnol_id: str) -> Dict[str, Any]:
    res = requests.get(f"{API_BASE_URL}/fnol/{fnol_id}", timeout=DEFAULT_TIMEOUT_SECONDS)
    res.raise_for_status()
    return res.json()


def get_customer_claims(customer_id: str) -> Dict[str, Any]:
    res = requests.get(
        f"{API_BASE_URL}/customer/{customer_id}/claims",
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    res.raise_for_status()
    return res.json()
