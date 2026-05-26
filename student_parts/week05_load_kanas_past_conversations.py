from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from langchain.tools import tool

from fixed.config import CONFIG, PACKAGE_ROOT
from fixed.stores import ExternalPeopleSQLiteStore
from student_parts.week01_wake_up_nana import ensure_demo_personal_schedule, list_personal_schedule_dicts
from student_parts.week04_retrieve_nanas_memory import week04_tools


EXTERNAL_STORE = ExternalPeopleSQLiteStore(CONFIG.external_db_path)
MEMBER_ALIAS = {"A": "민준", "B": "서연", "C": "지훈"}


def _normalize_members(member_names: list[str]) -> list[str]:
    normalized = [MEMBER_ALIAS.get(name, name) for name in member_names]
    return normalized or ["민준", "서연", "지훈"]


@tool
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 SQLite 데이터베이스에 저장된 이전 대화를 검색합니다."""

    # [5주차][학생 구현]
    # 에이전트 코드가 DB를 직접 뒤지지 않고 MCP SQLite 도구를 호출해 이전 대화를 검색하도록 만드세요.
    #
    # [참고 답안]
    rows = EXTERNAL_STORE.search_previous_conversations(query=query, member_names=member_names or None, limit=limit)
    return json.dumps({"ok": True, "tool_name": "search_previous_conversations", "rows": rows}, ensure_ascii=False)


@tool
def load_conversation_messages(conversation_id: str) -> str:
    """외부 SQLite 데이터베이스에서 특정 이전 대화의 모든 메시지를 불러옵니다."""

    # [5주차][학생 구현]
    # conversation_id로 외부 SQLite 대화 메시지를 시간순으로 조회하세요.
    #
    # [참고 답안]
    rows = EXTERNAL_STORE.load_conversation_messages(conversation_id=conversation_id)
    return json.dumps({"ok": True, "tool_name": "load_conversation_messages", "rows": rows}, ensure_ascii=False)


@tool
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 SQLite 이전 대화에서 멤버별 일정을 추출합니다."""

    # [5주차][학생 구현]
    # 멤버 이름과 날짜 범위로 외부 SQLite에 저장된 각자의 일정을 추출하세요.
    #
    # [참고 답안]
    rows = EXTERNAL_STORE.extract_schedules_from_history(
        member_names=member_names,
        date_from=date_from,
        date_to=date_to,
    )
    return json.dumps({"ok": True, "tool_name": "extract_schedules_from_history", "rows": rows}, ensure_ascii=False)


@tool
def collect_member_schedules(member_names: list[str], date_from: str, date_to: str) -> str:
    """내 일정과 다른 사람들의 일정을 MCP SQLite 기록에서 모읍니다."""

    # [5주차 -> 6주차 누적 사용]
    # 내 개인 일정은 1주차 Nana 도구에서, 다른 사람들의 일정은 5주차 외부 SQLite 도구에서 모아옵니다.
    ensure_demo_personal_schedule()
    normalized_members = _normalize_members(member_names)
    my_rows = [
        {
            "member_name": "나",
            "title": row["title"],
            "date": row["date"],
            "start_time": row["start_time"],
            "end_time": row["end_time"] if row["end_time"] != "미정" else "18:00",
            "notes": "Nana 개인 일정",
        }
        for row in list_personal_schedule_dicts(date_from=date_from, date_to=date_to)
    ]
    external_rows = extract_schedules_from_history_dict(
        member_names=normalized_members,
        date_from=date_from,
        date_to=date_to,
    )
    return json.dumps(
        {
            "ok": True,
            "tool_name": "collect_member_schedules",
            "members": ["나", *normalized_members],
            "rows": [*my_rows, *external_rows],
        },
        ensure_ascii=False,
    )


async def load_langchain_mcp_tools() -> list[Any]:
    """LangChain MCP 어댑터로 로컬 MCP 서버의 SQLite 도구를 불러옵니다."""

    from langchain_mcp_adapters.client import MultiServerMCPClient

    server_path = PACKAGE_ROOT / "mcp_server" / "sqlite_mcp_server.py"
    env = os.environ.copy()
    env["KANANA_EXTERNAL_DB_PATH"] = str(CONFIG.external_db_path)
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


def load_langchain_mcp_tools_sync() -> list[Any]:
    try:
        return asyncio.run(load_langchain_mcp_tools())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(load_langchain_mcp_tools())
        finally:
            loop.close()


def search_previous_conversations_dict(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    return json.loads(
        search_previous_conversations.invoke({"query": query, "member_names": member_names, "limit": limit})
    )["rows"]


def extract_schedules_from_history_dict(member_names: list[str], date_from: str, date_to: str) -> list[dict[str, Any]]:
    return json.loads(
        extract_schedules_from_history.invoke(
            {"member_names": member_names, "date_from": date_from, "date_to": date_to}
        )
    )["rows"]


def week05_tools() -> list[Any]:
    """4주차까지의 도구에 외부 SQLite/MCP 일정 도구를 누적한 목록입니다."""

    return [
        *week04_tools(),
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        collect_member_schedules,
    ]
