from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.tools import tool

from fixed.config import CONFIG
from fixed.external_people_store import normalize_external_member_names
from fixed.langchain_trace import extract_agent_events, extract_final_text
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from fixed.schedule_decision import (
    decide_final_slot_payload,
    find_common_available_slots_payload,
    normalize_date_bound,
)
from student_parts.week01_wake_up_nana import join_system_prompt
from student_parts.week02_structure_natural_language_requests import extract_schedule_request
from student_parts.week04_retrieve_nanas_memory import week04_prompt_parts, week04_tools
from student_parts.week05_load_kanas_past_conversations import (
    collect_member_schedules,
    extract_schedules_from_history,
    list_shared_schedules,
    load_conversation_messages,
    search_previous_conversations,
    week05_prompt_parts,
)


_NANA_SUBAGENT: Any | None = None
_KANA_SUBAGENT: Any | None = None
_SUPERVISOR_AGENT: Any | None = None


# [수강생 구현 가이드]
#
# 목표
#   Week 6은 "모든 기능을 한 agent가 직접 처리"하지 않고 supervisor가 Nana/Kana 하위 agent로 위임하게 만듭니다.
#   Nana는 개인 일정/저장/RAG를 맡고, Kana는 외부 대화/멤버 일정/그룹 시간 결정을 맡습니다.
#
# 구현 대상
#   1. decide_final_slot
#      - candidate_slots가 이미 들어오면 첫 번째 후보를 최종 시간으로 선택합니다.
#      - candidate_slots가 비어 있고 member_names/date_from/date_to가 있으면
#        find_common_available_slots_dict로 후보를 먼저 계산합니다.
#      - 반환 JSON은 course repo 기준 top-level final_slot, reason, candidates를 반드시 포함합니다.
#      - 후보 계산을 수행한 경우 members, busy_rows, candidate_slots도 함께 남겨 근거를 확인할 수 있게 합니다.
#
#   2. nana_agent
#      - supervisor가 넘긴 query로 Nana 하위 agent를 이 tool 안에서 만들거나 재사용해 실행합니다.
#      - 하위 agent 결과에서 answer, trace, inner_tool_names를 뽑아 JSON 문자열로 반환합니다.
#      - PROXY_TOKEN이 없으면 예외 대신 ok=False 실패 payload를 반환해 실습 화면이 깨지지 않게 합니다.
#
#   3. kana_agent
#      - supervisor가 넘긴 query로 Kana 하위 agent를 이 tool 안에서 만들거나 재사용해 실행합니다.
#      - 하위 trace를 훑어 decide_final_slot 결과를 final_slot_payload로 끌어올립니다.
#      - answer, trace, inner_tool_names, final_slot_payload, final_decision_payload를 JSON으로 반환합니다.
#
# 중요한 구조
#   Week 6 파일은 Week 1-5 구현을 다시 작성하지 않습니다.
#   이전 주차 tool을 import하고 kana_tools(), supervisor_tools()에서 역할별로 조립합니다.
#   prompt 함수와 busy-time 계산 helper는 구현 대상이 아니라 agent 역할과 데이터 흐름을 이해하는 참고 코드입니다.
#
# Compatibility helper
#   propose_group_schedule은 기존 흐름을 위해 유지합니다.
#   학생 핵심 구현 대상은 decide_final_slot, nana_agent, kana_agent 3개입니다.
#
# 검증 방법
#   ./run.sh --week6 또는 ./run.sh --golden을 실행합니다.
#   supervisor trace에서 nana_agent 또는 kana_agent 중 무엇이 선택됐는지 확인합니다.
#   그룹 일정 요청에서는 하위 trace에 search_previous_conversations, extract_schedules_from_history,
#   decide_final_slot이 이어지고 final_slot_payload가 최종 답변과 일치하는지 확인합니다.


