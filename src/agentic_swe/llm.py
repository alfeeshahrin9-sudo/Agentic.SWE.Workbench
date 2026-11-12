"""Optional LLM helpers. Falls back to None when extras/API key are unavailable."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel

from agentic_swe.config import Settings

T = TypeVar("T", bound=BaseModel)


def llm_available(settings: Settings) -> bool:
    if not settings.llm_enabled:
        return False
    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        return False
    return True


def structured_generate(
    settings: Settings,
    *,
    system: str,
    user: str,
    schema: type[T],
) -> T | None:
    """Ask the LLM for a JSON object matching ``schema``. Returns None on failure."""
    if not llm_available(settings):
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    try:
        model = ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )
        # Prefer native structured output when available
        try:
            structured = model.with_structured_output(schema)
            result = structured.invoke(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            if isinstance(result, schema):
                return result
            if isinstance(result, dict):
                return schema.model_validate(result)
        except Exception:
            pass

        raw = model.invoke(
            [
                {"role": "system", "content": system + "\nRespond with JSON only."},
                {"role": "user", "content": user},
            ]
        )
        content = getattr(raw, "content", str(raw))
        data = _extract_json(content)
        if data is None:
            return None
        return schema.model_validate(data)
    except Exception:
        return None


def _extract_json(text: str) -> Any | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
