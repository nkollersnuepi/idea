"""Thin wrapper over the Anthropic SDK used by every agent.

- Structured output via `output_format=<pydantic model>` (validated JSON).
- Streaming for every call so long outputs never hit HTTP timeouts.
- Server-side refusal fallback (`fallbacks="default"`) is on by default.
- `research()` gives an agent Claude's server-side web_search + web_fetch tools.
"""

from __future__ import annotations

import logging
import os
from typing import TypeVar

import anthropic
from pydantic import BaseModel

log = logging.getLogger("radar.llm")
T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
USE_FALLBACKS = os.environ.get("RADAR_FALLBACKS", "1") != "0"


class AgentRefused(RuntimeError):
    pass


class LLM:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def _extra(self) -> dict:
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"} if USE_FALLBACKS else {}

    def _track(self, msg) -> None:
        self.usage["calls"] += 1
        u = getattr(msg, "usage", None)
        if u:
            self.usage["input_tokens"] += getattr(u, "input_tokens", 0) or 0
            self.usage["output_tokens"] += getattr(u, "output_tokens", 0) or 0

    @staticmethod
    def _check(msg) -> None:
        if msg.stop_reason == "refusal":
            details = getattr(msg, "stop_details", None)
            raise AgentRefused(f"model declined: {getattr(details, 'category', None)}")
        if msg.stop_reason == "max_tokens":
            log.warning("response hit max_tokens; output may be truncated")

    @staticmethod
    def _text(msg) -> str:
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def structured(self, *, model: str, effort: str, system: str, user: str,
                   schema: type[T], max_tokens: int = 64000) -> T:
        """One agent turn that must return an instance of `schema`."""
        try:
            with self.client.beta.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": effort},
                output_format=schema,
                **self._extra(),
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.BadRequestError as e:
            log.error("bad request (%s): %s", getattr(e, "request_id", ""), e.message)
            raise
        self._track(msg)
        self._check(msg)
        parsed = getattr(msg, "parsed_output", None)
        return parsed if isinstance(parsed, schema) else schema.model_validate_json(self._text(msg))

    def research(self, *, model: str, effort: str, system: str, user: str,
                 max_searches: int = 5, max_fetches: int = 5, max_tokens: int = 64000) -> str:
        """Agent turn with Claude-hosted web_search/web_fetch. Returns the final prose with sources."""
        tools = [
            {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
            {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": max_fetches},
        ]
        messages: list = [{"role": "user", "content": user}]
        for _ in range(6):  # pause_turn continuations
            with self.client.beta.messages.stream(
                model=model, max_tokens=max_tokens, system=system, messages=messages,
                tools=tools, output_config={"effort": effort}, **self._extra(),
            ) as stream:
                msg = stream.get_final_message()
            self._track(msg)
            self._check(msg)
            if msg.stop_reason != "pause_turn":
                return self._collect(msg)
            messages = messages + [{"role": "assistant", "content": msg.content}]
        return self._collect(msg)

    @staticmethod
    def _collect(msg) -> str:
        """Final text plus every URL the server tools surfaced, so later stages can cite them."""
        parts, urls = [], []
        for b in msg.content:
            t = getattr(b, "type", "")
            if t == "text":
                parts.append(b.text)
                for c in getattr(b, "citations", None) or []:
                    u = getattr(c, "url", None)
                    if u:
                        urls.append(f"- {getattr(c, 'title', '') or ''} {u} :: {getattr(c, 'cited_text', '')[:300]}")
            elif t == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
                for r in b.content:
                    if getattr(r, "url", None):
                        urls.append(f"- {getattr(r, 'title', '')} {r.url} ({getattr(r, 'page_age', '') or ''})")
        out = "\n".join(parts)
        if urls:
            out += "\n\nSOURCES SEEN:\n" + "\n".join(dict.fromkeys(urls))
        return out