def _nana_capability_text() -> str:
    parts = [
        "personal_create_schedule, personal_list_schedules, personal_delete_schedule은 Week 1-2 현재 대화 임시 메모리 도구다. "
        "Week 3 이후 Nana 하위 에이전트에서는 새 일정 저장이나 단순 일정 조회에 이 인메모리 도구들을 사용하지 않는다.",
        "Week 2 날짜/시간/종류/멤버 판단이 필요하면 extract_schedule_request를 호출한다.",
        "Week 3 이후 저장은 extract_schedule_request 결과의 structured_request를 바로 save_structured_request에 전달한다.",
        "저장된 요청 조회는 list_saved_requests/get_saved_request를 사용한다.",
        "저장된 일정 목록, 내 일정 조회, 기간 일정 조회 요청이면 personal_list_saved_schedules로 앱 SQLite row를 확인한다.",
        "특정 날짜나 기간의 내 일정 조회는 personal_list_saved_schedules의 date_from/date_to를 YYYY-MM-DD로 채운다.",
        "검색 tool의 query는 코드에서 토큰화하지 않으므로, 질문 전체가 아니라 네가 직접 고른 짧은 핵심 검색 문자열을 넣는다.",
        "사용자가 직전 질문에 이어 '지난 대화 검색해서 찾아줘'처럼 말하면 직전 질문의 대상 명사를 query로 삼는다.",
        "저장된 일정/할 일/알림 검색 질문이면 search_saved_requests의 rows를 근거로 답한다.",
        "내가 했던 대화 목록, 이전 채팅, 방금 다른 대화에서 말한 일반 발화 검색이면 "
        "search_conversation_messages의 rows를 근거로 답한다. search_saved_requests는 구조화된 일정/할 일/알림 전용이다.",
        "일반 채팅 발화 검색 결과가 비어 있으면 search_saved_requests로 넘어가지 말고, 같은 search_conversation_messages에 더 짧은 핵심어로 다시 검색한다.",
        "일정 삭제 요청이면 personal_list_saved_schedules로 후보를 확인하고 "
        "personal_delete_saved_schedules를 호출한다.",
        "일정 수정 요청이면 personal_list_saved_schedules로 내 앱 DB 일정 원본 후보를 확인하고 "
        "schedule_id를 고른 뒤 personal_update_saved_schedule을 호출한다. "
        "공유 일정은 내 일정 원본 수정 결과에 맞춰 자동 갱신되므로 공유 일정만 단독으로 고치지 않는다.",
        "Week 4 RAG 검색은 course repo 기준 tool인 search_personal_references와 search_saved_requests를 구분해 사용한다. "
        "개인 참고자료 질문은 search_personal_references의 hits를, 저장된 일정/할 일/알림 질문은 search_saved_requests의 rows를 근거로 답한다.",
        "개인 참고자료 추가가 필요할 때만 add_personal_reference를 사용한다.",
    ]
    return " ".join(parts)


def _nana_workflow_text() -> str:
    return (
        "개인 일정 생성 요청이면 extract_schedule_request 결과의 structured_request를 바로 save_structured_request payload로 전달해 앱 DB에 저장한다. "
        "3주차 이후 SQLite 도구가 등록된 상태에서는 personal_create_schedule을 거쳐 저장하지 않는다. "
        "구체적인 날짜와 시간이 정해진 회의/미팅 등록 요청은 참석자가 있어도 그룹 조율이 아니라 앱 DB 일정 저장 요청이다. "
        "extract_schedule_request의 kind가 personal_schedule이든 group_schedule이든 "
        "structured_request를 그대로 save_structured_request에 전달해 저장한다. "
        "kind와 members는 extract_schedule_request의 structured_request를 그대로 근거로 삼는다. "
        "일정 조회는 personal_list_saved_schedules로 SQLite row를 확인하고, 날짜나 기간이 있으면 date_from/date_to를 YYYY-MM-DD로 채운다. "
        "personal_list_schedules는 Week 1-2 단순 조회 전용이므로 사용하지 않는다. "
        "저장된 개인 일정은 공유 일정에도 자동 동기화된다. 개인 일정 수정/삭제는 반드시 앱 DB에 저장된 내 일정 원본을 기준으로 수행한다."
        " 새 대화에서도 Week 3 이후 SQLite에 저장된 일정은 조회 가능하다."
    )


