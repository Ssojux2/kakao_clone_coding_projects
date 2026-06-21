from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import student_parts.week02_structure_natural_language_requests as week02_module
from fixed.config import CONFIG
from fixed.langchain_trace import extract_final_text


def test_week02_preserves_llm_structured_output_without_private_default(monkeypatch) -> None:
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

    assert structured["kind"] == "group_schedule"
    assert structured["members"] == ["철수", "영희"]
    assert structured["reason"] == "잘못 추측된 기본 외부 팀원"


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


def test_week02_agent_uses_structured_response_format(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_agent = object()

    def fake_create_agent(**kwargs: object) -> object:
        captured.update(kwargs)
        return fake_agent

    monkeypatch.setattr(week02_module, "CONFIG", SimpleNamespace(has_openai_key=True))
    monkeypatch.setattr(week02_module, "chat_model", lambda: "fake-model")
    monkeypatch.setattr(week02_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(week02_module, "_WEEK02_AGENT", None)

    agent = week02_module.build_week02_agent()

    assert agent is fake_agent
    assert captured["response_format"] is week02_module.StructuredRequest
    assert captured["tools"] == []


def test_extract_schedule_request_uses_structured_model_without_nested_agent(monkeypatch) -> None:
    seen: dict[str, object] = {}

    class FakeStructuredModel:
        def invoke(self, messages: list[dict[str, str]]) -> week02_module.StructuredRequest:
            seen["messages"] = messages
            return week02_module.StructuredRequest(
                kind="personal_schedule",
                title="개인 집중 작업",
                date="2026-05-21",
                start_time="10:00",
                end_time="11:00",
                members=[],
                reason="테스트 structured model",
                original_text=messages[-1]["content"],
            )

    class FakeModel:
        def with_structured_output(self, schema: object, *, method: str) -> FakeStructuredModel:
            seen["schema"] = schema
            seen["method"] = method
            return FakeStructuredModel()

    def fail_if_nested_agent_is_built() -> object:
        raise AssertionError("extract_schedule_request should not build a nested Week 2 agent")

    monkeypatch.setattr(week02_module, "chat_model", lambda: FakeModel())
    monkeypatch.setattr(week02_module, "build_week02_agent", fail_if_nested_agent_is_built)

    result = json.loads(
        week02_module.extract_schedule_request.invoke(
            {"query": "2026-05-21 오전 10시에 개인 집중 작업 일정을 1시간 잡아줘"}
        )
    )

    assert seen["schema"] is week02_module.StructuredRequest
    assert seen["method"] == "function_calling"
    assert seen["messages"][0]["role"] == "system"
    assert result["structured_request"]["title"] == "개인 집중 작업"


def test_structured_response_renders_as_class_info() -> None:
    structured = week02_module.StructuredRequest(
        kind="personal_schedule",
        title="개인 집중 작업",
        date="2026-05-21",
        start_time="10:00",
        end_time="11:00",
        members=[],
        reason="테스트 구조화",
        original_text="2026-05-21 오전 10시에 개인 집중 작업 일정 잡아줘",
    )

    text = extract_final_text({"messages": [], "structured_response": structured})

    assert text.startswith("StructuredRequest(")
    assert "kind='personal_schedule'" in text
    assert "title='개인 집중 작업'" in text


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
