"""MCP tools: agent."""
from __future__ import annotations

import inspect
import os

from ..browser import locked_tool
from ..normalize import _dumps
from ..security import (
    agent_task_error,
    clamp_max_steps,
    model_name_allowed,
    scope_agent_task,
)


async def run_browser_use_task(
    task: str,
    max_steps: int = 25,
    model: str = "gpt-4o-mini",
    headless: bool = True,
) -> str:
    """
    Run an autonomous browser-use agent for complex multi-step tasks on Infinite Backlog.
    Prefer the deterministic tools for simple reads/clicks. The agent is scoped to
    infinitebacklog.net and will refuse tasks that contain a non-IB URL.

    Requires: pip install browser-use  +  an LLM API key in the environment
    (OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, or BROWSER_USE_API_KEY).

    Examples:
      - "Go to infinitebacklog.net, search for Hades, and summarize the first result"
      - "Open my collection page and list unfinished RPGs" (needs a signed-in Playwright session)
    """
    rejected = agent_task_error(task)
    if rejected:
        return _dumps({"error": "agent_url_rejected", "hint": rejected})
    if not model_name_allowed(model):
        return _dumps({"error": "invalid_model", "hint": "Model name must not contain a URL."})
    steps = clamp_max_steps(max_steps)

    try:
        from browser_use import Agent
    except ImportError:
        return (
            "browser-use is not installed. Install with:\n"
            "  pip install browser-use\n"
            "  python -m playwright install chromium\n"
            "Then set OPENAI_API_KEY (or another supported provider key)."
        )

    llm = None
    try:
        if os.environ.get("BROWSER_USE_API_KEY"):
            from browser_use import ChatBrowserUse
            llm = ChatBrowserUse(model=model if "/" in model else f"openai/{model}")
        elif os.environ.get("OPENAI_API_KEY"):
            from browser_use import ChatOpenAI
            llm = ChatOpenAI(model=model)
        elif os.environ.get("ANTHROPIC_API_KEY"):
            from browser_use import ChatAnthropic
            llm = ChatAnthropic(model=model if model.startswith("claude") else "claude-sonnet-4-20250514")
        elif os.environ.get("GOOGLE_API_KEY"):
            from browser_use import ChatGoogle
            llm = ChatGoogle(model=model if "gemini" in model else "gemini-2.0-flash")
        else:
            return (
                "No LLM API key found. Set one of:\n"
                "  OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, or BROWSER_USE_API_KEY"
            )
    except Exception as e:
        return f"Failed to create LLM client: {e}"

    scoped_task = scope_agent_task(task)

    try:
        from browser_use import BrowserProfile

        profile_kwargs = {"headless": headless}
        try:
            params = inspect.signature(BrowserProfile).parameters
            if "allowed_domains" in params:
                profile_kwargs["allowed_domains"] = ["infinitebacklog.net", "www.infinitebacklog.net"]
        except (TypeError, ValueError):
            pass
        profile = BrowserProfile(**profile_kwargs)
    except Exception:
        profile = None

    try:
        agent_kwargs = {
            "task": scoped_task,
            "llm": llm,
            "use_vision": True,
            "max_failures": 3,
            "max_actions_per_step": 4,
        }
        if profile is not None:
            agent_kwargs["browser_profile"] = profile

        agent = Agent(**agent_kwargs)
        history = await agent.run(max_steps=steps)

        final = None
        if hasattr(history, "final_result"):
            try:
                final = history.final_result()
            except Exception:
                pass
        if final:
            return str(final)[:15000]

        if hasattr(history, "history") and history.history:
            last = history.history[-1]
            if hasattr(last, "result") and last.result:
                return str(last.result)[:15000]
        return str(history)[:15000]
    except Exception as e:
        return f"browser-use agent failed: {type(e).__name__}: {e}"


def register(mcp) -> None:
    mcp.tool()(locked_tool(run_browser_use_task))
