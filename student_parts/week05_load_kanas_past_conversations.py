from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from threading import Thread
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG, PACKAGE_ROOT
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.stores import (
    ExternalPeopleSQLiteStore,
    external_schedule_summary,
    normalize_external_member_names,
    normalize_external_schedule_date_bounds,
)
from student_parts.week01_wake_up_nana import ensure_demo_personal_schedule, list_personal_schedule_dicts
from student_parts.week04_retrieve_nanas_memory import week04_tools


EXTERNAL_STORE = ExternalPeopleSQLiteStore(CONFIG.external_db_path)
_WEEK05_AGENT: Any | None = None


# [수강생 구현 가이드]
#
# 목표
#   외부 SQLite/MCP 서버에 있는 Kana의 이전 대화와 공유 일정을 LangChain agent가 사용할 수 있게 감쌉니다.
#   학생이 직접 SQL을 작성하는 주차가 아니라, MCP tool을 호출하는 wrapper tool을 만드는 주차입니다.
#
# 구현 대상
#   1. search_previous_conversations
#      - query, member_names, limit를 받습니다.
#      - member_names가 있으면 normalize_external_member_names로 외부 DB 기준 이름으로 맞춥니다.
#      - call_mcp_tool_sync("search_previous_conversations", args)를 호출하고 결과 문자열을 그대로 반환합니다.
#
#   2. load_conversation_messages
#      - conversation_id를 MCP load_conversation_messages tool에 넘깁니다.
#      - 대화 메시지의 speaker/content/created_at 순서가 보존되도록 결과를 가공하지 않습니다.
#
#   3. extract_schedules_from_history
#      - member_names, date_from, date_to를 받습니다.
#      - 이름과 날짜 범위를 수업용 fixture 기준으로 정규화한 뒤 MCP tool에 넘깁니다.
#      - 결과 rows는 member_name/title/date/start_time/end_time/notes 필드를 유지해야 합니다.
#
#   4. create_shared_schedule / delete_shared_schedule
#      - 내 일정이 외부 공유 일정 저장소에도 보이도록 생성/삭제 MCP tool을 호출합니다.
#      - schedule_id 또는 source_conversation_id를 보존해야 나중에 수정/삭제 동기화가 가능합니다.
#
#   5. collect_member_schedules
#      - 내 일정은 list_personal_schedule_dicts에서 가져옵니다.
#      - 외부 멤버 일정은 extract_schedules_from_history_dict에서 가져옵니다.
#      - 두 출처를 member_name/title/date/start_time/end_time/notes가 있는 같은 rows 배열로 합칩니다.
#      - schedule_summary도 함께 반환해 LLM이 바쁜 시간을 자연어로 설명할 수 있게 합니다.
#
# 책임 경계
#   mcp_server/sqlite_mcp_server.py의 @mcp.tool 구현은 학생 구현 대상이 아닙니다.
#   이 파일의 wrapper tool은 직접 SQL을 작성하지 않고 call_mcp_tool_sync로 MCP 결과 JSON을 전달합니다.
#   week05_tools()는 Week 1-4 도구에 외부 SQLite/MCP 일정 도구를 누적합니다.
#
# 검증 방법
#   ./run.sh --week5에서 외부 팀원 일정 조회 요청을 입력합니다.
#   trace에서 search_previous_conversations, load_conversation_messages, extract_schedules_from_history 중
#   어떤 tool이 어떤 순서로 호출됐는지 확인합니다.
#   collect_member_schedules 결과 rows에 "나"와 외부 멤버 일정이 같은 구조로 들어 있는지도 확인합니다.


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
    tools = {item.name: item for item in await load_langchain_mcp_tools(db_path=db_path)}
    if tool_name not in tools:
        available = ", ".join(sorted(tools))
        raise ValueError(f"Unknown MCP tool {tool_name!r}. Available tools: {available}")
    return _mcp_result_to_text(await tools[tool_name].ainvoke(args))


def call_mcp_tool_sync(tool_name: str, args: dict[str, Any], db_path: str | Path | None = None) -> str:
    return _run_coroutine_sync(call_mcp_tool(tool_name=tool_name, args=args, db_path=db_path))


@tool
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 SQLite 데이터베이스에 저장된 이전 대화를 검색합니다."""

    normalized_members = normalize_external_member_names(member_names) if member_names is not None else None
    return call_mcp_tool_sync(
        "search_previous_conversations",
        {"query": query, "member_names": normalized_members, "limit": limit},
    )


@tool
def load_conversation_messages(conversation_id: str) -> str:
    """외부 SQLite 데이터베이스에서 특정 이전 대화의 모든 메시지를 불러옵니다."""

    return call_mcp_tool_sync("load_conversation_messages", {"conversation_id": conversation_id})


@tool
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 SQLite 이전 대화에서 멤버별 일정을 추출합니다."""

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

    return [
        *week04_tools(),
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        create_shared_schedule,
        delete_shared_schedule,
        collect_member_schedules,
    ]


def week05_system_prompt() -> str:
    """5주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return (
        "너는 Kanana의 Week 5 Kana history agent다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "개인 일정/저장/RAG 요청은 Week 1-4 tool chain을 사용한다. "
        "외부 멤버의 이전 대화나 공유 일정이 필요하면 search_previous_conversations, "
        "load_conversation_messages, extract_schedules_from_history를 사용한다. "
        "내 일정과 외부 멤버 일정을 함께 모아야 하면 collect_member_schedules를 사용한다. "
        "내 일정이 공유 저장소에도 보여야 할 때는 create_shared_schedule/delete_shared_schedule을 사용한다. "
        "Week 5에서는 최종 회의 시간 결정 payload는 만들지 않고, 수집한 일정과 근거를 정리한다. "
        "도구 결과에 없는 일정이나 시간을 만들지 않는다."
    )


def build_week05_agent() -> object:
    """Week 1-5 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK05_AGENT
    if _WEEK05_AGENT is None:
        _WEEK05_AGENT = create_agent(
            model=chat_model(),
            tools=week05_tools(),
            system_prompt=week05_system_prompt(),
        )
    return _WEEK05_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week05_agent()
