from __future__ import annotations

import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from pydantic import BaseModel, Field

from fixed.config import CONFIG
from fixed.llm import chat_model
from fixed.runtime_clock import current_app_date_iso
from student_parts.week01_wake_up_nana import week01_tools


RequestKind = Literal["personal_schedule", "group_schedule", "todo", "reminder", "unknown"]
KNOWN_MEMBERS = ["철수", "영희", "민준", "서연", "지훈", "유나", "도현"]
_WEEK02_AGENT: Any | None = None


# [수강생 구현 가이드]
#
# 목표
#   사용자의 한국어 자연어 요청을 일정 앱이 읽을 수 있는 StructuredRequest로 바꿉니다.
#   Week 1은 이미 정해진 인자를 받아 일정을 만들었다면, Week 2는 "내일 오후 3시" 같은
#   자연어를 날짜/시간/종류/멤버 필드로 구조화하는 단계입니다.
#
# 구현 대상
#   extract_schedule_request
#      - query 문자열을 extract_structured_request(query)에 넘깁니다.
#      - 반환된 Pydantic StructuredRequest 객체를 model_dump()로 dict로 바꿉니다.
#      - ok, tool_name, base_date, structured_request를 담은 JSON 문자열을 반환합니다.
#
# StructuredRequest 읽는 법
#   - kind: personal_schedule, group_schedule, todo, reminder, unknown 중 하나입니다.
#   - title/date/start_time/end_time: 일정 앱이 실제 저장이나 생성에 사용할 핵심 필드입니다.
#   - members: 참석자/관련 멤버 list입니다. 모르면 빈 list로 둡니다.
#   - priority/reason/original_text: 할 일 우선순위, 판단 근거, 원문 보존용 필드입니다.
#   - 모르는 값을 억지로 만들지 않는 것이 중요합니다. 확실하지 않으면 None 또는 빈 list가 안전합니다.
#
# 참고 코드
#   StructuredRequest schema, structured_output_system_prompt(), build_langchain_structured_agent()는
#   LLM structured output이 어떻게 검증되는지 보여 주는 참고 코드입니다.
#   week02_tools()는 Week 1 tool 목록 뒤에 extract_schedule_request를 누적해 agent에 공개합니다.
#
# 검증 방법
#   ./run.sh --week2로 실행한 뒤 "다음 주 화요일 오후 3시에 철수랑 회의 잡아줘" 같은 문장을 입력합니다.
#   상세 trace에서 extract_schedule_request가 호출됐는지 확인합니다.
#   tool 결과의 structured_request.kind/date/start_time/members가 기대한 값인지 비교합니다.


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    kind: RequestKind = Field(description="분류된 요청 종류")
    title: str | None = Field(default=None, description="일정, 할 일, 알림 제목")
    date: str | None = Field(default=None, description="연-월-일(YYYY-MM-DD) 형식 날짜")
    start_time: str | None = Field(default=None, description="시:분(HH:MM) 형식 시작 시간")
    end_time: str | None = Field(default=None, description="시:분(HH:MM) 형식 종료 시간")
    members: list[str] = Field(default_factory=list, description="참석자 또는 관련 멤버")
    priority: str | None = Field(default=None, description="할 일 우선순위")
    reason: str | None = Field(default=None, description="분류/추출 근거")
    original_text: str = Field(default="", description="원본 사용자 입력")


def structured_output_system_prompt() -> str:
    """2주차 LLM structured output 에이전트가 따르는 시스템 프롬프트입니다."""

    return (
        "너는 Kanana 일정 앱의 요청 구조화 에이전트다. "
        "사용자의 한국어 자연어 요청을 읽고 반드시 StructuredRequest 스키마로만 응답한다. "
        "kind는 personal_schedule, group_schedule, todo, reminder, unknown 중 하나다. "
        "날짜는 YYYY-MM-DD, 시간은 HH:MM 24시간 형식으로 채운다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "오늘, 내일, 모레, 다음 주, 요일 표현 같은 상대 날짜는 이 현재 날짜를 기준으로 판단한다. "
        "외부 팀원처럼 구체적인 이름이 없는 표현은 기본 외부 팀원 철수와 영희를 members에 반영한다. "
        "확실하지 않은 필드는 None 또는 빈 배열로 두고, reason에는 어떤 단서를 근거로 구조화했는지 짧게 쓴다."
    )


def build_langchain_structured_agent() -> object:
    """LangChain v1.0+ structured output 에이전트를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    model = chat_model()
    return create_agent(
        model=model,
        tools=[],
        response_format=StructuredRequest,
        system_prompt=structured_output_system_prompt(),
    )


def _structured_response_from_result(result: dict[str, Any]) -> StructuredRequest:
    structured = result.get("structured_response")
    if isinstance(structured, StructuredRequest):
        return structured
    if isinstance(structured, dict):
        return StructuredRequest.model_validate(structured)
    raise RuntimeError("LLM structured output 결과에서 StructuredRequest를 찾지 못했습니다.")


def extract_structured_request(text: str) -> StructuredRequest:
    """LLM structured output으로 사용자 요청을 StructuredRequest로 변환합니다."""

    agent = build_langchain_structured_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": text}]})
    return _structured_response_from_result(result)


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


def week02_tools() -> list[Any]:
    """1주차 도구에 2주차 structured output 도구를 누적한 목록입니다."""

    return [*week01_tools(), extract_schedule_request]


def week02_system_prompt() -> str:
    """2주차 단일 agent가 따르는 시스템 프롬프트입니다."""

    return (
        "너는 Kanana의 Week 2 요청 구조화 agent다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "사용자의 자연어 일정 요청을 읽고, 날짜/시간/멤버/종류 판단이 필요하면 extract_schedule_request를 먼저 호출한다. "
        "개인 일정 생성, 조회, 삭제는 Week 1 tool을 사용한다. "
        "Week 2에서는 SQLite 저장, RAG, 외부 멤버 일정 조율을 처리하지 않는다. "
        "도구 결과의 structured_request를 근거로 짧고 자연스럽게 답한다."
    )


def build_week02_agent() -> object:
    """Week 1-2 누적 tool 목록을 노출하는 단일 LangChain agent를 만듭니다."""

    if not CONFIG.has_openai_key:
        raise RuntimeError("PROXY_TOKEN이 .env에 필요합니다.")
    global _WEEK02_AGENT
    if _WEEK02_AGENT is None:
        _WEEK02_AGENT = create_agent(
            model=chat_model(),
            tools=week02_tools(),
            system_prompt=week02_system_prompt(),
        )
    return _WEEK02_AGENT


def build_week_agent() -> object:
    """active-week registry가 호출하는 표준 Week agent builder입니다."""

    return build_week02_agent()
