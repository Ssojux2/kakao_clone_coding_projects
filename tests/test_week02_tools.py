from __future__ import annotations

import json

import pytest

import student_parts.week02_structure_natural_language_requests as week02_module
from fixed.config import CONFIG


def test_week02_private_meeting_does_not_default_to_external_members(monkeypatch) -> None:
    def fake_extract_structured_request(query: str) -> week02_module.StructuredRequest:
        return week02_module.StructuredRequest(
            kind="group_schedule",
            title="개발 미팅",
            date="2026-06-22",
            start_time="10:00",
            end_time="11:00",
            members=["철수", "영희"],
            reason="잘못 추측된 기본 외부 팀원",
            original_text=query,
        )

    monkeypatch.setattr(week02_module, "extract_structured_request", fake_extract_structured_request)

    result = json.loads(
        week02_module.extract_schedule_request.invoke({"query": "내 개발 미팅 2026-06-22 오전 10시에 잡아줘"})
    )
    structured = result["structured_request"]

    assert structured["kind"] == "personal_schedule"
    assert structured["members"] == ["나"]


def test_week02_explicit_external_team_keeps_default_external_members(monkeypatch) -> None:
    def fake_extract_structured_request(query: str) -> week02_module.StructuredRequest:
        return week02_module.StructuredRequest(
            kind="group_schedule",
            title="외부 팀원 일정 조회",
            date=None,
            start_time=None,
            end_time=None,
            members=["철수", "영희"],
            reason="외부 팀원 요청",
            original_text=query,
        )

    monkeypatch.setattr(week02_module, "extract_structured_request", fake_extract_structured_request)

    result = json.loads(week02_module.extract_schedule_request.invoke({"query": "외부 팀원들 일정 조회해줘"}))
    structured = result["structured_request"]

    assert structured["kind"] == "group_schedule"
    assert structured["members"] == ["철수", "영희"]


@pytest.mark.integration
def test_week02_extract_schedule_request_uses_real_openai_structured_output() -> None:
    assert CONFIG.has_openai_key, "Week 2는 실제 structured output 호출이 필요합니다. .env에 PROXY_TOKEN을 설정하세요."

    result = json.loads(
        week02_module.extract_schedule_request.invoke(
            {"query": "2026-05-21 오전 10시에 개인 집중 작업 일정을 1시간 잡아줘"}
        )
    )
    structured = result["structured_request"]

    assert result["tool_name"] == "extract_schedule_request"
    assert structured["kind"] == "personal_schedule"
    assert structured["date"] == "2026-05-21"
    assert structured["start_time"] == "10:00"
    assert "개인" in structured["title"] or "집중" in structured["title"]
