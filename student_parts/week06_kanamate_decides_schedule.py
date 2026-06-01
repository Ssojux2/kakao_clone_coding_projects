from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

from fixed.config import CONFIG
from fixed.runtime_clock import current_app_date_iso
from golden_cases import harness_prompt_examples
from student_parts.week01_wake_up_nana import (
    ensure_demo_personal_schedule,
    list_personal_schedule_dicts,
    personal_create_schedule,
    personal_delete_schedule,
    personal_list_schedules,
    week01_tools,
)
from student_parts.week02_structure_natural_language_requests import extract_structured_request, week02_tools
from student_parts.week03_build_nanas_logbook import (
    delete_saved_schedules_dict,
    get_saved_request,
    list_saved_requests,
    personal_delete_saved_schedules,
    personal_list_saved_schedules,
    save_structured_request,
    week03_tools,
)
from student_parts import week03_build_nanas_logbook as week03_store
from student_parts.week04_retrieve_nanas_memory import (
    add_personal_reference,
    search_nana_memory,
    week04_tools,
)
from student_parts.week05_load_kanas_past_conversations import (
    _normalize_members,
    collect_member_schedules,
    extract_schedules_from_history,
    load_conversation_messages,
    search_previous_conversations,
    week05_tools,
)


_NANA_SUBAGENT: Any | None = None
_KANA_SUBAGENT: Any | None = None


def delete_schedule_by_query_dict(query: str, app_store: Any | None = None) -> dict[str, Any]:
    """기존 Week 6 import 호환을 유지하며 Week 3 삭제 헬퍼를 호출합니다."""

    original = week03_store.extract_structured_request
    week03_store.extract_structured_request = extract_structured_request
    try:
        return week03_store.delete_schedule_by_query_dict(query, app_store=app_store)
    finally:
        week03_store.extract_structured_request = original


@tool
def personal_delete_schedule_by_query(query: str) -> str:
    """일정 ID가 없어도 사용자 프롬프트의 날짜, 시간, 제목 단서로 개인 일정을 찾아 삭제합니다."""

    return json.dumps(delete_schedule_by_query_dict(query), ensure_ascii=False)


def _chat_model() -> ChatOpenAI:
    if not CONFIG.has_openai_key:
        raise RuntimeError("OPENAI_API_KEY가 .env에 필요합니다.")
    return ChatOpenAI(model=CONFIG.openai_model, temperature=0)


def _harness_examples_text() -> str:
    examples = [example for example in harness_prompt_examples() if example["week"] <= CONFIG.active_week]
    return json.dumps(examples, ensure_ascii=False, indent=2)


def _nana_capability_text() -> str:
    parts = [
        "Week 1 개인 일정 생성/조회/삭제는 personal_create_schedule, personal_list_schedules, "
        "personal_delete_schedule을 사용한다."
    ]
    if CONFIG.active_week >= 2:
        parts.append("Week 2 날짜/시간/종류/멤버 판단이 필요하면 extract_schedule_request를 호출한다.")
    if CONFIG.active_week >= 3:
        parts.append(
            "Week 3 저장/조회는 save_structured_request, list_saved_requests, get_saved_request를 사용한다."
        )
        parts.append(
            "일정 삭제 요청이면 personal_list_saved_schedules로 후보를 확인하고 "
            "personal_delete_saved_schedules를 호출한다."
        )
    if CONFIG.active_week >= 4:
        parts.append(
            "Week 4 RAG 검색은 search_nana_memory 하나를 사용한다. 사용자 질문 전체가 아니라 "
            "네가 고른 핵심 키워드/날짜/참석자를 넣고, 반환된 reference_hits, schedule_chunks, context를 근거로 답한다."
        )
        parts.append("개인 참고자료 추가가 필요할 때만 add_personal_reference를 사용한다.")
    return " ".join(parts)


def _nana_workflow_text() -> str:
    if CONFIG.active_week <= 1:
        return "개인 일정 생성 요청이면 사용자의 프롬프트에서 필요한 값을 읽어 personal_create_schedule을 호출한다."
    if CONFIG.active_week == 2:
        return (
            "개인 일정 생성 요청이면 먼저 extract_schedule_request로 날짜/시간/제목을 구조화하고, "
            "그 결과를 바탕으로 personal_create_schedule을 호출한다."
        )
    return (
        "개인 일정 생성 요청이면 extract_schedule_request 결과를 바탕으로 personal_create_schedule을 호출하고, "
        "personal_create_schedule 결과의 structured_request를 save_structured_request payload로 전달해 앱 DB에 저장한다."
    )