def _kana_capability_text() -> str:
    parts = [
        "먼저 extract_schedule_request로 날짜와 멤버를 구조화한다.",
        "검색 tool의 query는 코드에서 토큰화하지 않으므로, 질문 전체가 아니라 네가 직접 고른 짧은 핵심 검색 문자열을 넣는다.",
        "이전 대화 원문이 필요하면 search_previous_conversations나 load_conversation_messages를 쓴다.",
        "멤버별 바쁜 시간은 extract_schedules_from_history 또는 collect_member_schedules로 확인한다.",
        "공유 일정 저장소 자체에 등록된 row를 확인해야 하면 list_shared_schedules를 사용한다.",
        "외부 팀원 일정 조회 답변은 tool 결과의 schedule_summary 또는 rows를 기준으로 모든 일정을 빠짐없이 나열한다. "
        "각 일정마다 반드시 멤버, 제목, 날짜, 시작 시간, 종료 시간, 비고를 포함한다. "
        "rows에 해당 멤버 일정이 있으면 일정이 없다고 말하지 않는다.",
        "팀원들과 회의 시간을 결정하는 요청이면 search_previous_conversations, extract_schedules_from_history, "
        "find_common_available_slots, decide_final_slot을 필요한 순서로 호출한다.",
        "최종 회의 시간 결정은 course repo 기준 tool인 decide_final_slot을 사용하고, "
        "후보를 먼저 계산한 뒤 네가 선택한 selected_slot 또는 selected_index를 명시해 최종 시간을 확정한다. "
        "결과의 final_slot, reason, candidates, needs_agent_selection을 근거로 답한다.",
    ]
    return " ".join(parts)


def nana_system_prompt() -> str:
    return join_system_prompt(
        [
            *week04_prompt_parts(),
            "너는 Kanana의 Nana 하위 에이전트다. 사용자의 프롬프트를 기준으로 필요한 도구를 직접 선택한다. "
            f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
            "오늘/내일/다음 주 같은 상대 날짜는 이 날짜를 기준으로 해석한다. "
            "코드가 주차나 기능을 대신 고르지 않으므로 네가 프롬프트를 읽고 필요한 tool chain을 선택한다. "
            f"{_nana_capability_text()} "
            f"{_nana_workflow_text()} "
            "요약, 후보 선택, 자연어 답변은 네가 맡고, 도구 결과에 없는 사실은 만들지 않는다. "
            "그룹 일정 조율, 여러 사람의 공통 가능 시간 계산은 직접 처리하지 말고 그 사실을 짧게 알린다.",
        ]
    )


def kana_system_prompt() -> str:
    return join_system_prompt(
        [
            *week05_prompt_parts(),
            "너는 Kanana의 Kana 하위 에이전트다. 여러 사람의 일정을 조율한다. "
            f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
            f"{_kana_capability_text()} "
            "도구 결과에 없는 일정이나 시간을 만들지 않는다. "
            "구체적인 날짜와 시간이 이미 정해진 개인/그룹 일정 등록 요청이면 Nana 저장 담당이라고 짧게 답한다.",
        ]
    )


