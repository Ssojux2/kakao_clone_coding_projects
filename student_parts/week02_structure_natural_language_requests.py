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
KNOWN_MEMBERS = ["민준", "서연", "지훈", "유나", "도현", "A", "B", "C"]


class StructuredRequest(BaseModel):
    """LLM structured output으로 추출되는 2주차 요청 스키마입니다."""

    # [2주차][학생 구현]
    # LLM이 반드시 채워야 하는 출력 필드를 Pydantic 모델로 정의하세요.
    # 필드를 추가하거나 설명을 바꾸면 LLM이 반환하는 JSON 구조도 함께 바뀝니다.
    #
    # [참고 답안]
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

    # [2주차][학생 구현]
    # 조건문으로 분류하지 않고, LLM이 따라야 할 판단 기준을 프롬프트로 작성하세요.
    # 날짜 기준, 출력 형식, 애매한 필드 처리 규칙을 자연어로 명확히 적으세요.
    #
    # [참고 답안]
    return (
        "너는 Kanana 일정 앱의 요청 구조화 에이전트다. "
        "사용자의 한국어 자연어 요청을 읽고 반드시 StructuredRequest 스키마로만 응답한다. "
        "kind는 personal_schedule, group_schedule, todo, reminder, unknown 중 하나다. "
        "날짜는 YYYY-MM-DD, 시간은 HH:MM 24시간 형식으로 채운다. "
        f"현재 날짜는 앱 시작 시 OS에서 읽은 {current_app_date_iso()}이다. "
        "오늘, 내일, 모레, 다음 주, 요일 표현 같은 상대 날짜는 이 현재 날짜를 기준으로 판단한다. "
        "팀원 A/B/C는 필요한 경우 실제 멤버 이름과 함께 members에 반영한다. "
        "확실하지 않은 필드는 None 또는 빈 배열로 두고, reason에는 어떤 단서를 근거로 구조화했는지 짧게 쓴다."
    )


def build_langchain_structured_agent() -> object:
    """LangChain v1.0+ structured output 에이전트를 만듭니다."""

    # [2주차][학생 구현]
    # response_format에 StructuredRequest를 넘겨 LLM이 스키마를 따르도록 만드세요.
    # 여기서는 규칙 기반 parser나 if/elif 분류기를 만들지 않습니다.
    #
    # [참고 답안]
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
    # [2주차][학생 구현]
    # 에이전트 실행 결과에서 structured_response를 꺼내고 Pydantic으로 검증하세요.
    # 앱의 다른 주차 도구들은 이 함수가 반환한 StructuredRequest를 사용합니다.
    #
    # [참고 답안]
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


def extract_structured_request_with_langchain(text: str) -> StructuredRequest:
    """기존 import 호환을 위한 별칭입니다. 2주차는 항상 LLM structured output을 사용합니다."""

    return extract_structured_request(text)


def week02_tools() -> list[Any]:
    """1주차 도구에 2주차 structured output 도구를 누적한 목록입니다."""

    return [*week01_tools(), extract_schedule_request]
