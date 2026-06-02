from __future__ import annotations

import json
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from fixed.config import CONFIG
from fixed.runtime_clock import current_app_date_iso
from student_parts.week01_wake_up_nana import week01_tools


RequestKind = Literal["personal_schedule", "group_schedule", "todo", "reminder", "unknown"]
KNOWN_MEMBERS = ["철수", "영희", "민준", "서연", "지훈", "유나", "도현"]


# [수강생 구현 가이드]
# Week 2의 학생 구현 대상은 @tool이 붙은 extract_schedule_request입니다.
# Pydantic schema, prompt, LangChain agent builder는 tool 구현에 필요한 참고 코드로 읽어보세요.


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    # [수강생 참고 코드 포인트]
    # 각 필드의 타입과 기본값은 LLM 출력 검증 기준입니다.
    # 필수로 분류해야 하는 kind/original_text와, 모르면 비워둘 수 있는 날짜/시간/멤버 필드를 구분하세요.
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

    # [수강생 참고 코드 포인트]
    # prompt에는 schema만으로 알 수 없는 판단 규칙을 적습니다.
    # 특히 상대 날짜의 기준일, 날짜/시간 형식, 애매한 필드를 비워두는 규칙을 명확히 써야 합니다.
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

    # [수강생 참고 코드 포인트]
    # ChatOpenAI 모델을 만들고 create_agent에 response_format=StructuredRequest를 넘깁니다.
    # Week 2 구조화 agent는 외부 tool을 쓰지 않으므로 tools=[]로 둡니다.
    if not CONFIG.has_openai_key:
        raise RuntimeError("OPENAI_API_KEY가 .env에 필요합니다.")
    model = ChatOpenAI(model=CONFIG.openai_model, temperature=0)
    return create_agent(
        model=model,
        tools=[],
        response_format=StructuredRequest,
        system_prompt=structured_output_system_prompt(),
    )


def _structured_response_from_result(result: dict[str, Any]) -> StructuredRequest:
    # [수강생 참고 코드 포인트]
    # LangChain 결과의 structured_response가 이미 모델이면 그대로 쓰고, dict면 Pydantic으로 다시 검증합니다.
    # 이 함수에서 항상 StructuredRequest를 반환하게 만들면 tool 구현이 단순해집니다.
    structured = result.get("structured_response")
    if isinstance(structured, StructuredRequest):
        return structured
    if isinstance(structured, dict):
        return StructuredRequest.model_validate(structured)
    raise RuntimeError("LLM structured output 결과에서 StructuredRequest를 찾지 못했습니다.")


def extract_structured_request(text: str) -> StructuredRequest:
    """LLM structured output으로 사용자 요청을 StructuredRequest로 변환합니다."""

    # [수강생 참고 코드 포인트]
    # 사용자 문장을 messages 형식으로 agent.invoke에 넘기고, 결과를 schema 모델로 꺼냅니다.
    agent = build_langchain_structured_agent()
    result = agent.invoke({"messages": [{"role": "user", "content": text}]})
    return _structured_response_from_result(result)


@tool
def extract_schedule_request(query: str) -> str:
    """사용자 프롬프트를 일정 앱용 구조화 요청 JSON으로 변환합니다."""

    # [수강생 구현 포인트]
    # tool의 반환값은 JSON 문자열입니다.
    # base_date와 structured_request를 함께 넣어 trace에서 상대 날짜 해석 기준을 확인할 수 있게 합니다.
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


def extract_structured_request_with_langchain(text: str) -> StructuredRequest:
    """기존 import 호환을 위한 별칭입니다. 2주차는 항상 LLM structured output을 사용합니다."""

    return extract_structured_request(text)


def week02_tools() -> list[Any]:
    """1주차 도구에 2주차 structured output 도구를 누적한 목록입니다."""

    # [수강생 참고 코드 포인트]
    # Week 1 CRUD tool을 유지하면서 Week 2의 extract_schedule_request를 추가로 공개합니다.
    return [*week01_tools(), extract_schedule_request]
