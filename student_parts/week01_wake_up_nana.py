from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso, next_weekday_iso
from fixed.stores import new_id, now_iso


PERSONAL_SCHEDULES: list[dict[str, Any]] = []
_WEEK01_AGENT: Any | None = None


# [수강생 구현 가이드]
#
# 목표
#   Nana가 "내 일정 만들어줘/보여줘/지워줘" 같은 개인 일정 요청을 받았을 때
#   LLM이 직접 고를 수 있는 LangChain tool 3개를 완성합니다.
#
# 구현 대상
#   1. personal_create_schedule
#      - title/date/start_time/end_time/attendees 인자로 schedule dict를 만듭니다.
#      - id는 new_id("personal"), created_at은 now_iso()로 채웁니다.
#      - attendees가 None이면 빈 list로 바꿔 PERSONAL_SCHEDULES에 append합니다.
#      - 반환 JSON에는 ok, tool_name, created_schedule, structured_request를 넣습니다.
#
#   2. personal_list_schedules
#      - PERSONAL_SCHEDULES를 직접 수정하지 않고 조회만 합니다.
#      - date_from이 있으면 그 날짜 이상, date_to가 있으면 그 날짜 이하만 남깁니다.
#      - 반환 JSON에는 ok, tool_name, schedules를 넣습니다.
#
#   3. personal_delete_schedule
#      - schedule_id가 일치하지 않는 일정만 남겨 삭제를 표현합니다.
#      - 리스트 객체 자체는 유지해야 하므로 PERSONAL_SCHEDULES[:]에 새 목록을 대입합니다.
#      - 삭제 전후 길이 비교로 deleted 값을 만들고 JSON으로 반환합니다.
#
# 중요한 반환 규칙
#   LangChain tool은 문자열 반환이 가장 안정적입니다. dict를 만든 뒤 _json(...)으로 감싸세요.
#   structured_request는 Week 3 DB 저장 도구가 바로 읽는 표준 페이로드입니다.
#   kind/title/date/start_time/end_time/members/original_text/source_schedule_id를 유지하세요.
#
# 참고 코드
#   week01_system_prompt, week01_tools(), build_week_agent(), trace helper는 구현 대상이 아닙니다.
#   이 함수들은 "LLM이 어떤 tool을 볼 수 있는지"와 "trace를 어떻게 보여주는지"를 이해할 때 읽습니다.
#
# 검증 방법
#   앱을 ./run.sh --week1로 실행하고 채팅에 하네스 프롬프트를 넣습니다.
#   상세 trace에서 LLM이 personal_create_schedule/list/delete 중 어떤 tool을 골랐는지 확인합니다.
#   tool 결과 JSON에 created_schedule, schedules, deleted, structured_request가 있는지도 확인합니다.


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def message_content_to_text(message: Any) -> str:
    """LangChain message나 dict payload에서 최종 답변 텍스트를 꺼냅니다."""

    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


def normalize_messages_value(value: Any) -> list[Any]:
    """LangChain stream chunk의 messages 값을 항상 list로 정규화합니다."""

    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value is None:
        return []
    return [value]


def stream_chunk_messages(chunk: Any) -> list[Any]:
    """LangChain stream update chunk에서 message 목록만 추출합니다."""

    if not isinstance(chunk, dict):
        return []
    if "messages" in chunk:
        return normalize_messages_value(chunk["messages"])

    messages: list[Any] = []
    for value in chunk.values():
        if isinstance(value, dict) and "messages" in value:
            messages.extend(normalize_messages_value(value["messages"]))
    return messages


def message_tool_call_names(message: Any) -> list[str]:
    """진행 상태 표시에 사용할 tool call 이름을 추출합니다."""

    tool_calls = getattr(message, "tool_calls", None) or []
    names: list[str] = []
    for call in tool_calls:
        if isinstance(call, dict) and call.get("name"):
            names.append(str(call["name"]))
    return names


def extract_final_text(result: dict[str, Any]) -> str:
    """LangChain 실행 결과의 마지막 비어 있지 않은 메시지를 최종 답변으로 사용합니다."""

    messages = result.get("messages", []) if isinstance(result, dict) else []
    for message in reversed(messages):
        text = message_content_to_text(message)
        if text:
            return text
    return "응답을 생성하지 못했습니다."


def extract_agent_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    """LangChain tool call/tool result 메시지를 trace 이벤트 배열로 변환합니다."""

    events: list[dict[str, Any]] = []
    messages = result.get("messages", []) if isinstance(result, dict) else []
    for message in messages:
        tool_calls = getattr(message, "tool_calls", None) or []
        for call in tool_calls:
            events.append(
                {
                    "event": "tool_call",
                    "tool_name": call.get("name"),
                    "arguments": call.get("args"),
                    "id": call.get("id"),
                }
            )
        if getattr(message, "type", "") == "tool":
            content = getattr(message, "content", "")
            parsed_content: Any = content
            try:
                parsed_content = json.loads(content)
            except Exception:
                pass
            events.append(
                {
                    "event": "tool_result",
                    "tool_name": getattr(message, "name", None),
                    "content": parsed_content,
                    "id": getattr(message, "tool_call_id", None),
                }
            )
    return events


