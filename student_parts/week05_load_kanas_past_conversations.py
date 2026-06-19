from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG
from fixed.external_mcp import call_external_tool_payload
from fixed.llm import chat_model
from fixed.mcp_client import (
    call_local_mcp_tool,
    call_local_mcp_tool_sync,
    load_local_mcp_tools,
    load_local_mcp_tools_sync,
)
from fixed.runtime_clock import current_app_date_iso
from fixed.student_api import (
    collect_member_schedules_payload,
    json_payload,
)
from student_parts.week01_wake_up_nana import PERSONAL_SCHEDULES, ensure_demo_personal_schedule
from student_parts.week04_retrieve_nanas_memory import week04_tools


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
#      - call_mcp_tool_sync("search_previous_conversations", args)를 호출하고 결과 문자열을 그대로 반환합니다.
#      - 멤버 이름 정규화는 외부 SQLite store/MCP 경계에서 한 번만 처리합니다.
#
#   2. load_conversation_messages
#      - conversation_id로 외부 SQLite/MCP helper에서 이전 대화 메시지를 조회합니다.
#      - 대화 메시지의 speaker/content/created_at 순서가 보존되도록 결과를 가공하지 않습니다.
#
#   3. extract_schedules_from_history
#      - member_names, date_from, date_to를 받습니다.
#      - 수업용 fixture 날짜 범위 보정은 외부 SQLite store/MCP 경계에서 한 번만 처리합니다.
#      - 결과 rows는 member_name/title/date/start_time/end_time/notes 필드를 유지해야 합니다.
#
#   4. create_shared_schedule / delete_shared_schedule / list_shared_schedules
#      - 내 일정이 외부 공유 일정 저장소에도 보이도록 생성/삭제/조회 MCP tool을 호출합니다.
#      - schedule_id 또는 source_conversation_id를 보존해야 나중에 수정/삭제 동기화가 가능합니다.
#      - 공유 저장소 자체를 확인할 때는 list_shared_schedules로 "나"를 포함한 등록 row를 조회합니다.
#
#   5. collect_member_schedules
#      - 내 일정은 PERSONAL_SCHEDULES를 이 tool 안에서 날짜 범위로 필터링합니다.
#      - 외부 멤버 일정은 MCP extract_schedules_from_history 결과를 이 tool 안에서 읽습니다.
#      - 두 출처를 member_name/title/date/start_time/end_time/notes가 있는 rows 배열로 직접 합칩니다.
#      - schedule_summary도 함께 반환해 LLM이 바쁜 시간을 자연어로 설명할 수 있게 합니다.
#
# 책임 경계
#   mcp_server/sqlite_mcp_server.py의 @mcp.tool 구현은 학생 구현 대상이 아닙니다.
#   이 파일의 wrapper tool은 직접 SQL이나 중복 정규화 helper를 두지 않고 store/MCP helper의 결과 JSON을 전달합니다.
#   week05_tools()는 Week 1-4 도구에 외부 SQLite/MCP 일정 도구를 누적합니다.
#
# 검증 방법
#   ./run.sh --week5에서 외부 팀원 일정 조회 요청을 입력합니다.
#   trace에서 search_previous_conversations, load_conversation_messages, extract_schedules_from_history 중
#   어떤 tool이 어떤 순서로 호출됐는지 확인합니다.
#   collect_member_schedules 결과 rows에 "나"와 외부 멤버 일정이 같은 구조로 들어 있는지도 확인합니다.


call_mcp_tool = call_local_mcp_tool
call_mcp_tool_sync = call_local_mcp_tool_sync
load_langchain_mcp_tools = load_local_mcp_tools
load_langchain_mcp_tools_sync = load_local_mcp_tools_sync


@tool
def search_previous_conversations(
    query: str,
    member_names: list[str] | None = None,
    limit: int = 5,
) -> str:
    """외부 SQLite 데이터베이스에 저장된 이전 대화를 검색합니다."""

    return call_mcp_tool_sync(
        "search_previous_conversations",
        {"query": query, "member_names": member_names, "limit": limit},
    )


@tool
def load_conversation_messages(conversation_id: str) -> str:
    """외부 SQLite 데이터베이스에서 특정 이전 대화의 모든 메시지를 불러옵니다."""

    return json_payload(
        call_external_tool_payload("load_conversation_messages", {"conversation_id": conversation_id})
    )


@tool
def extract_schedules_from_history(member_names: list[str], date_from: str, date_to: str) -> str:
    """외부 SQLite 이전 대화에서 멤버별 일정을 추출합니다."""

    return call_mcp_tool_sync(
        "extract_schedules_from_history",
        {
            "member_names": member_names,
            "date_from": date_from,
            "date_to": date_to,
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
def list_shared_schedules(
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_conversation_id: str | None = None,
    limit: int = 50,
) -> str:
    """외부 MCP 공유 일정 저장소에 등록된 일정을 조회합니다."""

    return call_mcp_tool_sync(
        "list_shared_schedules",
        {
            "member_names": member_names,
            "date_from": date_from,
            "date_to": date_to,
            "source_conversation_id": source_conversation_id,
            "limit": limit,
        },
    )


@tool
def collect_member_schedules(member_names: list[str], date_from: str, date_to: str) -> str:
    """내 일정과 다른 사람들의 일정을 MCP SQLite 기록에서 모읍니다."""

    ensure_demo_personal_schedule()
    return json_payload(
        collect_member_schedules_payload(
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            personal_schedules=PERSONAL_SCHEDULES,
        )
    )


def week05_tools() -> list[Any]:
    """4주차까지의 도구에 외부 SQLite/MCP 일정 도구를 누적한 목록입니다."""

    return [
        *week04_tools(),
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        create_shared_schedule,
        delete_shared_schedule,
        list_shared_schedules,
        collect_member_schedules,
    ]


def week05_system_prompt() -> str:
    """5주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return (
        "너는 Kanana의 Week 5 Kana history agent다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "개인 일정/저장/RAG 요청은 Week 1-4 tool chain을 사용한다. "
        "외부 멤버의 이전 대화나 일정 추출이 필요하면 search_previous_conversations, "
        "load_conversation_messages, extract_schedules_from_history를 사용한다. "
        "공유 일정 저장소에 등록된 row 자체를 확인해야 하면 list_shared_schedules를 사용한다. "
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
