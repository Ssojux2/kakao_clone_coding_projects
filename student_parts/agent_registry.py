from __future__ import annotations

import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fixed.config import CONFIG
from student_parts.week01_wake_up_nana import (
    extract_agent_events,
    extract_final_text,
    extract_langchain_trace as extract_common_langchain_trace,
    message_tool_call_names,
    stream_chunk_messages,
)


WEEK_AGENT_MODULES = {
    1: "student_parts.week01_wake_up_nana",
    2: "student_parts.week02_structure_natural_language_requests",
    3: "student_parts.week03_build_nanas_logbook",
    4: "student_parts.week04_retrieve_nanas_memory",
    5: "student_parts.week05_load_kanas_past_conversations",
    6: "student_parts.week06_kanamate_decides_schedule",
}


@dataclass
class ActiveWeekAgentResult:
    answer: str
    trace: dict[str, Any]


@dataclass
class ActiveWeekAgentStreamEvent:
    status_text: str | None = None
    result: ActiveWeekAgentResult | None = None


def normalize_active_week(active_week: int | str | None) -> int:
    try:
        week = int(active_week or 1)
    except (TypeError, ValueError):
        week = 1
    if week not in WEEK_AGENT_MODULES:
        raise ValueError("active_week은 1부터 6 사이여야 합니다.")
    return week


def _extract_trace(module: Any, result: dict[str, Any]) -> dict[str, Any]:
    extractor = getattr(module, "extract_langchain_trace", extract_common_langchain_trace)
    trace = extractor(result)
    if isinstance(trace, dict):
        return trace
    return extract_common_langchain_trace(result)


def run_active_week_agent(active_week: int | str | None, messages: list[dict[str, str]]) -> ActiveWeekAgentResult:
    """선택된 주차의 student_parts agent를 실행하고 UI trace payload로 변환합니다."""

    week = normalize_active_week(active_week)
    if not CONFIG.has_openai_key:
        return ActiveWeekAgentResult(
            answer=(
                f"Week {week} 프롬프트 기반 에이전트 실행에는 .env의 PROXY_TOKEN이 필요합니다. "
                "키를 추가하면 선택한 주차의 agent가 prompt와 tool을 직접 선택해 실행합니다."
            ),
            trace={
                "mode": "active_week_agent",
                "active_week": week,
                "error": "missing_proxy_token",
                "events": [],
            },
        )

    try:
        module = importlib.import_module(WEEK_AGENT_MODULES[week])
        builder = getattr(module, "build_week_agent")
        agent = builder()
        result = agent.invoke({"messages": messages})
        trace = _extract_trace(module, result)
        trace["mode"] = "active_week_agent"
        trace["active_week"] = week
        return ActiveWeekAgentResult(answer=extract_final_text(result), trace=trace)
    except Exception as exc:
        return ActiveWeekAgentResult(
            answer=f"Week {week} agent 실행 중 오류가 발생했습니다: {type(exc).__name__}: {exc}",
            trace={
                "mode": "active_week_agent",
                "active_week": week,
                "events": [],
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
        )


def stream_active_week_agent(
    active_week: int | str | None,
    messages: list[dict[str, str]],
) -> Iterator[ActiveWeekAgentStreamEvent]:
    """선택된 주차 agent를 stream으로 실행하며 UI progress 이벤트를 함께 반환합니다."""

    week = normalize_active_week(active_week)
    yield ActiveWeekAgentStreamEvent(status_text="답변을 진행중입니다")
    if not CONFIG.has_openai_key:
        yield ActiveWeekAgentStreamEvent(result=_missing_openai_key_result(week))
        return

    collected_messages: list[Any] = []
    try:
        module = importlib.import_module(WEEK_AGENT_MODULES[week])
        builder = getattr(module, "build_week_agent")
        agent = builder()
        for chunk in agent.stream({"messages": messages}, stream_mode="updates"):
            for message in stream_chunk_messages(chunk):
                collected_messages.append(message)
                for tool_name in message_tool_call_names(message):
                    yield ActiveWeekAgentStreamEvent(status_text=f"현재 {tool_name} 실행 중")

        result = {"messages": collected_messages}
        trace = _extract_trace(module, result)
        trace["mode"] = "active_week_agent"
        trace["active_week"] = week
        yield ActiveWeekAgentStreamEvent(result=ActiveWeekAgentResult(answer=extract_final_text(result), trace=trace))
    except Exception as exc:
        yield ActiveWeekAgentStreamEvent(
            result=ActiveWeekAgentResult(
                answer=f"Week {week} agent 실행 중 오류가 발생했습니다: {type(exc).__name__}: {exc}",
                trace={
                    "mode": "active_week_agent",
                    "active_week": week,
                    "events": extract_agent_events({"messages": collected_messages}),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
        )


def _missing_openai_key_result(week: int) -> ActiveWeekAgentResult:
    return ActiveWeekAgentResult(
        answer=(
            f"Week {week} 프롬프트 기반 에이전트 실행에는 .env의 PROXY_TOKEN이 필요합니다. "
            "키를 추가하면 선택한 주차의 agent가 prompt와 tool을 직접 선택해 실행합니다."
        ),
        trace={
            "mode": "active_week_agent",
            "active_week": week,
            "error": "missing_proxy_token",
            "events": [],
        },
    )