def extract_langchain_trace(result: dict[str, Any]) -> dict[str, Any]:
    """Week 1-5가 공통으로 쓰는 기본 trace payload를 만듭니다."""

    return {"events": extract_agent_events(result)}


def _schedule_structured_request(schedule: dict[str, Any]) -> dict[str, Any]:
    """일정 정보를 표준 필드로 정리한 구조화 페이로드를 만듭니다."""

    return {
        "kind": "personal_schedule",
        "title": schedule["title"],
        "date": schedule["date"],
        "start_time": schedule["start_time"],
        "end_time": schedule["end_time"],
        "members": schedule["attendees"],
        "priority": None,
        "reason": "1주차 개인 일정 생성 도구가 일정 앱 공통 structured output으로 변환했습니다.",
        "original_text": schedule["title"],
        "source_schedule_id": schedule["id"],
    }


@tool
def personal_create_schedule(
    title: str,
    date: str,
    start_time: str,
    end_time: str = "미정",
    attendees: list[str] | None = None,
) -> str:
    """Nana의 개인 일정을 생성하고 저장된 일정 페이로드를 반환합니다."""

    schedule = {
        "id": new_id("personal"),
        "owner": "me",
        "title": title,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
        "attendees": attendees or [],
        "created_at": now_iso(),
    }
    PERSONAL_SCHEDULES.append(schedule)
    return _json(
        {
            "ok": True,
            "tool_name": "personal_create_schedule",
            "created_schedule": schedule,
            "structured_request": _schedule_structured_request(schedule),
        }
    )


@tool
def personal_list_schedules(date_from: str | None = None, date_to: str | None = None) -> str:
    """선택한 시작일과 종료일 범위에 포함되는 Nana의 개인 일정을 조회합니다."""

    schedules = [
        schedule
        for schedule in PERSONAL_SCHEDULES
        if (not date_from or schedule["date"] >= date_from) and (not date_to or schedule["date"] <= date_to)
    ]
    return _json({"ok": True, "tool_name": "personal_list_schedules", "schedules": schedules})


@tool
def personal_delete_schedule(schedule_id: str) -> str:
    """일정 ID에 해당하는 개인 일정을 삭제합니다."""

    before = len(PERSONAL_SCHEDULES)
    PERSONAL_SCHEDULES[:] = [schedule for schedule in PERSONAL_SCHEDULES if schedule["id"] != schedule_id]
    deleted = len(PERSONAL_SCHEDULES) != before
    return _json(
        {
            "ok": True,
            "tool_name": "personal_delete_schedule",
            "schedule_id": schedule_id,
            "deleted": deleted,
        }
    )


def week01_tools() -> list[Any]:
    """1주차에서 직접 구현한 개인 일정 CRUD 도구 목록입니다."""

    return [personal_create_schedule, personal_list_schedules, personal_delete_schedule]


def week01_system_prompt() -> str:
    """1주차 단일 Nana agent가 따르는 시스템 프롬프트입니다."""

    return (
        "너는 Kanana의 Week 1 Nana 일정 agent다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "사용자의 개인 일정 생성, 조회, 삭제 요청을 읽고 필요한 tool을 직접 선택한다. "
        "일정을 만들 때는 personal_create_schedule을 호출하고, 조회할 때는 personal_list_schedules를 호출한다. "
        "삭제할 schedule_id를 알고 있으면 personal_delete_schedule을 사용한다. "
        "Week 1에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 처리하지 않는다. "
        "도구 결과에 없는 사실은 만들지 말고, 사용자에게는 자연스럽게 한국어로 답한다."
    )


def build_week01_agent() -> object:
    """Week 1 tool 목록만 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK01_AGENT
    if _WEEK01_AGENT is None:
        _WEEK01_AGENT = create_agent(
            model=chat_model(),
            tools=week01_tools(),
            system_prompt=week01_system_prompt(),
        )
    return _WEEK01_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week01_agent()


def list_personal_schedule_dicts(date_from: str | None = None, date_to: str | None = None) -> list[dict[str, Any]]:
    """개인 일정 dict 목록이 필요한 내부 코드에서 사용하는 비-도구 헬퍼입니다."""

    schedules = json.loads(personal_list_schedules.invoke({"date_from": date_from, "date_to": date_to}))
    return schedules["schedules"]


def ensure_demo_personal_schedule() -> None:
    if PERSONAL_SCHEDULES:
        return
    personal_create_schedule.invoke(
        {
            "title": "개인 집중 작업",
            "date": next_weekday_iso(2),
            "start_time": "09:00",
            "end_time": "10:00",
            "attendees": [],
        }
    )
