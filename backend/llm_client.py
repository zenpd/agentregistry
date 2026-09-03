"""Azure OpenAI LLM client for AIRegistry orchestrations.

Supports both Azure OpenAI (production) and a fallback deterministic mode
when no API key is configured (local development).
"""
from __future__ import annotations

import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """Thin wrapper around Azure OpenAI chat completions with fallback."""

    def __init__(self):
        self.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        self.api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
        self._client = None

    @property
    def available(self) -> bool:
        """True when a real API key is configured."""
        return bool(self.api_key and self.endpoint)

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.available:
            return None
        try:
            from openai import AzureOpenAI
            self._client = AzureOpenAI(
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=self.api_version,
            )
        except ImportError:
            logger.warning("openai package not installed — falling back to deterministic mode")
            self._client = None
        return self._client

    def chat(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """Send a chat completion request. Falls back to deterministic response if no key."""
        client = self._get_client()
        if client is None:
            return self._fallback(system, user)

        try:
            resp = client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content or ""
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            return self._fallback(system, user)

    def chat_json(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Chat and parse JSON response. Falls back to deterministic dict."""
        raw = self.chat(system, user, max_tokens)
        try:
            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw, "_error": "invalid_json"}

    def _fallback(self, system: str, user: str) -> str:
        """Deterministic fallback when no LLM is available."""
        return f"[DETERMINISTIC] System: {system[:80]}... | User: {user[:80]}..."


# Singleton instance
llm = LLMClient()


def llm_review_notes(agent_name: str, agent_type: str, gate: str, agent_context: dict) -> str:
    """Generate governance review notes for a specific gate."""
    system = (
        "You are an AI governance reviewer. Generate concise, actionable review notes "
        "for the given agent and gate. Be specific and practical."
    )
    user = (
        f"Agent: {agent_name}\n"
        f"Type: {agent_type}\n"
        f"Gate: {gate}\n"
        f"Context: {json.dumps(agent_context, default=str)[:500]}\n\n"
        f"Generate 1-2 sentences of review notes."
    )
    return llm.chat(system, user, max_tokens=256)


def llm_waste_suggestions(agent_name: str, findings: list) -> str:
    """Generate optimization suggestions from waste findings."""
    system = "You are a cost optimization analyst. Given waste findings, suggest concrete cost-saving actions."
    user = (
        f"Agent: {agent_name}\n"
        f"Waste findings: {json.dumps(findings, default=str)[:800]}\n\n"
        f"Generate 1-3 prioritized suggestions."
    )
    return llm.chat(system, user, max_tokens=512)


def llm_impact_summary(target_name: str, impact: dict) -> str:
    """Generate a natural-language impact summary."""
    system = "You are an AI risk analyst. Summarize the outage impact in 2-3 sentences."
    user = (
        f"Target: {target_name}\n"
        f"Impact data: {json.dumps(impact, default=str)[:500]}\n\n"
        f"Generate a concise impact summary."
    )
    return llm.chat(system, user, max_tokens=256)


def llm_discovery_signal(suspected_name: str, source: str, raw_data: str) -> str:
    """Generate a human-readable signal description for a discovery."""
    system = "You are an AI discovery analyst. Describe why this finding matters in 1 sentence."
    user = (
        f"Finding: {suspected_name}\n"
        f"Source: {source}\n"
        f"Raw data: {raw_data[:300]}\n\n"
        f"Generate a concise signal description."
    )
    return llm.chat(system, user, max_tokens=128)