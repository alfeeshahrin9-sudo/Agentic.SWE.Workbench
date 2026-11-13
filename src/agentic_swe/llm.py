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


def create_chat_model(settings: Settings) -> Any | None:
    """Instantiate a ChatOpenAI-compatible client (OpenAI, Ollama, GitHub Models, Groq, Gemini)."""
    if not llm_available(settings):
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None

    kwargs: dict[str, Any] = {
        "model": settings.openai_model,
        "api_key": settings.resolved_api_key,
        "temperature": 0,
    }
    if settings.resolved_base_url:
        kwargs["base_url"] = settings.resolved_base_url
    return ChatOpenAI(**kwargs)


def structured_generate(
    settings: Settings,
    *,
    system: str,
    user: str,
    schema: type[T],
) -> T | None:
    """Ask the LLM for a JSON object matching ``schema``. Returns None on failure."""
    model = create_chat_model(settings)
    if model is None:
        return None

    try:
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


def run_tool_calling_agent(
    settings: Settings,
    *,
    system: str,
    user: str,
    tools: list[Any],
    max_steps: int = 6,
) -> list[dict[str, Any]] | None:
    """Run an LLM tool-calling loop over MCP / sandbox tools.

    Returns the list of executed tool-call records, or None if unavailable/failed.
    """
    model = create_chat_model(settings)
    if model is None or not tools:
        return None

    try:
        from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

        tool_map = {t.name: t for t in tools}
        bound = model.bind_tools(tools)
        messages: list[Any] = [SystemMessage(content=system), HumanMessage(content=user)]
        executed: list[dict[str, Any]] = []

        for _ in range(max_steps):
            ai_msg = bound.invoke(messages)
            messages.append(ai_msg)
            tool_calls = getattr(ai_msg, "tool_calls", None) or []
            if not tool_calls:
                break
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("args") or {}
                call_id = tc.get("id") or name
                tool_obj = tool_map.get(name)
                if tool_obj is None:
                    output = f"Error: unknown tool '{name}'"
                else:
                    try:
                        output = tool_obj.invoke(args)
                    except Exception as exc:
                        output = f"Error calling {name}: {exc}"
                executed.append({"tool": name, "args": args, "output": output})
                messages.append(
                    ToolMessage(
                        content=json.dumps(output) if not isinstance(output, str) else output,
                        tool_call_id=str(call_id),
                    )
                )
        return executed
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