def _kana_capability_text() -> str:
    if CONFIG.active_week < 5:
        return "Kana 도구는 Week 5부터 열린다."
    parts = [
        "먼저 extract_schedule_request로 날짜와 멤버를 구조화한다.",
        "이전 대화 원문이 필요하면 search_previous_conversations나 load_conversation_messages를 쓴다.",
        "멤버별 바쁜 시간은 extract_schedules_from_history 또는 collect_member_schedules로 확인한다.",
    ]
    if CONFIG.active_week >= 6:
        parts.append(
            "공통 후보 시간 계산은 find_common_available_slots를 사용하고, 선택한 시간을 "
            "selected_slot으로 만들어 propose_group_schedule에 전달한다."
        )
    return " ".join(parts)


def nana_system_prompt() -> str:
    return (
        "너는 Kanana의 Nana 하위 에이전트다. 사용자의 프롬프트를 기준으로 필요한 도구를 직접 선택한다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "오늘/내일/다음 주 같은 상대 날짜는 이 날짜를 기준으로 해석한다. "
        "코드가 주차나 기능을 대신 고르지 않으므로 네가 프롬프트를 읽고 필요한 tool chain을 선택한다. "
        f"{_nana_capability_text()} "
        f"{_nana_workflow_text()} "
        "personal_delete_schedule_by_query는 이전 하네스 호환용 간편 도구로만 사용한다. "
        "요약, 후보 선택, 자연어 답변은 네가 맡고, 도구 결과에 없는 사실은 만들지 않는다. "
        "그룹 일정 조율, 여러 사람의 공통 가능 시간 계산은 직접 처리하지 말고 그 사실을 짧게 알린다. "
        "하네스 예시는 다음과 같다:\n"
        f"{_harness_examples_text()}"
    )


def kana_system_prompt() -> str:
    return (
        "너는 Kanana의 Kana 하위 에이전트다. 여러 사람의 일정을 조율한다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        f"{_kana_capability_text()} "
        "도구 결과에 없는 일정이나 시간을 만들지 않는다. 개인 일정만 요청하면 Nana 담당이라고 짧게 답한다. "
        "하네스 예시는 다음과 같다:\n"
        f"{_harness_examples_text()}"
    )


def supervisor_system_prompt() -> str:
    return (
        "너는 Kanana 일정 비서의 프롬프트 기반 supervisor 에이전트다. 메인 런타임이나 Python 코드가 "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "오늘/내일/다음 주 같은 상대 날짜는 이 날짜를 기준으로 해석한다. "
        "주차, 에이전트, 도구를 미리 고르지 않는다. 너는 사용자 프롬프트와 아래 하네스 예시를 읽고 "
        f"현재 활성 주차는 Week {CONFIG.active_week}이다. "
        "Week 1-4의 개인 일정/저장/RAG 흐름은 nana_agent에, Week 5-6의 여러 사람 일정/외부 대화/그룹 조율 흐름은 "
        "kana_agent에 맡긴다. 반드시 nana_agent 또는 kana_agent 도구 중 하나를 직접 호출한 뒤, "
        "그 도구 결과만 근거로 최종 답변을 작성한다. "
        "개인 일정 생성/조회/삭제, todo/reminder 저장, 개인 참고자료 검색은 nana_agent에게 위임한다. "
        "팀원, 그룹, 여러 사람, 모두의 일정 조율은 kana_agent에게 위임한다. "
        "단, 사용자가 '그 시간', '방금 정한 시간', '아까 제안한 일정'처럼 이전 답변의 특정 "
        "후보를 그대로 사용하라고 하면 kana_agent로 다시 재탐색하지 말고, 이전 대화에 나온 "
        "날짜와 시간을 명시적으로 포함해 nana_agent에 위임한다. 사용자가 다시 찾아달라고 "
        "요청한 경우에만 kana_agent로 재계산한다. "
        "최종 답변에서는 도구 결과와 이전 대화에 실제로 나온 시간만 말하고, 도구 결과와 다른 "
        "새 시간이나 상태를 만들어내지 않는다. "
        "사용자에게는 자연스럽게 답변하고, 에이전트 이름이나 도구 이름은 사용자가 묻지 않는 한 "
        "노출하지 않는다. 하네스 예시는 다음과 같다:\n"
        f"{_harness_examples_text()}"
    )


def _message_content_to_text(message: Any) -> str:
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


def _extract_final_text(result: dict[str, Any]) -> str:
    messages = result.get("messages", []) if isinstance(result, dict) else []
    for message in reversed(messages):
        text = _message_content_to_text(message)
        if text:
            return text
    return "응답을 생성하지 못했습니다."


def _extract_agent_trace(result: dict[str, Any]) -> list[dict[str, Any]]:
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
            parsed: Any = content
            try:
                parsed = json.loads(content)
            except Exception:
                pass
            events.append(
                {
                    "event": "tool_result",
                    "tool_name": getattr(message, "name", None),
                    "content": parsed,
                    "id": getattr(message, "tool_call_id", None),
                }
            )
    return events


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["tool_name"] for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def tool_name(tool_object: Any) -> str:
    return getattr(tool_object, "name", getattr(tool_object, "__name__", str(tool_object)))


