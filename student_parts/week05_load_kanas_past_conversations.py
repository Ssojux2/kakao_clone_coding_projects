from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from threading import Thread
from typing import Any

from langchain.tools import tool

from fixed.config import CONFIG, PACKAGE_ROOT
from fixed.stores import (
    ExternalPeopleSQLiteStore,
    external_schedule_summary,
    normalize_external_member_names,
    normalize_external_schedule_date_bounds,
)
from student_parts.week01_wake_up_nana import ensure_demo_personal_schedule, list_personal_schedule_dicts
from student_parts.week04_retrieve_nanas_memory import week04_tools


EXTERNAL_STORE = ExternalPeopleSQLiteStore(CONFIG.external_db_path)


# [수강생 구현 가이드]
# Week 5의 핵심 실습은 외부 SQLite/MCP 서버를 LangChain tool처럼 불러와 감싸는 것입니다.
# 아래 @tool 함수들은 직접 SQL을 작성하기보다 call_mcp_tool_sync로 MCP tool을 호출하고, 그 결과를 agent가 읽을 JSON으로 전달합니다.
# collect_member_schedules는 Week 6 공통 시간 계산을 위해 "나 + 외부 멤버" busy-time rows를 합치는 연결 tool입니다.


def _normalize_members(member_names: list[str]) -> list[str]:
    return normalize_external_member_names(member_names)


def _mcp_result_to_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts: list[str] = []
        for item in result:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
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


async def call_mcp_tool(tool_name: str, args: dict[str, Any], db_path: str | Path | None = None) -> str:
    # [수강생 참고 코드 포인트]
    # 로컬 MCP 서버에서 tool 목록을 불러온 뒤 이름으로 선택해 ainvoke합니다.
    # 없는 tool 이름이 들어오면 사용 가능한 목록을 보여주는 오류를 내면 디버깅이 쉽습니다.
    tools = {item.name: item for item in await load_langchain_mcp_tools(db_path=db_path)}
    if tool_name not in tools:
        available = ", ".join(sorted(tools))
        raise ValueError(f"Unknown MCP tool {tool_name!r}. Available tools: {available}")
    return _mcp_result_to_text(await tools[tool_name].ainvoke(args))


def call_mcp_tool_sync(tool_name: str, args: dict[str, Any], db_path: str | Path | None = None) -> str:
    # [수강생 참고 코드 포인트]
    # LangChain tool 함수는 동기 함수로 쓰기 편하므로 async MCP 호출을 동기 wrapper로 감쌉니다.
    return _run_coroutine_sync(call_mcp_tool(tool_name=tool_name, args=args, db_path=db_path))


@tool
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 SQLite 데이터베이스에 저장된 이전 대화를 검색합니다."""

    # [수강생 구현 포인트]
    # member_names가 들어오면 외부 DB 기준 이름으로 정규화한 뒤 MCP의 search_previous_conversations tool에 넘깁니다.
    normalized_members = normalize_external_member_names(member_names) if member_names is not None else None
    return call_mcp_tool_sync(
        "search_previous_conversations",
        {"query": query, "member_names": normalized_members, "limit": limit},
    )


@tool
def load_conversation_messages(conversation_id: str) -> str:
    """외부 SQLite 데이터베이스에서 특정 이전 대화의 모든 메시지를 불러옵니다."""

    # [수강생 구현 포인트]
    # conversation_id 하나로 대화 전체를 불러오는 단순 wrapper입니다.
    return call_mcp_tool_sync("load_conversation_messages", {"conversation_id": conversation_id})


@tool
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 SQLite 이전 대화에서 멤버별 일정을 추출합니다."""

    # [수강생 구현 포인트]
    # 멤버 이름과 날짜 범위를 수업용 외부 데이터 기준으로 정규화한 뒤 MCP 일정 추출 tool에 전달합니다.
    normalized_date_from, normalized_date_to = normalize_external_schedule_date_bounds(
        member_names,
        date_from,
        date_to,
    )
    return call_mcp_tool_sync(
        "extract_schedules_from_history",
        {
            "member_names": _normalize_members(member_names),
            "date_from": normalized_date_from,
            "date_to": normalized_date_to,
        },
    )


