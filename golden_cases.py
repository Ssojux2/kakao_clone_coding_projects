from __future__ import annotations

from typing import Any


GOLDEN_CASES = [
    {
        "id": "week1_personal_create",
        "week": 1,
        "input": "내일 오전 10시에 개인 집중 작업 일정 잡아줘",
        "expected_agent": "nana_agent",
        "expected_tool": "personal_create_schedule",
    },
    {
        "id": "week2_structured_output",
        "week": 2,
        "input": "내일 오후 2시에 회고 준비 요청을 구조화해줘",
        "expected_agent": "nana_agent",
        "expected_tool": "extract_schedule_request",
    },
    {
        "id": "week3_structured_sqlite",
        "week": 3,
        "input": "2026-05-20 오후 3시에 회고 준비 할 일 추가해줘",
        "expected_agent": "nana_agent",
        "expected_tool": "save_structured_request",
    },
    {
        "id": "week4_agentic_rag",
        "week": 4,
        "input": "내 회의 선호 참고자료와 저장된 일정을 같이 검색해줘",
        "expected_agent": "nana_agent",
        "expected_tool": "search_personal_references",
        "expected_tools": ["search_personal_references", "search_saved_requests"],
    },
    {
        "id": "week5_mcp_sqlite",
        "week": 5,
        "input": "외부 팀원들 일정 조회해줘",
        "expected_agent": "kana_agent",
        "expected_tool": "extract_schedules_from_history",
    },
    {
        "id": "week6_kana_group_decision",
        "week": 6,
        "input": "철수 영희와 다음 주 회의 시간을 잡아줘",
        "expected_agent": "kana_agent",
        "expected_tool": "decide_final_slot",
        "expected_tools": ["search_previous_conversations", "extract_schedules_from_history", "decide_final_slot"],
    },
    {
        "id": "week6_nana_personal",
        "week": 6,
        "input": "2026-05-20 오전 11시에 개인 코칭 일정 잡아줘",
        "expected_agent": "nana_agent",
        "expected_tool": "personal_create_schedule",
    },
]


def find_case_by_input(prompt: str) -> dict[str, Any] | None:
    """수업용 프롬프트와 정확히 일치하는 하네스 케이스를 반환합니다."""

    normalized = (prompt or "").strip()
    for case in GOLDEN_CASES:
        if case["input"] == normalized:
            return case
    return None


def harness_prompt_examples() -> list[dict[str, Any]]:
    """프롬프트와 문서 화면에서 함께 사용하는 압축된 하네스 예시를 반환합니다."""

    examples: list[dict[str, Any]] = []
    for case in GOLDEN_CASES:
        example = {
            "id": case["id"],
            "week": case["week"],
            "input": case["input"],
            "expected_agent": case.get("expected_agent"),
            "expected_tool": case["expected_tool"],
        }
        if case.get("expected_tools"):
            example["expected_tools"] = case["expected_tools"]
        examples.append(example)
    return examples


def sample_prompts() -> list[str]:
    """앱에 표시할 샘플 프롬프트를 반환하며, golden 하네스와 항상 맞춰 둡니다."""

    return [case["input"] for case in GOLDEN_CASES]
