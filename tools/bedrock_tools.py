import json
import os
from typing import Any, Dict

import boto3
from langchain_core.tools import tool


@tool
def invoke_claude_sonnet(prompt: str) -> Dict[str, Any]:
    """Invoke Claude Sonnet on AWS Bedrock with a plain text prompt."""
    region = os.getenv("AWS_REGION", "us-east-1")
    model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")

    try:
        client = boto3.client("bedrock-runtime", region_name=region)

        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 600,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        }

        response = client.invoke_model(
            modelId=model_id,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        body = json.loads(response["body"].read())

        text_parts = []
        for item in body.get("content", []):
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        return {"model_id": model_id, "text": "\n".join(text_parts).strip(), "raw": body}
    except Exception as exc:
        return {
            "model_id": model_id,
            "text": "",
            "error": str(exc),
            "raw": {"error_type": type(exc).__name__},
        }