@tool
def create_shared_schedule(
    member_name: str,
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    notes: str | None = None,
    source_conversation_id: str | None = None,
    schedule_id: str | None = None,
) -> str:
    """외부 MCP 공유 일정 저장소에 일정을 등록하거나 갱신합니다."""

    # [수강생 구현 포인트]
    # 내 일정이 공유 저장소에도 보여야 할 때 사용하는 wrapper입니다.
    # source_conversation_id와 schedule_id를 같이 넘기면 이후 수정/삭제 동기화가 쉬워집니다.
    return call_mcp_tool_sync(
        "create_shared_schedule",
        {
            "member_name": member_name,
            "title": title,
            "date": date,
            "start_time": start_time,
            "end_time": end_time,
            "notes": notes,
            "source_conversation_id": source_conversation_id,
            "schedule_id": schedule_id,
        },
    )


@tool
def delete_shared_schedule(
    schedule_id: str | None = None,
    source_conversation_id: str | None = None,
) -> str:
    """외부 MCP 공유 일정 저장소에서 일정을 삭제합니다."""

    # [수강생 구현 포인트]
    # schedule_id 또는 source_conversation_id 중 하나로 공유 일정 복사본을 삭제합니다.
    return call_mcp_tool_sync(
        "delete_shared_schedule",
        {
            "schedule_id": schedule_id,
            "source_conversation_id": source_conversation_id,
        },
    )


@tool
def collect_member_schedules(member_names: list[str], date_from: str, date_to: str) -> str:
    """내 일정과 다른 사람들의 일정을 MCP SQLite 기록에서 모읍니다."""

    # [수강생 구현 포인트]
    # 1. 내 개인 일정은 Week 1 Nana 도구에서 가져옵니다.
    # 2. 외부 멤버 일정은 Week 5 MCP tool에서 가져옵니다.
    # 3. 둘을 같은 row 모양으로 합쳐 Week 6 find_common_available_slots가 바로 읽게 만듭니다.
    ensure_demo_personal_schedule()
    normalized_members = _normalize_members(member_names)
    normalized_date_from, normalized_date_to = normalize_external_schedule_date_bounds(
        normalized_members,
        date_from,
        date_to,
    )
    my_rows = [
        {
            "member_name": "나",
            "title": row["title"],
            "date": row["date"],
            "start_time": row["start_time"],
            "end_time": row["end_time"] if row["end_time"] != "미정" else "18:00",
            "notes": "Nana 개인 일정",
        }
        for row in list_personal_schedule_dicts(date_from=normalized_date_from, date_to=normalized_date_to)
    ]
    external_rows = extract_schedules_from_history_dict(
        member_names=normalized_members,
        date_from=normalized_date_from,
        date_to=normalized_date_to,
    )
    return json.dumps(
        {
            "ok": True,
            "tool_name": "collect_member_schedules",
            "members": ["나", *normalized_members],
            "rows": [*my_rows, *external_rows],
            "schedule_summary": external_schedule_summary([*my_rows, *external_rows]),
        },
        ensure_ascii=False,
    )


async def load_langchain_mcp_tools(db_path: str | Path | None = None) -> list[Any]:
    """LangChain MCP 어댑터로 로컬 MCP 서버의 SQLite 도구를 불러옵니다."""

    # [수강생 참고 코드 포인트]
    # MultiServerMCPClient에 stdio transport, Python 실행 파일, MCP 서버 스크립트 경로, DB 경로 env를 넘깁니다.
    # 반환되는 객체들은 LangChain agent에 그대로 노출 가능한 tool입니다.
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


def load_langchain_mcp_tools_sync(db_path: str | Path | None = None) -> list[Any]:
    return _run_coroutine_sync(load_langchain_mcp_tools(db_path=db_path))


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

    # [수강생 참고 코드 포인트]
    # Week 4까지의 Nana tool에 외부 대화/공유 일정/MCP 수집 tool을 더합니다.
    return [
        *week04_tools(),
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        create_shared_schedule,
        delete_shared_schedule,
        collect_member_schedules,
    ]