def supervisor_system_prompt() -> str:
    return join_system_prompt(
        [
            *week05_prompt_parts(),
            "너는 Kanana 일정 비서의 프롬프트 기반 supervisor 에이전트다. 메인 런타임이나 Python 코드가 "
            f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
            "오늘/내일/다음 주 같은 상대 날짜는 이 날짜를 기준으로 해석한다. "
            "주차, 에이전트, 도구를 미리 고르지 않는다. 너는 사용자 프롬프트와 현재 대화 맥락을 읽고 "
            "Week 1-4의 개인 일정/저장/RAG 흐름은 nana_agent에, Week 5-6의 여러 사람 일정/외부 대화/그룹 조율 흐름은 "
            "kana_agent에 맡긴다. 반드시 nana_agent 또는 kana_agent 도구 중 하나를 직접 호출한 뒤, "
            "그 도구 결과만 근거로 최종 답변을 작성한다. "
            "개인 일정 생성/조회/수정/삭제, todo/reminder 저장, 개인 참고자료 검색, 내 앱 대화 목록 검색은 nana_agent에게 위임한다. "
            "Week 3 이후의 일정 생성과 조회는 SQLite 저장 도구 기준이며, "
            "단순 일정 조회에 personal_list_schedules 같은 Week 1-2 인메모리 조회를 사용하지 않는다. "
            "구체적인 날짜와 시간이 정해진 미팅/회의를 잡아줘, 등록해줘, 추가해줘라는 요청은 "
            "참석자가 있어도 일정 저장 요청이므로 nana_agent에게 위임한다. "
            "외부 멤버의 바쁜 시간 조회, 여러 사람의 공통 가능 시간 탐색, 아직 정해지지 않은 회의 시간 조율이 필요할 때만 "
            "kana_agent에게 위임한다. "
            "하위 에이전트가 자기 담당이 아니라고 답하면, 그 답을 최종 답변으로 끝내지 말고 다른 하위 에이전트를 호출해 완료한다. "
            "단, 사용자가 '그 시간', '방금 정한 시간', '아까 제안한 일정'처럼 이전 답변의 특정 "
            "후보를 그대로 사용하라고 하면 kana_agent로 다시 재탐색하지 말고, 이전 대화에 나온 "
            "날짜와 시간을 명시적으로 포함해 nana_agent에 위임한다. 사용자가 다시 찾아달라고 "
            "요청한 경우에만 kana_agent로 재계산한다. "
            "최종 답변에서는 도구 결과와 이전 대화에 실제로 나온 시간만 말하고, 도구 결과와 다른 "
            "새 시간이나 상태를 만들어내지 않는다. "
            "사용자에게는 자연스럽게 답변하고, 에이전트 이름이나 도구 이름은 사용자가 묻지 않는 한 "
            "노출하지 않는다.",
        ]
    )


def _tool_call_names(events: list[dict[str, Any]]) -> list[str]:
    return [event["tool_name"] for event in events if event.get("event") == "tool_call" and event.get("tool_name")]


def extract_langchain_trace(result: dict[str, Any]) -> dict[str, Any]:
    """Week 6 supervisor 실행 결과를 UI trace payload로 변환합니다."""

    events = extract_agent_events(result)
    inner_tool_names: list[str] = []
    final_slot_payload: dict[str, Any] | None = None
    final_decision_payload: dict[str, Any] | None = None
    selected_agent: str | None = None

    for event in events:
        if event.get("event") == "tool_call" and event.get("tool_name") in {"nana_agent", "kana_agent"}:
            selected_agent = event["tool_name"]
        content = event.get("content")
        if isinstance(content, dict):
            inner_tool_names.extend(content.get("inner_tool_names") or [])
            if content.get("final_slot_payload"):
                final_slot_payload = content["final_slot_payload"]
            elif "final_slot" in content:
                final_slot_payload = content
            if content.get("final_decision_payload"):
                final_decision_payload = content["final_decision_payload"]

    return {
        "events": events,
        "supervisor_selected_agent": selected_agent,
        "inner_tool_names": inner_tool_names,
        "final_slot_payload": final_slot_payload,
        "final_decision_payload": final_decision_payload,
    }


def tool_name(tool_object: Any) -> str:
    return getattr(tool_object, "name", getattr(tool_object, "__name__", str(tool_object)))


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

    normalized_members = normalize_external_member_names(member_names)
    normalized_date_from = normalize_date_bound(date_from)
    normalized_date_to = normalize_date_bound(date_to)
    collected = json.loads(
        collect_member_schedules.invoke(
            {
                "member_names": normalized_members,
                "date_from": normalized_date_from,
                "date_to": normalized_date_to,
            }
        )
    )
    rows = collected.get("rows", [])
    return find_common_available_slots_payload(
        member_names=["나", *normalized_members],
        date_from=normalized_date_from,
        date_to=normalized_date_to,
        busy_rows=rows,
        duration_minutes=duration_minutes,
        workday_start=workday_start,
        workday_end=workday_end,
        limit=limit,
    )


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


