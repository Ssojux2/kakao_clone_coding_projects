from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from threading import Thread
from typing import Any

from fixed.config import CONFIG, PACKAGE_ROOT


def _mcp_result_to_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
            else:
                text = getattr(item, "text", None) or getattr(item, "content", None)
            if text:
                parts.append(str(text))
        if parts:
            return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False)


def _run_coroutine_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[Any] = []
    errors: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


async def load_local_mcp_tools(db_path: str | Path | None = None) -> list[Any]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    server_path = PACKAGE_ROOT / "mcp_server" / "sqlite_mcp_server.py"
    env = os.environ.copy()
    selected_db_path = db_path or env.get("KANANA_EXTERNAL_DB_PATH") or CONFIG.external_db_path
    env["KANANA_EXTERNAL_DB_PATH"] = str(selected_db_path)
    client = MultiServerMCPClient(
        {
            "kanana_sqlite": {
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(server_path)],
                "env": env,
            }
        }
    )
    return await client.get_tools()


async def call_local_mcp_tool(tool_name: str, args: dict[str, Any], db_path: str | Path | None = None) -> str:
    tools = {item.name: item for item in await load_local_mcp_tools(db_path=db_path)}
    if tool_name not in tools:
        available = ", ".join(sorted(tools))
        raise ValueError(f"Unknown MCP tool {tool_name!r}. Available tools: {available}")
    return _mcp_result_to_text(await tools[tool_name].ainvoke(args))


def call_local_mcp_tool_sync(tool_name: str, args: dict[str, Any], db_path: str | Path | None = None) -> str:
    return _run_coroutine_sync(call_local_mcp_tool(tool_name=tool_name, args=args, db_path=db_path))