@tool
def extract_schedule_request(query: str) -> str:
    """사용자 프롬프트를 일정 앱용 구조화 요청 JSON으로 변환합니다."""

    structured = extract_structured_request(query)
    return json.dumps(
        {
            "ok": True,
            "tool_name": "extract_schedule_request",
            "base_date": current_app_date_iso(),
            "structured_request": structured.model_dump(),
        },
        ensure_ascii=False,
    )


def _parse_time_minutes(value: str | None, fallback: int) -> int:
    if not value or value == "미정":
        return fallback
    try:
        hour_text, minute_text = value.split(":", 1)
        return int(hour_text) * 60 + int(minute_text)
    except (AttributeError, ValueError):
        return fallback


def _format_time_minutes(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _date_range(date_from: str, date_to: str) -> list[str]:
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    if end < start:
        start, end = end, start
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _busy_rows_overlap(rows: list[dict[str, Any]], day: str, start_minutes: int, end_minutes: int) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for row in rows:
        if row.get("date") != day:
            continue
        busy_start = _parse_time_minutes(row.get("start_time"), 0)
        busy_end = _parse_time_minutes(row.get("end_time"), 24 * 60)
        if start_minutes < busy_end and busy_start < end_minutes:
            blockers.append(row)
    return blockers


def find_common_available_slots_dict(
    member_names: list[str],
    date_from: str,
    date_to: str,
    duration_minutes: int = 60,
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    limit: int = 5,
) -> dict[str, Any]:
    """멤버별 busy-time rows를 공통 가능 시간 후보로 바꿉니다."""

    normalized_members = _normalize_members(member_names)
    collected = json.loads(
        collect_member_schedules.invoke(
            {
                "member_names": normalized_members,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
    )
    rows = collected.get("rows", [])
    start_minutes = _parse_time_minutes(workday_start, 9 * 60)
    end_minutes = _parse_time_minutes(workday_end, 18 * 60)
    duration = max(30, min(int(duration_minutes or 60), end_minutes - start_minutes))
    step = 30

    candidate_slots: list[dict[str, Any]] = []
    for day in _date_range(date_from, date_to):
        cursor = start_minutes
        while cursor + duration <= end_minutes:
            slot_end = cursor + duration
            blockers = _busy_rows_overlap(rows, day, cursor, slot_end)
            if not blockers:
                candidate_slots.append(
                    {
                        "date": day,
                        "start_time": _format_time_minutes(cursor),
                        "end_time": _format_time_minutes(slot_end),
                        "duration_minutes": duration,
                        "reason": "수집된 busy-time과 겹치지 않는 공통 가능 시간입니다.",
                    }
                )
                if len(candidate_slots) >= limit:
                    return {
                        "ok": True,
                        "tool_name": "find_common_available_slots",
                        "members": ["나", *normalized_members],
                        "busy_rows": rows,
                        "candidate_slots": candidate_slots,
                    }
            cursor += step

    return {
        "ok": True,
        "tool_name": "find_common_available_slots",
        "members": ["나", *normalized_members],
        "busy_rows": rows,
        "candidate_slots": candidate_slots,
    }


@tool
def find_common_available_slots(
    member_names: list[str],
    date_from: str,
    date_to: str,
    duration_minutes: int = 60,
    workday_start: str = "09:00",
    workday_end: str = "18:00",
    limit: int = 5,
) -> str:
    """수집된 멤버 일정에서 공통으로 비어 있는 후보 시간을 계산합니다."""

    return json.dumps(
        find_common_available_slots_dict(
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            duration_minutes=duration_minutes,
            workday_start=workday_start,
            workday_end=workday_end,
            limit=limit,
        ),
        ensure_ascii=False,
    )


def nana_tools() -> list[Any]:
    if CONFIG.active_week <= 1:
        return week01_tools()
    if CONFIG.active_week == 2:
        return week02_tools()
    if CONFIG.active_week == 3:
        return week03_tools()
    return week04_tools()


def kana_tools() -> list[Any]:
    if CONFIG.active_week < 5:
        return []
    tools = [
        extract_schedule_request,
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        collect_member_schedules,
    ]
    if CONFIG.active_week >= 6:
        tools.extend([find_common_available_slots, propose_group_schedule])
    return tools


def supervisor_tools() -> list[Any]:
    if CONFIG.active_week < 5:
        return [nana_agent]
    return [nana_agent, kana_agent]


def agent_tool_names(agent_name: str) -> list[str]:
    if agent_name == "nana_agent":
        return [tool_name(item) for item in nana_tools()]
    if agent_name == "kana_agent":
        return [tool_name(item) for item in kana_tools()]
    if agent_name == "supervisor":
        return [tool_name(item) for item in supervisor_tools()]
    return []


def build_nana_subagent() -> object:
    """개인 일정과 RAG 작업을 처리하는 프롬프트 기반 Nana 하위 에이전트를 만듭니다."""

    global _NANA_SUBAGENT
    if _NANA_SUBAGENT is None:
        _NANA_SUBAGENT = create_agent(
            model=_chat_model(),
            tools=nana_tools(),
            system_prompt=nana_system_prompt(),
        )
    return _NANA_SUBAGENT


def build_kana_subagent() -> object:
    """그룹 일정 조율을 처리하는 프롬프트 기반 Kana 하위 에이전트를 만듭니다."""

    global _KANA_SUBAGENT
    if _KANA_SUBAGENT is None:
        _KANA_SUBAGENT = create_agent(
            model=_chat_model(),
            tools=kana_tools(),
            system_prompt=kana_system_prompt(),
        )
    return _KANA_SUBAGENT


@tool
def propose_group_schedule(
    title: str,
    member_names: list[str],
    candidate_slots: list[dict[str, Any]] | None = None,
    selected_slot: dict[str, Any] | None = None,
    reason: str | None = None,
) -> str:
    """Kana가 고른 후보 시간으로 최종 그룹 일정 결정 페이로드를 만듭니다."""

    slots = candidate_slots or []
    selected = selected_slot or (slots[0] if slots else None)
    payload = {
        "title": title,
        "members": _normalize_members(member_names),
        "selected_slot": selected,
        "status": "confirmed" if selected else "needs_manual_review",
        "reason": reason or (selected.get("reason") if selected else "공통 가능 시간을 찾지 못했습니다."),
    }
    return json.dumps({"ok": True, "tool_name": "propose_group_schedule", "final_decision": payload}, ensure_ascii=False)


@tool
def nana_agent(query: str) -> str:
    """개인 일정과 개인 RAG 작업을 프롬프트 기반 Nana 하위 에이전트에게 위임합니다."""

    if not CONFIG.has_openai_key:
        return json.dumps(
            {
                "ok": False,
                "selected_agent": "nana_agent",
                "error": "missing_openai_api_key",
                "answer": "Nana 하위 에이전트는 프롬프트 기반 도구 호출로 동작하므로 OPENAI_API_KEY가 필요합니다.",
                "trace": [],
                "inner_tool_names": [],
                "mode": "prompt_driven_subagent",
            },
            ensure_ascii=False,
        )
    result = build_nana_subagent().invoke({"messages": [{"role": "user", "content": query}]})
    trace = _extract_agent_trace(result)
    return json.dumps(
        {
            "ok": True,
            "selected_agent": "nana_agent",
            "answer": _extract_final_text(result),
            "trace": trace,
            "inner_tool_names": _tool_call_names(trace),
            "mode": "prompt_driven_subagent",
        },
        ensure_ascii=False,
    )


@tool
def kana_agent(query: str) -> str:
    """그룹 일정 종합 작업을 프롬프트 기반 Kana 하위 에이전트에게 위임합니다."""

    if not CONFIG.has_openai_key:
        return json.dumps(
            {
                "ok": False,
                "selected_agent": "kana_agent",
                "error": "missing_openai_api_key",
                "answer": "Kana 하위 에이전트는 프롬프트 기반 도구 호출로 동작하므로 OPENAI_API_KEY가 필요합니다.",
                "trace": [],
                "inner_tool_names": [],
                "final_decision_payload": None,
                "mode": "prompt_driven_subagent",
            },
            ensure_ascii=False,
        )
    result = build_kana_subagent().invoke({"messages": [{"role": "user", "content": query}]})
    trace = _extract_agent_trace(result)
    final_decision = None
    for event in trace:
        content = event.get("content")
        if isinstance(content, dict) and content.get("final_decision"):
            final_decision = content["final_decision"]
    return json.dumps(
        {
            "ok": True,
            "selected_agent": "kana_agent",
            "answer": _extract_final_text(result),
            "trace": trace,
            "inner_tool_names": _tool_call_names(trace),
            "final_decision_payload": final_decision,
            "mode": "prompt_driven_subagent",
        },
        ensure_ascii=False,
    )


def build_langchain_supervisor_agent() -> object:
    """nana_agent와 kana_agent 위임 도구만 노출하는 LangChain v1 슈퍼바이저입니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("OPENAI_API_KEY가 .env에 필요합니다.")
    return create_agent(
        model=_chat_model(),
        tools=supervisor_tools(),
        system_prompt=supervisor_system_prompt(),
    )