@tool
def decide_final_slot(
    candidate_slots: list[Any] | None = None,
    selected_slot: Any | None = None,
    selected_index: int | None = None,
    member_names: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    duration_minutes: int = 60,
    reason: str | None = None,
) -> str:
    """내 일정과 팀원 가능 시간을 비교해 최종 회의 시간을 결정합니다."""

    return json.dumps(
        decide_final_slot_payload(
            candidate_slots=candidate_slots,
            selected_slot=selected_slot,
            selected_index=selected_index,
            member_names=member_names,
            date_from=date_from,
            date_to=date_to,
            duration_minutes=duration_minutes,
            reason=reason,
            slot_finder=find_common_available_slots_dict,
        ),
        ensure_ascii=False,
    )


def kana_tools() -> list[Any]:
    return [
        extract_schedule_request,
        search_previous_conversations,
        load_conversation_messages,
        extract_schedules_from_history,
        list_shared_schedules,
        collect_member_schedules,
        find_common_available_slots,
        decide_final_slot,
    ]


def supervisor_tools() -> list[Any]:
    return [nana_agent, kana_agent]


def agent_tool_names(agent_name: str) -> list[str]:
    if agent_name == "nana_agent":
        return [tool_name(item) for item in week04_tools()]
    if agent_name == "kana_agent":
        return [tool_name(item) for item in kana_tools()]
    if agent_name == "supervisor":
        return [tool_name(item) for item in supervisor_tools()]
    return []


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
        "members": normalize_external_member_names(member_names),
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
                "error": "missing_proxy_token",
                "answer": "Nana 하위 에이전트는 프롬프트 기반 도구 호출로 동작하므로 PROXY_TOKEN이 필요합니다.",
                "trace": [],
                "inner_tool_names": [],
                "mode": "prompt_driven_subagent",
            },
            ensure_ascii=False,
        )
    global _NANA_SUBAGENT
    if _NANA_SUBAGENT is None:
        _NANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=week04_tools(),
            system_prompt=nana_system_prompt(),
        )
    result = _NANA_SUBAGENT.invoke({"messages": [{"role": "user", "content": query}]})
    trace = extract_agent_events(result)
    return json.dumps(
        {
            "ok": True,
            "selected_agent": "nana_agent",
            "answer": extract_final_text(result),
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
                "error": "missing_proxy_token",
                "answer": "Kana 하위 에이전트는 프롬프트 기반 도구 호출로 동작하므로 PROXY_TOKEN이 필요합니다.",
                "trace": [],
                "inner_tool_names": [],
                "final_slot_payload": None,
                "final_decision_payload": None,
                "mode": "prompt_driven_subagent",
            },
            ensure_ascii=False,
        )
    global _KANA_SUBAGENT
    if _KANA_SUBAGENT is None:
        _KANA_SUBAGENT = create_agent(
            model=chat_model(),
            tools=kana_tools(),
            system_prompt=kana_system_prompt(),
        )
    result = _KANA_SUBAGENT.invoke({"messages": [{"role": "user", "content": query}]})
    trace = extract_agent_events(result)
    final_slot = None
    final_decision = None
    for event in trace:
        content = event.get("content")
        if isinstance(content, dict) and "final_slot" in content:
            final_slot = content
        if isinstance(content, dict) and content.get("final_decision"):
            final_decision = content["final_decision"]
    return json.dumps(
        {
            "ok": True,
            "selected_agent": "kana_agent",
            "answer": extract_final_text(result),
            "trace": trace,
            "inner_tool_names": _tool_call_names(trace),
            "final_slot_payload": final_slot,
            "final_decision_payload": final_decision,
            "mode": "prompt_driven_subagent",
        },
        ensure_ascii=False,
    )


def build_langchain_supervisor_agent() -> object:
    """nana_agent와 kana_agent 위임 도구만 노출하는 LangChain v1 슈퍼바이저입니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _SUPERVISOR_AGENT
    if _SUPERVISOR_AGENT is None:
        _SUPERVISOR_AGENT = create_agent(
            model=chat_model(),
            tools=supervisor_tools(),
            system_prompt=supervisor_system_prompt(),
        )
    return _SUPERVISOR_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_langchain_supervisor_agent()
