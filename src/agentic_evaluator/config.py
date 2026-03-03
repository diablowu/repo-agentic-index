"""
LLM client configuration for AutoGen agents (autogen-agentchat 0.7.x).

Supports:
- Mock server (default for testing): http://localhost:8000
- Any OpenAI-compatible endpoint via environment variables
"""

import os

from autogen_core.models import ModelInfo
from autogen_ext.models.openai import OpenAIChatCompletionClient

# ─── LLM Endpoint Config ──────────────────────────────────────────────────────

DEFAULT_MOCK_URL = "http://localhost:8000/v1"

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", DEFAULT_MOCK_URL)
LLM_API_KEY = os.environ.get("LLM_API_KEY", "mock-key-not-needed")
LLM_MODEL = os.environ.get("LLM_MODEL", "mock-gpt-4")


def get_model_client() -> OpenAIChatCompletionClient:
    """
    Create and return an OpenAI-compatible model client for AutoGen agents.

    Environment variables:
        LLM_BASE_URL: OpenAI-compatible API base URL (default: mock server)
        LLM_API_KEY: API key (default: mock placeholder)
        LLM_MODEL: Model name (default: mock-gpt-4)

    Returns:
        OpenAIChatCompletionClient configured for the target endpoint.
    """
    base_url = os.environ.get("LLM_BASE_URL", LLM_BASE_URL)
    api_key = os.environ.get("LLM_API_KEY", LLM_API_KEY)
    model = os.environ.get("LLM_MODEL", LLM_MODEL)

    return OpenAIChatCompletionClient(
        model=model,
        api_key=api_key,
        base_url=base_url,
        model_info=ModelInfo(
            vision=False,
            function_calling=True,
            json_output=True,
            family="unknown",
            structured_output=False,
        ),
    )
